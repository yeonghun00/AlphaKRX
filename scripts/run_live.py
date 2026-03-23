#!/usr/bin/env python3
"""
Live trading runner — checks rebalancing schedule and submits orders via Kiwoom REST API.

Usage
-----
  # Check if rebalancing is needed today (dry-run)
  python3 scripts/run_live.py --run myrun

  # Check + submit orders (paper trading)
  python3 scripts/run_live.py --run myrun --execute

  # Interactively select a run
  python3 scripts/run_live.py

Setup
-----
  Set API credentials via environment variables (or .env file):
    KIWOOM_APP_KEY=...
    KIWOOM_APP_SECRET=...
    KIWOOM_ACCOUNT=12345678-01   # account number
    KIWOOM_MOCK=true             # true = paper trading, false = live
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env if present
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

RUNS_DIR  = Path("runs")
LIVE_DIR  = Path("live")
STATE_FILE = LIVE_DIR / "state.json"

# ---------------------------------------------------------------------------
# Trading calendar (Korean market)
# ---------------------------------------------------------------------------

def _get_krx_calendar():
    try:
        import exchange_calendars as ec
        return ec.get_calendar("XKRX")
    except Exception:
        return None


def _trading_days_between(start: str, end: str) -> list[str]:
    """Return list of KRX trading days (YYYYMMDD) between start and end inclusive."""
    cal = _get_krx_calendar()
    if cal is None:
        # Fallback: weekdays only
        dates = pd.bdate_range(start, end)
        return [d.strftime("%Y%m%d") for d in dates]
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    try:
        sessions = cal.sessions_in_range(s, e)
        return [d.strftime("%Y%m%d") for d in sessions]
    except Exception:
        dates = pd.bdate_range(s, e)
        return [d.strftime("%Y%m%d") for d in dates]


def _add_trading_days(date_str: str, n: int) -> str:
    """Return the date that is n KRX trading days after date_str."""
    cal = _get_krx_calendar()
    ts = pd.Timestamp(date_str)
    if cal is None:
        result = ts + pd.offsets.BDay(n)
        return result.strftime("%Y%m%d")
    # Wrap all calendar calls: is_session/session_offset can throw DateOutOfBounds
    # if ts is outside the calendar's supported range, or NotSessionError if ts
    # is not a trading day. Fall back to business days in either case.
    try:
        if not cal.is_session(ts):
            future = cal.sessions_in_range(ts, ts + pd.Timedelta(days=14))
            if future.empty:
                raise ValueError("no sessions found in range")
            ts = future[0]
        result = cal.session_offset(ts, n)
        return result.strftime("%Y%m%d")
    except Exception:
        result = ts + pd.offsets.BDay(n)
        return result.strftime("%Y%m%d")


def _tomorrow_str() -> str:
    return (datetime.today() + timedelta(days=1)).strftime("%Y%m%d")


def _today_str() -> str:
    return datetime.today().strftime("%Y%m%d")


def _next_trading_day(date_str: str) -> str:
    return _add_trading_days(date_str, 1)

# ---------------------------------------------------------------------------
# Run discovery
# ---------------------------------------------------------------------------

def list_runs() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted([
        d.name for d in RUNS_DIR.iterdir()
        if d.is_dir() and (d / "results.csv").exists() and (d / "picks.csv").exists()
    ])


def pick_run(run_name: str) -> str:
    """Interactively pick a run if not specified."""
    runs = list_runs()
    if not runs:
        print("ERROR: No completed runs found in runs/")
        sys.exit(1)
    if run_name and run_name in runs:
        return run_name
    if run_name and run_name not in runs:
        print(f"WARNING: run '{run_name}' not found.")

    print("\nAvailable runs:")
    for i, r in enumerate(runs, 1):
        results_csv = RUNS_DIR / r / "results.csv"
        picks_csv   = RUNS_DIR / r / "picks.csv"
        try:
            res = pd.read_csv(results_csv)
            last_date = res["date"].max()
            n_rebals  = len(res)
            horizon   = _extract_horizon(picks_csv)
            print(f"  [{i}] {r:<20}  last_rebal={last_date}  rebals={n_rebals}  horizon={horizon}d")
        except Exception:
            print(f"  [{i}] {r}")

    while True:
        choice = input("\nSelect run number (or name): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(runs):
            return runs[int(choice) - 1]
        if choice in runs:
            return choice
        print("Invalid choice, try again.")


def _extract_horizon(picks_csv: Path) -> int:
    """Extract horizon from forward_return column name, e.g. forward_return_42d → 42."""
    try:
        cols = pd.read_csv(picks_csv, nrows=0).columns.tolist()
        for c in cols:
            m = re.search(r"forward_return_(\d+)d", c)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return 21  # fallback

# ---------------------------------------------------------------------------
# Schedule logic
# ---------------------------------------------------------------------------

def compute_next_rebal(run_dir: Path) -> dict:
    """
    Given a run directory, compute the next rebalancing signal date.

    Returns dict with:
        last_rebal      : last rebalancing signal date (YYYYMMDD)
        horizon         : horizon in trading days
        next_rebal      : next rebalancing signal date (YYYYMMDD)
        next_exec       : execution date = next_rebal + 1 trading day (YYYYMMDD)
        trading_days_left : trading days from today until next_exec
        status          : 'today' | 'tomorrow' | 'future' | 'overdue'
    """
    picks_csv   = run_dir / "picks.csv"
    results_csv = run_dir / "results.csv"

    results = pd.read_csv(results_csv, dtype={"date": str})
    last_rebal = str(results["date"].max()).replace("-", "")

    horizon = _extract_horizon(picks_csv)
    today   = _today_str()

    # Advance rebal signal date until next_exec is today or in the future.
    # Track skipped rebalancings so we can warn the user.
    candidate      = last_rebal
    skipped_rebals = []
    while True:
        next_rebal = _add_trading_days(candidate, horizon)
        next_exec  = _next_trading_day(next_rebal)
        if next_exec >= today:
            break
        skipped_rebals.append({"signal": next_rebal, "exec": next_exec})
        candidate = next_rebal

    tomorrow  = _tomorrow_str()
    days_left = len(_trading_days_between(today, next_exec)) - 1

    if next_exec == today:
        status = "today"
    elif next_exec == tomorrow:
        status = "tomorrow"
    else:
        status = "future"

    return {
        "last_rebal":         last_rebal,
        "horizon":            horizon,
        "next_rebal":         next_rebal,
        "next_exec":          next_exec,
        "trading_days_left":  days_left,
        "status":             status,
        "skipped_rebals":     skipped_rebals,
    }


def get_current_holdings(run_dir: Path) -> set[str]:
    """Return the set of stock codes held from the last rebalancing."""
    picks_csv = run_dir / "picks.csv"
    picks = pd.read_csv(picks_csv, dtype={"stock_code": str, "date": str})
    last_date = picks["date"].max()
    return set(picks[picks["date"] == last_date]["stock_code"].tolist())


# ---------------------------------------------------------------------------
# Live state management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Load live trading state from live/state.json."""
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        return {
            "last_executed_rebal": None,   # signal date of the last executed rebalancing
            "current_holdings": [],        # list of stock codes currently held
            "run_name": None,
        }
    import json
    return json.loads(STATE_FILE.read_text())


def save_state(state: dict) -> None:
    import json
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def save_order_log(exec_date: str, sell_orders: list, buy_orders: list, new_holdings: list) -> None:
    import json
    log = {
        "exec_date":    exec_date,
        "sell_orders":  sell_orders,
        "buy_orders":   buy_orders,
        "new_holdings": new_holdings,
        "logged_at":    datetime.now().isoformat(),
    }
    order_path = LIVE_DIR / "orders" / f"{exec_date}.json"
    order_path.parent.mkdir(parents=True, exist_ok=True)
    order_path.write_text(json.dumps(log, ensure_ascii=False, indent=2))
    print(f"  Order log saved → {order_path}")

# ---------------------------------------------------------------------------
# Kiwoom REST API client
# ---------------------------------------------------------------------------

class KiwoomClient:
    """
    Thin wrapper around the Kiwoom REST API (paper trading / live trading).

    Official docs: https://apiportal.kiwoom.com
    Environment variables:
        KIWOOM_APP_KEY     : app key
        KIWOOM_APP_SECRET  : app secret
        KIWOOM_ACCOUNT     : account number (e.g. "12345678-01")
        KIWOOM_MOCK        : "true" → paper trading, "false" → live trading (default: true)
    """

    MOCK_BASE = "https://mockapi.kiwoom.com"   # paper trading endpoint
    REAL_BASE = "https://openapi.kiwoom.com"   # live trading endpoint

    def __init__(self):
        self.app_key    = os.environ.get("KIWOOM_APP_KEY", "")
        self.app_secret = os.environ.get("KIWOOM_APP_SECRET", "")
        self.account    = os.environ.get("KIWOOM_ACCOUNT", "")
        self.mock       = os.environ.get("KIWOOM_MOCK", "true").lower() != "false"
        self.base_url   = self.MOCK_BASE if self.mock else self.REAL_BASE
        self._token: str = ""

    def _check_credentials(self) -> bool:
        if not self.app_key or not self.app_secret or not self.account:
            print(
                "\n[Kiwoom] API credentials not set.\n"
                "  export KIWOOM_APP_KEY=...\n"
                "  export KIWOOM_APP_SECRET=...\n"
                "  export KIWOOM_ACCOUNT=12345678-01\n"
                "  export KIWOOM_MOCK=true\n"
            )
            return False
        return True

    def authenticate(self) -> bool:
        """Obtain an OAuth2 access token."""
        if not self._check_credentials():
            return False
        try:
            import requests
            resp = requests.post(
                f"{self.base_url}/oauth2/token",
                headers={"Content-Type": "application/json"},
                json={
                    "grant_type":    "client_credentials",
                    "appkey":        self.app_key,
                    "appsecretkey":  self.app_secret,
                },
                timeout=10,
            )
            resp.raise_for_status()
            self._token = resp.json().get("access_token", "")
            print(f"[Kiwoom] Authenticated ({'paper' if self.mock else 'live'})")
            return True
        except Exception as e:
            print(f"[Kiwoom] Authentication failed: {e}")
            return False

    def _headers(self) -> dict:
        return {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self._token}",
            "appkey":        self.app_key,
            "appsecretkey":  self.app_secret,
        }

    def get_holdings(self) -> pd.DataFrame:
        """Fetch current portfolio holdings from the account."""
        try:
            import requests
            resp = requests.get(
                f"{self.base_url}/v1/account/balance",
                headers=self._headers(),
                params={"account": self.account},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            # Parse according to Kiwoom API docs — adjust field names if needed
            holdings = data.get("output", [])
            return pd.DataFrame(holdings)
        except Exception as e:
            print(f"[Kiwoom] Failed to fetch holdings: {e}")
            return pd.DataFrame()

    def order_sell(self, stock_code: str, quantity: int, price: int = 0) -> bool:
        """Place a sell order (price=0 → market order)."""
        return self._order(stock_code, quantity, price, side="sell")

    def order_buy(self, stock_code: str, quantity: int, price: int = 0) -> bool:
        """Place a buy order (price=0 → market order)."""
        return self._order(stock_code, quantity, price, side="buy")

    def _order(self, stock_code: str, quantity: int, price: int, side: str) -> bool:
        try:
            import requests
            payload = {
                "account":    self.account,
                "stock_code": stock_code,
                "order_type": "01" if side == "buy" else "02",   # 01=buy, 02=sell
                "quantity":   quantity,
                "price":      price,        # 0 = market order
                "price_type": "01" if price == 0 else "00",      # 00=limit, 01=market
            }
            resp = requests.post(
                f"{self.base_url}/v1/order/stock",
                headers=self._headers(),
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            order_no = result.get("order_no", "?")
            print(f"  [ORDER OK] {side.upper()} {stock_code} x{quantity}  order_no={order_no}")
            return True
        except Exception as e:
            print(f"  [ORDER FAILED] {side.upper()} {stock_code}: {e}")
            return False

# ---------------------------------------------------------------------------
# Order generation
# ---------------------------------------------------------------------------

def build_orders(
    new_picks: pd.DataFrame,
    current_holdings: set[str],
    top_n: int,
    portfolio_krw: int,
) -> tuple[list[dict], list[dict]]:
    """
    Compare current holdings vs new picks to generate buy/sell lists.

    Returns (sell_orders, buy_orders).
    Each order: {stock_code, name, quantity, price}
    """
    new_codes  = set(new_picks.head(top_n)["stock_code"].tolist())
    sell_codes = current_holdings - new_codes
    buy_codes  = new_codes - current_holdings

    per_stock_krw = portfolio_krw // max(len(new_codes), 1)

    sell_orders = []
    for code in sell_codes:
        sell_orders.append({
            "stock_code": code,
            "name":       new_picks[new_picks["stock_code"] == code]["name"].values[0]
                          if code in new_picks["stock_code"].values else code,
            "quantity":   0,    # full exit: actual quantity is filled from API balance query
            "price":      0,    # market order
        })

    buy_orders = []
    for _, row in new_picks[new_picks["stock_code"].isin(buy_codes)].iterrows():
        price = int(row.get("closing_price", row.get("buy_price", 0)))
        qty   = per_stock_krw // max(price, 1) if price > 0 else 0
        buy_orders.append({
            "stock_code": str(row["stock_code"]),
            "name":       str(row.get("name", "")),
            "quantity":   qty,
            "price":      0,    # market order
        })

    return sell_orders, buy_orders


def print_order_summary(
    schedule: dict,
    current_holdings: set[str],
    new_picks: pd.DataFrame,
    sell_orders: list[dict],
    buy_orders:  list[dict],
    top_n: int,
) -> None:
    new_codes  = set(new_picks.head(top_n)["stock_code"].tolist())
    hold_codes = current_holdings & new_codes

    print("\n" + "=" * 60)
    print("  REBALANCING PLAN")
    print("=" * 60)
    print(f"  Next signal date : {schedule['next_rebal']}")
    print(f"  Execution date   : {schedule['next_exec']}  (T+1)")
    print(f"  Current holdings : {len(current_holdings)} stocks")
    print(f"  New portfolio    : {top_n} stocks")

    if hold_codes:
        print(f"\n  [HOLD] {len(hold_codes)} unchanged: {', '.join(sorted(hold_codes))}")

    if sell_orders:
        print(f"\n  [SELL] {len(sell_orders)} stocks:")
        for o in sell_orders:
            print(f"     {o['stock_code']}  {o['name']}")

    if buy_orders:
        print(f"\n  [BUY]  {len(buy_orders)} stocks:")
        for o in buy_orders:
            print(f"     {o['stock_code']}  {o['name']}  qty={o['quantity']}  market")

    print("=" * 60)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live rebalancing runner with Kiwoom REST API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  python3 scripts/run_live.py                        # interactively select run and check schedule
  python3 scripts/run_live.py --run myrun            # check schedule for a specific run
  python3 scripts/run_live.py --run myrun --execute  # check schedule and submit orders
        """,
    )
    parser.add_argument("--run",       type=str, default="",
                        help="Run name (subfolder under runs/). Prompts interactively if omitted.")
    parser.add_argument("--execute",   action="store_true",
                        help="Submit orders (default: dry-run only)")
    parser.add_argument("--top",       type=int, default=0,
                        help="Number of portfolio stocks (0 = read from model.pkl)")
    parser.add_argument("--portfolio", type=int, default=100_000_000,
                        help="Total portfolio value in KRW (default: 100,000,000)")
    parser.add_argument("--no-update", action="store_true",
                        help="Skip DB update step")
    parser.add_argument("--force", action="store_true",
                        help="Force re-run even if rebalancing was already executed")
    args = parser.parse_args()

    # ── 1. Select run ────────────────────────────────────────────────────
    run_name = pick_run(args.run)
    run_dir  = RUNS_DIR / run_name
    print(f"\n[Run] {run_name}")

    # ── 2. Update DB ──────────────────────────────────────────────────────
    if not args.no_update:
        print("\n[1/4] Updating DB...")
        import subprocess
        r1 = subprocess.run([sys.executable, "scripts/run_etl.py", "update"], check=False)
        r2 = subprocess.run([sys.executable, "scripts/run_index_etl.py", "--daily-update"], check=False)
        r3 = subprocess.run([sys.executable, "etl/adj_price_etl.py"], check=False)
        if any(r.returncode != 0 for r in [r1, r2, r3]):
            print("  WARNING: one or more update steps failed. Continuing anyway.")
    else:
        print("\n[1/4] Skipping DB update (--no-update)")

    # ── 3. Check rebalancing schedule ────────────────────────────────────
    print("\n[2/4] Checking rebalancing schedule...")
    schedule = compute_next_rebal(run_dir)
    horizon  = schedule["horizon"]

    state = load_state()
    already_done = (state.get("last_executed_rebal") == schedule["next_rebal"])

    print(f"  Last backtest rebalancing : {schedule['last_rebal']}")
    print(f"  Horizon                   : {horizon} trading days")

    # Warn about missed rebalancings
    skipped = schedule.get("skipped_rebals", [])
    if skipped:
        print(f"\n  WARNING: {len(skipped)} missed rebalancing(s) (already passed):")
        for s in skipped:
            print(f"     signal {s['signal']} → exec {s['exec']}  (not executed)")
        print(f"  → Normal on first run. Start executing from the next rebalancing.")

    print(f"\n  Next signal date : {schedule['next_rebal']}")
    print(f"  Execution date   : {schedule['next_exec']}  (recommended before 09:00 KST)")

    if state.get("current_holdings"):
        print(f"  Current holdings : {len(state['current_holdings'])} stocks  {state['current_holdings']}")

    if already_done:
        print(f"\n  Already executed rebalancing for signal date {schedule['next_rebal']}.")
        print(f"  Use --force to re-run.")
        if not getattr(args, "force", False):
            return

    status = schedule["status"]
    if status == "future":
        days = schedule["trading_days_left"]
        print(f"\n  {days} trading day(s) until execution. No orders needed yet.")
        print(f"  Run with --execute on or before the execution date before 09:00 KST.")
        return
    elif status == "tomorrow":
        print(f"\n  Execution date is tomorrow ({schedule['next_exec']}).")
        print(f"  Picks computed now. Run with --execute tomorrow before 09:00 KST.")
        # Continue to compute picks (no order submission yet)
    elif status == "today":
        print(f"\n  Execution date is TODAY ({schedule['next_exec']}). Proceeding with open-market orders.")

    # ── 4. Compute new picks ──────────────────────────────────────────────
    print("\n[3/4] Computing new portfolio...")

    from ml.models.base import BaseRanker
    from ml.features import FeatureEngineer

    model_path = run_dir / "model.pkl"
    if not model_path.exists():
        print(f"ERROR: model.pkl not found in {run_dir}")
        sys.exit(1)

    model = BaseRanker.load(str(model_path))
    meta  = model.metadata or {}

    # top_n
    top_n = args.top or meta.get("top_n", 10)

    # market cap
    min_cap = meta.get("min_market_cap", 500_000_000_000)
    max_cap = meta.get("max_market_cap", None)

    # sector neutral
    sector_neutral = meta.get("sector_neutral_score", True)

    print(f"  top_n={top_n}  min_cap={min_cap:,}  max_cap={max_cap}  sector_neutral={sector_neutral}")

    fe = FeatureEngineer()
    today = _today_str()

    pred_df = fe.prepare_prediction_data(
        end_date=today,
        target_horizon=horizon,
        min_market_cap=min_cap,
        max_market_cap=max_cap,
    )
    if pred_df.empty:
        print("ERROR: No prediction data available. Check DB update.")
        sys.exit(1)

    # Filter suspended stocks
    if "value" in pred_df.columns:
        pred_df = pred_df[pred_df["value"] > 0].copy()

    # Score
    pred_df["score"] = model.predict(pred_df)
    if sector_neutral and "sector" in pred_df.columns:
        sec_mean = pred_df.groupby("sector")["score"].transform("mean")
        sec_std  = pred_df.groupby("sector")["score"].transform("std").replace(0, np.nan)
        pred_df["score_rank"] = (
            (pred_df["score"] - sec_mean) / sec_std
        ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    else:
        pred_df["score_rank"] = pred_df["score"]

    pred_df["rank"] = pred_df["score_rank"].rank(ascending=False, method="first").astype(int)
    new_picks = pred_df.sort_values("rank")

    # Current holdings — prefer live/state.json; fall back to picks.csv on first run
    if state.get("current_holdings") and state.get("run_name") == run_name:
        current_holdings = set(state["current_holdings"])
        print(f"  [State] {len(current_holdings)} holdings loaded from live/state.json")
    else:
        current_holdings = get_current_holdings(run_dir)
        print(f"  [State] {len(current_holdings)} holdings loaded from picks.csv (first run)")

    # Build orders
    sell_orders, buy_orders = build_orders(
        new_picks=new_picks,
        current_holdings=current_holdings,
        top_n=top_n,
        portfolio_krw=args.portfolio,
    )

    print_order_summary(schedule, current_holdings, new_picks, sell_orders, buy_orders, top_n)

    # ── 5. Submit orders ──────────────────────────────────────────────────
    if status == "tomorrow" and not args.execute:
        print("\n  [Tomorrow] Picks computed. Run with --execute tomorrow before 09:00 KST:")
        print(f"  python3 scripts/run_live.py --run {run_name} --execute")
        return

    if not args.execute:
        print("\n  [Dry-run] --execute flag not set. No orders submitted.")
        print(f"  To place orders: python3 scripts/run_live.py --run {run_name} --execute")
        return

    print("\n[4/4] Submitting orders...")

    total = len(sell_orders) + len(buy_orders)
    confirm = input(f"\n  Confirm {len(sell_orders)} sell + {len(buy_orders)} buy ({total} total)? (y/n): ").strip().lower()
    if confirm != "y":
        print("  Cancelled.")
        return

    client = KiwoomClient()
    if not client.authenticate():
        print("  Authentication failed. Aborting.")
        return

    # Sell first to free up capital
    print(f"\n  Sell orders ({len(sell_orders)}):")
    for o in sell_orders:
        client.order_sell(o["stock_code"], o["quantity"], price=0)

    # Then buy
    print(f"\n  Buy orders ({len(buy_orders)}):")
    for o in buy_orders:
        client.order_buy(o["stock_code"], o["quantity"], price=0)

    # Persist state
    new_holdings = list(set(new_picks.head(top_n)["stock_code"].tolist()))
    save_order_log(schedule["next_exec"], sell_orders, buy_orders, new_holdings)
    save_state({
        "last_executed_rebal": schedule["next_rebal"],
        "current_holdings":    new_holdings,
        "run_name":            run_name,
        "last_updated":        datetime.now().isoformat(),
    })

    print("\n  Done.")


if __name__ == "__main__":
    main()
