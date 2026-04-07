#!/usr/bin/env python3
"""Unified backtest runner (single model, single feature pipeline)."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.backtest import (
    BENCHMARK_INDEX_MAP,
    load_benchmark_returns as _load_benchmark_returns,
    compute_core_stats as _compute_core_stats,
    compute_stat_significance as _compute_stat_significance,
    compute_performance as _compute_performance,
    parse_exclude_years as _parse_exclude_years,
    format_sector_names as _format_sector_names,
    print_table as _print_table,
    print_requested_tests as _print_requested_tests,
    generate_summary as summarize,
    generate_visual_report as _generate_visual_report,
    generate_picks_chart as _generate_picks_chart,
)

compute_core_stats = _compute_core_stats
compute_stat_significance = _compute_stat_significance
compute_performance = _compute_performance
parse_exclude_years = _parse_exclude_years
load_benchmark_returns = _load_benchmark_returns


def _run_fold(payload: dict) -> dict:
    """Run one walk-forward fold in a worker process."""
    from ml.models import get_model_class

    train_df: pd.DataFrame = payload["train_df"]
    test_df: pd.DataFrame = payload["test_df"]
    info: dict = payload["info"]
    feature_cols: list[str] = payload["feature_cols"]
    target_col: str = payload["target_col"]
    fwd_col: str = payload["fwd_col"]
    eval_fwd_col: str = payload.get("eval_fwd_col", fwd_col)
    min_daily_value: int = payload.get("min_daily_value", 0)
    portfolio_size: int = payload.get("portfolio_size", 100_000_000)
    top_n: int = payload["top_n"]
    rebalance_days: int = payload["rebalance_days"]
    time_decay: float = payload["time_decay"]
    model_jobs: int = payload["model_jobs"]
    buy_fee_rate: float = payload["buy_fee_rate"]
    sell_fee_rate: float = payload["sell_fee_rate"]
    learning_rate: float = payload["learning_rate"]
    n_estimators: int = payload["n_estimators"]
    patience: int = payload["patience"]
    min_market_cap: int = payload["min_market_cap"]
    max_market_cap: int | None = payload.get("max_market_cap")
    stress_mode: bool = payload["stress_mode"]
    vol_exclude_pct: float = payload["vol_exclude_pct"]
    sector_neutral_score: bool = payload["sector_neutral_score"]
    buy_rank: int = payload["buy_rank"]
    hold_rank: int = payload["hold_rank"]
    embargo_days: int = payload["embargo_days"]
    cash_out_enabled: bool = payload.get("cash_out", False)
    weighting: str = payload.get("weighting", "equal")
    bench_returns_by_date: dict = payload.get("bench_returns_by_date", {})
    model_class_name: str = payload.get("model_class", "lgbm")
    run_turnover_test: bool = payload.get("run_turnover_test", True)
    turnover_test_hold_rank: int = payload.get("turnover_test_hold_rank", hold_rank)
    turnover_test_smoothing_alpha: float = payload.get("turnover_test_smoothing_alpha", 1.0)
    stop_loss_pct: float = payload.get("stop_loss_pct", 0.0)
    print(
        f"[Fold {info['test_year']}] start "
        f"(train={info['train_period']}, train_rows={len(train_df):,}, test_rows={len(test_df):,})",
        flush=True,
    )

    train_years = sorted(train_df["date"].str[:4].unique())
    val_year = train_years[-1]
    sub_train = train_df[train_df["date"].str[:4] != val_year]
    val_df = train_df[train_df["date"].str[:4] == val_year]
    if sub_train.empty:
        sub_train, val_df = train_df, None
    # Purged training: enforce embargo gap before test period.
    all_dates = sorted(pd.concat([train_df["date"], test_df["date"]]).unique())
    test_start = min(test_df["date"])
    if test_start in all_dates:
        idx = all_dates.index(test_start)
        if idx > embargo_days:
            cutoff = all_dates[idx - embargo_days]
            sub_train = sub_train[sub_train["date"] < cutoff].copy()
            if val_df is not None:
                val_df = val_df[val_df["date"] < cutoff].copy()
    if sub_train.empty:
        if val_df is not None and not val_df.empty:
            print(
                f"[Fold {info['test_year']}] WARNING: sub_train empty after embargo; "
                f"using val_df as sole training set (no early-stopping).",
                flush=True,
            )
            sub_train = val_df.copy()
            val_df = None
        else:
            print(
                f"[Fold {info['test_year']}] ERROR: no training data after embargo; skipping fold.",
                flush=True,
            )
            return {
                "test_year": info["test_year"],
                "rows": [],
                "sector_rows": [],
                "pick_rows": [],
                "final_holdings": [],
                "final_holdings_tuned": [],
                "final_scores_tuned": {},
            }

    ModelClass = get_model_class(model_class_name)
    model = ModelClass(feature_cols=feature_cols, target_col=target_col, time_decay=time_decay)
    params = model.BEST_PARAMS.copy()
    params["n_jobs"] = model_jobs
    params["learning_rate"] = learning_rate
    params["n_estimators"] = n_estimators
    model.patience = patience
    model.train(sub_train, val_df, params=params)

    # ── IC diagnostics: train IC vs val IC (overfitting check) ──────────────
    from scipy.stats import spearmanr as _spearmanr
    def _ic(df, fc=fwd_col):
        d = df[[fc, "score"]].dropna() if "score" in df.columns else pd.DataFrame()
        if len(d) < 30:
            return float("nan")
        return _spearmanr(d["score"], d[fc]).statistic

    train_probe = sub_train.copy()
    train_probe["score"] = model.predict(train_probe)
    train_ic = _ic(train_probe)

    if val_df is not None and len(val_df) > 100 and fwd_col in val_df.columns:
        val_probe = val_df.copy()
        val_probe["score"] = model.predict(val_probe)
        val_ic = _ic(val_probe)
        score_rank_probe = val_probe["score"].rank(method="first", pct=True)
        val_probe["quintile"] = np.ceil(score_rank_probe * 5).clip(1, 5).astype(int)
        qv = val_probe.groupby("quintile")[fwd_col].mean()
        mono_ok = False
        if all(q in qv.index for q in [1, 2, 3, 4, 5]):
            mono_ok = bool(qv.loc[5] > qv.loc[4] > qv.loc[3] > qv.loc[2] > qv.loc[1])
        if not mono_ok:
            # Per-fold val quintile ordering is noisy (6 rebalances, ~1yr window).
            # Treat as informational only — the aggregate OOS quintile table is authoritative.
            print(f"[Fold {info['test_year']}] quintiles not monotonic (val set noise — see aggregate OOS table)", flush=True)
        print(
            f"[Fold {info['test_year']}] IC  train={train_ic:.4f}  val={val_ic:.4f}  "
            f"ratio={val_ic/train_ic:.2f}  {'⚠ OVERFIT' if train_ic > 0 and val_ic / train_ic < 0.5 else 'OK'}",
            flush=True,
        )
    else:
        print(f"[Fold {info['test_year']}] IC  train={train_ic:.4f}  val=N/A", flush=True)
    print(f"[Fold {info['test_year']}] model trained", flush=True)

    rows = []
    sector_rows = []
    pick_rows = []
    date_groups = {d: g.copy() for d, g in test_df.groupby("date", sort=True)}
    rebalance_dates = sorted(date_groups.keys())[::rebalance_days]
    prev_holdings: set[str] = set(payload.get("prev_holdings", []))
    prev_holdings_tuned: set[str] = set(payload.get("prev_holdings_tuned", []))
    prev_scores_tuned: dict[str, float] = dict(payload.get("prev_scores_tuned", {}))

    def _build_picks(
        frame: pd.DataFrame,
        rank_col: str,
        rank_pos_col: str,
        previous_holdings: set[str],
        hold_rank_limit: int,
        effective_top_n: int,
    ) -> tuple[pd.DataFrame, set[str], float, float]:
        keep_pool = frame[
            (frame["stock_code"].isin(previous_holdings)) & (frame[rank_pos_col] <= hold_rank_limit)
        ].copy().sort_values(rank_col, ascending=False)
        already_in = set(keep_pool["stock_code"])
        buy_candidates = frame[
            (~frame["stock_code"].isin(already_in)) & (frame[rank_pos_col] <= buy_rank)
        ].copy().sort_values(rank_col, ascending=False)

        # True hysteresis: kept stocks are protected — only fill empty slots with new candidates.
        # A new candidate only displaces a kept stock if it scores higher by > transaction cost edge.
        score_edge = buy_fee_rate + sell_fee_rate
        protected = keep_pool.copy()
        new_entries = []
        for _, candidate in buy_candidates.iterrows():
            if len(protected) + len(new_entries) >= effective_top_n:
                break
            new_entries.append(candidate)

        # If keep_pool exceeds top_n, drop weakest kept stocks
        if len(protected) > effective_top_n:
            protected = protected.head(effective_top_n)

        picks = pd.concat([protected, pd.DataFrame(new_entries)], ignore_index=True)
        picks = picks.sort_values(rank_col, ascending=False).drop_duplicates("stock_code")

        # Fill any remaining slots if still short
        if len(picks) < effective_top_n:
            fill_pool = frame[
                (~frame["stock_code"].isin(set(picks["stock_code"])))
                & (frame[rank_pos_col] <= hold_rank_limit)
            ].copy().sort_values(rank_col, ascending=False)
            picks = pd.concat([picks, fill_pool.head(effective_top_n - len(picks))], ignore_index=True)

        picks = picks.sort_values(rank_col, ascending=False).drop_duplicates("stock_code")
        picks = picks.head(effective_top_n).copy()
        current_holdings = set(picks["stock_code"].tolist())
        if not previous_holdings:
            turnover = 1.0
            transaction_cost = buy_fee_rate
        else:
            overlap = len(previous_holdings & current_holdings)
            turnover = 1.0 - (overlap / max(effective_top_n, 1))
            transaction_cost = turnover * (buy_fee_rate + sell_fee_rate)
        return picks, current_holdings, turnover, transaction_cost

    for d in rebalance_dates:
        day_df = date_groups[d].copy()
        # PIT universe on rebalance date
        day_df = day_df[day_df["market_cap"] >= min_market_cap].copy()
        if max_market_cap:
            day_df = day_df[day_df["market_cap"] <= max_market_cap].copy()
        # Exclude suspended stocks (trading halted): zero daily trading value means
        # the stock is halted and cannot be traded at this rebalance date.
        if "value" in day_df.columns:
            day_df = day_df[day_df["value"] > 0].copy()
        # Liquidity filter: exclude stocks whose daily trading value is below threshold.
        # Prevents allocating to illiquid names that cannot be filled in practice.
        if min_daily_value > 0 and "value" in day_df.columns:
            day_df = day_df[day_df["value"] >= min_daily_value].copy()
        if stress_mode and 0 < vol_exclude_pct < 1 and "volatility_21d" in day_df.columns and len(day_df) > 10:
            vol_cut = day_df["volatility_21d"].quantile(1.0 - vol_exclude_pct)
            day_df = day_df[day_df["volatility_21d"] <= vol_cut].copy()
        if len(day_df) < top_n:
            continue
        # Cash-out: two-layer risk-off switch
        # Layer 1 (existing): KOSPI200 below 20-day MA → halve positions
        # Layer 2 (new):      VKOSPI fear index in top 20% → additional 50% cash
        effective_top_n = top_n
        cash_weight = 0.0
        if cash_out_enabled:
            # Layer 1: trend filter (KOSPI200 below 20d MA)
            if "market_regime_20d" in day_df.columns:
                regime_val = day_df["market_regime_20d"].iloc[0]
                if pd.notna(regime_val) and regime_val < 0:
                    effective_top_n = max(top_n // 2, 5)
                    cash_weight = 1.0 - (effective_top_n / top_n)
            # Layer 2: fear filter (VKOSPI in top-20% of 1-year distribution)
            # vkospi_level_pct is a 252d rolling percentile: >0.8 = extreme fear
            if "vkospi_level_pct" in day_df.columns:
                vkos_val = day_df["vkospi_level_pct"].iloc[0]
                if pd.notna(vkos_val) and vkos_val > 0.8:
                    # Additional 50% into cash on top of Layer 1
                    cash_weight = min(cash_weight + 0.5, 1.0)
                    effective_top_n = max(int(top_n * (1.0 - cash_weight)), 5)
        day_df["score"] = model.predict(day_df)
        if sector_neutral_score and "sector" in day_df.columns:
            sec_mean = day_df.groupby("sector")["score"].transform("mean")
            sec_std = day_df.groupby("sector")["score"].transform("std").replace(0, np.nan)
            day_df["score_rank"] = ((day_df["score"] - sec_mean) / sec_std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        else:
            day_df["score_rank"] = day_df["score"]
        day_df["rank_pos"] = day_df["score_rank"].rank(ascending=False, method="first")
        score_rank = day_df["score_rank"].rank(method="first", pct=True)
        day_df["quintile"] = np.ceil(score_rank * 5).clip(1, 5).astype(int)
        # Use eval_fwd_col (the actually-traded return) for all signal-quality metrics.
        # When exec_lag > 0, this is open[T+lag]/open[T+H+lag] rather than close[T]/close[T+H].
        _ret_col = eval_fwd_col if eval_fwd_col in day_df.columns else fwd_col
        qret = day_df.groupby("quintile")[_ret_col].mean()
        q1 = float(qret.get(1, np.nan))
        q2 = float(qret.get(2, np.nan))
        q3 = float(qret.get(3, np.nan))
        q4 = float(qret.get(4, np.nan))
        q5 = float(qret.get(5, np.nan))
        q_mono = int(q5 > q4 > q3 > q2 > q1) if np.all(pd.notna([q1, q2, q3, q4, q5])) else 0
        ic = day_df[["score_rank", _ret_col]].corr(method="spearman").iloc[0, 1]
        ic = float(ic) if pd.notna(ic) else np.nan
        decile_n = max(int(len(day_df) * 0.10), 1)
        top_decile_return = float(day_df.nlargest(decile_n, "score_rank")[_ret_col].mean())
        bottom_decile_return = float(day_df.nsmallest(decile_n, "score_rank")[_ret_col].mean())
        long_short_return = top_decile_return - bottom_decile_return

        picks, current_holdings, turnover, transaction_cost = _build_picks(
            frame=day_df,
            rank_col="score_rank",
            rank_pos_col="rank_pos",
            previous_holdings=prev_holdings,
            hold_rank_limit=hold_rank,
            effective_top_n=effective_top_n,
        )
        if picks.empty:
            continue

        _ret_col_pick = eval_fwd_col if eval_fwd_col in picks.columns else fwd_col
        sl_triggered_rate = float(picks["_sl_triggered"].mean()) if stop_loss_pct > 0 and "_sl_triggered" in picks.columns else 0.0
        if portfolio_size > 0 and "closing_price" in picks.columns:
            investable = portfolio_size * (1.0 - cash_weight)
            _prices = picks["closing_price"].clip(lower=1.0)
            if weighting == "signal" and "score_rank" in picks.columns and picks["score_rank"].sum() > 0:
                _sw = picks["score_rank"] / picks["score_rank"].sum()
                _shares = np.floor((_sw * investable) / _prices)
            elif weighting == "signal_vol" and "score_rank" in picks.columns and "volatility_21d" in picks.columns:
                _vol = picks["volatility_21d"].replace(0, np.nan).fillna(picks["volatility_21d"].median()).clip(lower=1e-6)
                _raw = picks["score_rank"] / _vol
                _sw = _raw / _raw.sum()
                _shares = np.floor((_sw * investable) / _prices)
            else:
                # equal-weight (default)
                _shares = np.floor((investable / max(len(picks), 1)) / _prices)
            _invested = _shares * _prices
            _total_invested = float(_invested.sum())
            cash_drag_pct = 1.0 - _total_invested / portfolio_size
            if _total_invested > 0:
                _w = _invested / _total_invested
                stock_ret = float((_w * picks[_ret_col_pick].fillna(0.0)).sum())
            else:
                stock_ret = 0.0
            port_ret = stock_ret * (_total_invested / portfolio_size)
            # Attach shares info to picks for CSV export
            picks = picks.copy()
            picks["shares"] = _shares.values
            picks["invested_krw"] = _invested.values
        else:
            stock_ret = float(picks[_ret_col_pick].mean())
            port_ret = stock_ret * (1.0 - cash_weight)
            cash_drag_pct = cash_weight
        if bench_returns_by_date and d in bench_returns_by_date and pd.notna(bench_returns_by_date[d]):
            bench_ret = float(bench_returns_by_date[d])
        else:
            bench_ret = float(day_df[eval_fwd_col].mean()) if eval_fwd_col in day_df.columns else float(day_df[fwd_col].mean())
        net_port_ret = (1.0 + port_ret) * (1.0 - transaction_cost) - 1.0
        prev_holdings = current_holdings

        # Turnover reduction test: relaxed hold threshold + score smoothing.
        net_port_ret_tuned = np.nan
        turnover_tuned = np.nan
        transaction_cost_tuned = np.nan
        if run_turnover_test:
            if 0.0 < turnover_test_smoothing_alpha < 1.0:
                prev_smoothed = day_df["stock_code"].map(prev_scores_tuned)
                day_df["score_tuned"] = day_df["score"]
                valid_prev = prev_smoothed.notna()
                day_df.loc[valid_prev, "score_tuned"] = (
                    turnover_test_smoothing_alpha * day_df.loc[valid_prev, "score"]
                    + (1.0 - turnover_test_smoothing_alpha) * prev_smoothed.loc[valid_prev].astype(float)
                )
            else:
                day_df["score_tuned"] = day_df["score"]

            prev_scores_tuned.update(
                {str(c): float(v) for c, v in zip(day_df["stock_code"], day_df["score_tuned"])}
            )

            if sector_neutral_score and "sector" in day_df.columns:
                sec_mean_t = day_df.groupby("sector")["score_tuned"].transform("mean")
                sec_std_t = day_df.groupby("sector")["score_tuned"].transform("std").replace(0, np.nan)
                day_df["score_rank_tuned"] = (
                    (day_df["score_tuned"] - sec_mean_t) / sec_std_t
                ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            else:
                day_df["score_rank_tuned"] = day_df["score_tuned"]

            day_df["rank_pos_tuned"] = day_df["score_rank_tuned"].rank(ascending=False, method="first")
            picks_tuned, current_holdings_tuned, turnover_tuned, transaction_cost_tuned = _build_picks(
                frame=day_df,
                rank_col="score_rank_tuned",
                rank_pos_col="rank_pos_tuned",
                previous_holdings=prev_holdings_tuned,
                hold_rank_limit=turnover_test_hold_rank,
                effective_top_n=effective_top_n,
            )
            if not picks_tuned.empty:
                _ret_col_tuned = eval_fwd_col if eval_fwd_col in picks_tuned.columns else fwd_col
                if portfolio_size > 0 and "closing_price" in picks_tuned.columns:
                    investable_t = portfolio_size * (1.0 - cash_weight)
                    per_stock_t = investable_t / max(len(picks_tuned), 1)
                    _prices_t = picks_tuned["closing_price"].clip(lower=1.0)
                    _invested_t = np.floor(per_stock_t / _prices_t) * _prices_t
                    _total_t = float(_invested_t.sum())
                    if _total_t > 0:
                        _w_t = _invested_t / _total_t
                        stock_ret_tuned = float((_w_t * picks_tuned[_ret_col_tuned].fillna(0.0)).sum())
                    else:
                        stock_ret_tuned = 0.0
                    port_ret_tuned = stock_ret_tuned * (_total_t / portfolio_size)
                else:
                    stock_ret_tuned = float(picks_tuned[_ret_col_tuned].mean())
                    port_ret_tuned = stock_ret_tuned * (1.0 - cash_weight)
                net_port_ret_tuned = (1.0 + port_ret_tuned) * (1.0 - transaction_cost_tuned) - 1.0
                prev_holdings_tuned = current_holdings_tuned

        _attr_col = eval_fwd_col if eval_fwd_col in picks.columns else fwd_col
        sec = (
            picks.groupby("sector", as_index=False)
            .agg(
                n=("stock_code", "count"),
                sector_forward_return=(_attr_col, "mean"),
            )
            .sort_values("n", ascending=False)
        )
        sec["weight"] = sec["n"] / max(effective_top_n, 1)
        sec["contribution"] = sec["weight"] * sec["sector_forward_return"]
        top_sector = str(sec.iloc[0]["sector"]) if len(sec) > 0 else "N/A"
        top_sector_weight = float(sec.iloc[0]["weight"]) if len(sec) > 0 else 0.0
        sector_hhi = float((sec["weight"] ** 2).sum()) if len(sec) > 0 else np.nan
        for _, srow in sec.iterrows():
            sector_rows.append(
                {
                    "date": d,
                    "test_year": info["test_year"],
                    "sector": srow["sector"],
                    "weight": float(srow["weight"]),
                    "sector_forward_return": float(srow["sector_forward_return"]),
                    "contribution": float(srow["contribution"]),
                }
            )

        # Collect per-pick details for optional CSV export
        pick_detail_cols = ["stock_code", "name", "sector", "closing_price", "shares", "invested_krw",
                            "buy_price", "sell_price", "sell_date", "market_cap", "score", "score_rank", "rank_pos", eval_fwd_col]
        pick_detail_cols = [c for c in pick_detail_cols if c in picks.columns]
        for _, prow in picks.iterrows():
            pick_rows.append({
                "date": d,
                "test_year": info["test_year"],
                **{c: prow[c] for c in pick_detail_cols},
            })

        rows.append(
            {
                "date": d,
                "year": int(d[:4]),
                "portfolio_return": net_port_ret,
                "portfolio_return_gross": port_ret,
                "benchmark_return": bench_ret,
                "alpha": net_port_ret - bench_ret,
                "transaction_cost": transaction_cost,
                "turnover": turnover,
                "cash_drag_pct": cash_drag_pct,
                "sl_triggered_rate": sl_triggered_rate,
                "ic_spearman": ic,
                "q1_ret": q1,
                "q2_ret": q2,
                "q3_ret": q3,
                "q4_ret": q4,
                "q5_ret": q5,
                "q_monotonic": q_mono,
                "top_decile_return": top_decile_return,
                "bottom_decile_return": bottom_decile_return,
                "long_short_return": long_short_return,
                "portfolio_return_tuned": net_port_ret_tuned,
                "turnover_tuned": turnover_tuned,
                "transaction_cost_tuned": transaction_cost_tuned,
                "top_sector": top_sector,
                "top_sector_weight": top_sector_weight,
                "sector_hhi": sector_hhi,
                "top_picks": " | ".join(
                    (
                        f"{row['stock_code']}({str(row.get('name', ''))[:10]}):{row[eval_fwd_col]:+.1%}"
                        if eval_fwd_col in picks.columns and pd.notna(row.get(eval_fwd_col))
                        else f"{row['stock_code']}({str(row.get('name', ''))[:10]})"
                    )
                    for _, row in picks.head(10).iterrows()
                ),
                "train_period": info["train_period"],
                "test_year": info["test_year"],
            }
        )

    print(
        f"[Fold {info['test_year']}] done "
        f"(rebalance_points={len(rebalance_dates)}, result_rows={len(rows)})",
        flush=True,
    )
    _fi = None
    if hasattr(model, "feature_importance"):
        try:
            _fi_df = model.feature_importance()
            _fi = dict(zip(_fi_df["feature"], _fi_df["importance"]))
        except Exception:
            pass

    return {
        "test_year": info["test_year"],
        "rows": rows,
        "sector_rows": sector_rows,
        "pick_rows": pick_rows,
        "final_holdings": list(prev_holdings),
        "final_holdings_tuned": list(prev_holdings_tuned),
        "final_scores_tuned": prev_scores_tuned,
        "feature_importance": _fi,
    }


def run(args: argparse.Namespace) -> None:
    from ml.features import FeatureEngineer
    from ml.model import walk_forward_split
    from ml.models import get_model_class

    effective_buy_fee = args.buy_fee
    effective_sell_fee = args.sell_fee
    if getattr(args, "no_sector_neutral", False):
        args.sector_neutral_score = False
    if getattr(args, "no_cash_out", False):
        args.cash_out = False
    effective_sector_neutral = args.sector_neutral_score or args.stress_mode
    if args.stress_mode:
        effective_buy_fee = 1.0
        effective_sell_fee = 1.0

    if args.horizon <= 0:
        raise ValueError("--horizon must be >= 1")

    exec_lag = int(getattr(args, "exec_lag", 1))
    if exec_lag < 0:
        raise ValueError("--exec-lag must be >= 0")
    args.exec_lag = exec_lag

    exec_price = str(getattr(args, "exec_price", "open")).lower()
    if exec_price not in {"open", "close"}:
        raise ValueError("--exec-price must be one of: open, close")
    args.exec_price = exec_price

    # Purge embargo must cover the full label horizon and execution lag.
    required_embargo = args.horizon + exec_lag
    if args.embargo_days < required_embargo:
        print(
            f"[Backtest] embargo auto-calc: {args.embargo_days}d -> {required_embargo}d "
            f"(>= horizon {args.horizon}d + exec_lag {exec_lag}d)",
            flush=True,
        )
        args.embargo_days = required_embargo

    if args.end is None:
        import sqlite3 as _sqlite3
        with _sqlite3.connect(args.db) as _conn:
            args.end = _conn.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0]
    print(f"[Backtest] loading data {args.start}~{args.end} ...", flush=True)
    fe = FeatureEngineer(args.db)
    df = fe.prepare_ml_data(
        start_date=args.start,
        end_date=args.end,
        target_horizon=args.horizon,
        min_market_cap=args.min_market_cap,
        max_market_cap=getattr(args, "max_market_cap", None),
        use_cache=not args.no_cache,
        n_workers=args.workers,
    )

    if df.empty:
        print("No ML data available for the requested range.")
        return
    exclude_years = _parse_exclude_years(args.exclude_years)
    if exclude_years:
        before_rows = len(df)
        df = df[~df["date"].str[:4].isin(exclude_years)].copy()
        print(
            f"[Backtest] excluded years={sorted(exclude_years)} "
            f"(rows {before_rows:,} -> {len(df):,})",
            flush=True,
        )
        if df.empty:
            print("No rows left after applying --exclude-years filter.")
            return
    if args.stress_mode and 0 < args.vol_exclude_pct < 1 and "volatility_21d" in df.columns:
        vol_cut = df.groupby("date")["volatility_21d"].transform(
            lambda s: s.quantile(1.0 - args.vol_exclude_pct)
        )
        df = df[df["volatility_21d"] <= vol_cut].copy()
    print(f"[Backtest] feature rows={len(df):,}, cols={len(df.columns)}", flush=True)

    feature_cols = [c for c in FeatureEngineer.FEATURE_COLUMNS if c in df.columns]
    fwd_col = f"forward_return_{args.horizon}d"

    # ── Test 1: Execution Lag ─────────────────────────────────────────────
    # Trade after signal with explicit execution lag and price basis.
    # Model is still trained on spot fwd_col; only portfolio evaluation uses lag.
    eval_fwd_col = fwd_col
    # Prefer adjusted prices so splits within the holding period don't distort returns.
    # Fall back to raw prices if adj_daily_prices table hasn't been built yet.
    if exec_price == "open":
        if "adj_opening_price" in df.columns:
            trade_price_col = "adj_opening_price"
        elif "opening_price" in df.columns:
            print("[Backtest] WARNING: adj_opening_price missing, falling back to raw opening_price.", flush=True)
            trade_price_col = "opening_price"
        elif "closing_price" in df.columns:
            print("[Backtest] WARNING: opening_price missing, falling back to closing_price execution.", flush=True)
            exec_price = "close"
            trade_price_col = "closing_price"
        else:
            raise ValueError("No execution price column found.")
    else:
        trade_price_col = "adj_closing_price" if "adj_closing_price" in df.columns else "closing_price"
    if trade_price_col not in df.columns:
        raise ValueError(f"Required execution price column not found: {trade_price_col}")

    if exec_lag > 0:
        lag_col = f"forward_return_{args.horizon}d_lag{exec_lag}_{exec_price}"
        _df_sorted = df.sort_values(["stock_code", "date"]).copy()
        # Replace 0 prices with NaN: opening_price=0 occurs on circuit-breaker / upper-lock
        # days in KRX data. Dividing by zero would produce inf returns silently.
        _df_sorted[trade_price_col] = _df_sorted[trade_price_col].replace(0, float("nan"))
        _grp = _df_sorted.groupby("stock_code")[trade_price_col]
        _entry_px = _grp.shift(-exec_lag)
        _exit_px = _grp.shift(-(args.horizon + exec_lag))
        _df_sorted[lag_col] = _exit_px / _entry_px - 1
        # Tail fallback: when exit price is unavailable (NaN), fall back to the
        # pipeline's adj-closing forward return which is pre-computed on the
        # UNFILTERED per-stock series and is immune to universe-filter row gaps.
        # The old mark-to-last (_last_px / _entry_px - 1) could produce extreme
        # returns (e.g. 191%) when hard filters like bad_accrual create mid-series
        # gaps and _last_px is a distant peak price from a later year.
        _base_fwd_col = f"forward_return_{args.horizon}d"
        if _base_fwd_col in _df_sorted.columns:
            # Use pre-computed forward_return whenever lag_col is NaN and base is valid.
            # _entry_px.gt(0) check is intentionally removed: when a stock is the only
            # row in its group after universe filters, shift(-1) returns NaN (not 0),
            # causing gt(0) to be False and silently skipping the fallback.
            _nan_mask = _df_sorted[lag_col].isna() & _df_sorted[_base_fwd_col].notna()
            _df_sorted.loc[_nan_mask, lag_col] = _df_sorted.loc[_nan_mask, _base_fwd_col]
        else:
            _last_px = _df_sorted.groupby("stock_code")[trade_price_col].transform("last")
            _df_sorted.loc[_nan_mask, lag_col] = _last_px[_nan_mask] / _entry_px[_nan_mask] - 1
        df = _df_sorted
        eval_fwd_col = lag_col
        print(
            f"[Backtest] exec_lag={exec_lag}d — execution: T+{exec_lag} {exec_price} ({lag_col})",
            flush=True,
        )

    # ── TWAP Execution Mode ───────────────────────────────────────────────
    # Simulates spreading execution over N trading days at each rebalance.
    #
    # Bias-free design:
    #   • Model is trained on spot fwd_col (signal quality is separate from execution)
    #   • entry_avg  = equal-weight mean of close[T+1 .. T+N]   (buy leg)
    #   • exit_avg   = equal-weight mean of close[T+H-N+1 .. T+H] (sell leg)
    #   • Suspended days (value==0) are excluded from each average
    #   • N is capped at H//3 so entry and exit windows never overlap
    #   • NaN (data tail / full suspension) → last observed price fallback
    #
    # This overrides exec_lag if both flags are set (TWAP already implies T+1 start).
    twap_days = getattr(args, "twap_days", 0)
    if twap_days > 0 and "closing_price" in df.columns:
        H = args.horizon
        max_twap = H // 3  # entry [T+1..T+N] and exit [T+H-N+1..T+H] must not overlap
        if twap_days > max_twap:
            print(f"[Backtest] Warning: --twap-days={twap_days} > horizon//3={max_twap}. Capped.", flush=True)
            twap_days = max_twap

        twap_col = f"forward_return_{H}d_twap{twap_days}"
        _df_tw = df.sort_values(["stock_code", "date"]).copy()
        has_value = "value" in _df_tw.columns

        # ── Entry window: average close over days T+1 .. T+twap_days ──────
        _entry_list = []
        for k in range(1, twap_days + 1):
            px = _df_tw.groupby("stock_code")["closing_price"].shift(-k)
            if has_value:
                vl = _df_tw.groupby("stock_code")["value"].shift(-k)
                px = px.where(vl > 0)   # exclude suspended days from average
            _entry_list.append(px)
        entry_avg = pd.concat(_entry_list, axis=1).mean(axis=1, skipna=True)

        # ── Exit window: average close over days T+H-twap_days+1 .. T+H ──
        _exit_list = []
        for k in range(H - twap_days + 1, H + 1):
            px = _df_tw.groupby("stock_code")["closing_price"].shift(-k)
            if has_value:
                vl = _df_tw.groupby("stock_code")["value"].shift(-k)
                px = px.where(vl > 0)   # exclude suspended days from average
            _exit_list.append(px)
        exit_avg = pd.concat(_exit_list, axis=1).mean(axis=1, skipna=True)

        _df_tw[twap_col] = exit_avg / entry_avg - 1

        # Fix NaN: data tail or fully suspended window → last observed price
        _last_px = _df_tw.groupby("stock_code")["closing_price"].transform("last")
        _nan_mask = _df_tw[twap_col].isna() & _df_tw["closing_price"].gt(0)
        _df_tw.loc[_nan_mask, twap_col] = (
            _last_px[_nan_mask] / _df_tw.loc[_nan_mask, "closing_price"] - 1
        )

        # Store exact entry/exit prices for picks.csv
        _df_tw["buy_price"] = entry_avg.round(0)
        _df_tw["sell_price"] = exit_avg.round(0)

        df = _df_tw
        eval_fwd_col = twap_col   # overrides exec_lag if both set
        print(
            f"[Backtest] twap_days={twap_days}: "
            f"entry=avg(close T+1~T+{twap_days}), "
            f"exit=avg(close T+{H - twap_days + 1}~T+{H}), "
            f"suspended days excluded  [{twap_col}]",
            flush=True,
        )
    else:
        # Non-TWAP execution prices for picks.csv
        _df_base = df.sort_values(["stock_code", "date"]).copy()
        _grp_px_close = _df_base.groupby("stock_code")["closing_price"]
        _grp_px_exec = _df_base.groupby("stock_code")[trade_price_col]
        _grp_date = _df_base.groupby("stock_code")["date"]
        if exec_lag > 0:
            _df_base["buy_price"] = _grp_px_exec.shift(-exec_lag).round(0)
            _df_base["sell_price"] = _grp_px_exec.shift(-(args.horizon + exec_lag)).round(0)
            _df_base["sell_date"] = _grp_date.shift(-(args.horizon + exec_lag))
        else:
            _df_base["buy_price"] = _df_base["closing_price"].round(0)
            _df_base["sell_price"] = _grp_px_close.shift(-args.horizon).round(0)
            _df_base["sell_date"] = _grp_date.shift(-args.horizon)
        df = _df_base

    # ── Stop-Loss Pre-computation ─────────────────────────────────────────
    # For each stock on date T, find the minimum intraperiod close price in the
    # holding window [T+exec_lag+1 .. T+exec_lag+horizon].  If that minimum is
    # more than stop_loss_pct below the entry price (close[T+exec_lag]), the
    # position is assumed to have been exited at the stop level.
    # Result: eval_fwd_col returns are capped at -stop_loss_pct for those rows.
    # Only supported when exec_lag >= 1 (entry price is unambiguous).
    stop_loss_pct: float = getattr(args, "stop_loss", 0.0)
    if stop_loss_pct > 0 and exec_lag >= 1 and twap_days == 0:
        print(
            f"[Backtest] stop_loss={stop_loss_pct:.0%} — "
            f"pre-computing intraperiod minimums over {args.horizon} days ...",
            flush=True,
        )
        _df_sl = df.sort_values(["stock_code", "date"]).copy()
        _grp_sl = _df_sl.groupby("stock_code")[trade_price_col]
        _entry_px_sl = _grp_sl.shift(-exec_lag).replace(0, float("nan"))
        # Build list of prices at each day inside the holding window
        _min_prices = []
        for _k in range(exec_lag + 1, exec_lag + args.horizon + 1):
            _min_prices.append(_grp_sl.shift(-_k))
        _intraperiod_min = pd.concat(_min_prices, axis=1).min(axis=1, skipna=True)
        _min_return = _intraperiod_min / _entry_px_sl - 1
        _sl_triggered = (_min_return < -stop_loss_pct) & _entry_px_sl.notna()
        sl_col = f"{eval_fwd_col}_sl{int(stop_loss_pct * 100)}"
        _df_sl[sl_col] = np.where(_sl_triggered, -stop_loss_pct, _df_sl[eval_fwd_col])
        _df_sl["_sl_triggered"] = _sl_triggered.astype(float)
        df = _df_sl
        eval_fwd_col = sl_col
        _valid = _entry_px_sl.notna().sum()
        _hit = int(_sl_triggered.sum())
        print(
            f"[Backtest] stop_loss applied: {_hit:,}/{_valid:,} rows triggered "
            f"({_hit / max(_valid, 1):.1%})",
            flush=True,
        )
    elif stop_loss_pct > 0:
        print("[Backtest] WARNING: --stop-loss requires --exec-lag >= 1 and no --twap-days. Skipped.", flush=True)
        stop_loss_pct = 0.0

    # ── Test 4: Feature Permutation ───────────────────────────────────────
    # Shuffle one or all feature columns across ALL rows (stocks × dates).
    # This completely destroys both temporal and cross-sectional signal in that feature.
    #
    # Interpretation:
    #   If IC / Sharpe drops significantly after permutation → feature has real signal.
    #   If IC / Sharpe is maintained after permuting ALL features → look-ahead leakage.
    #
    # Bias-free design:
    #   • Permutation is applied BEFORE walk-forward splits (same shuffled data seen in
    #     all folds → consistent apples-to-apples comparison within this run).
    #   • random_state is fixed for reproducibility.
    #   • Model is retrained on the permuted dataset (full walk-forward preserved).
    #   • eval_fwd_col (portfolio returns) is NOT shuffled — only features are.
    permute_feature = getattr(args, "permute_feature", "")
    if permute_feature:
        rng = np.random.default_rng(seed=42)
        if permute_feature.lower() == "all":
            targets = [c for c in feature_cols if c in df.columns]
        else:
            targets = [f for f in permute_feature.split(",") if f.strip() in df.columns]
            unknown = [f for f in permute_feature.split(",") if f.strip() not in df.columns]
            if unknown:
                print(f"[Permutation] WARNING: unknown feature(s) skipped: {unknown}", flush=True)
        for feat in targets:
            df[feat] = rng.permutation(df[feat].values)
        print(
            f"[Permutation] Test 4: shuffled {len(targets)} feature(s) → "
            f"{targets if len(targets) <= 5 else str(targets[:5]) + '...'}\n"
            f"  Expected: IC ≈ 0, Sharpe ≈ 0 if these features drive signal (no leakage).",
            flush=True,
        )

    residual_rank_col = f"target_residual_rank_{args.horizon}d"
    rank_label_col = f"target_rank_label_{args.horizon}d"
    if getattr(args, "composite_target", False) and "target_composite_residual_rank" in df.columns:
        base_col = "target_composite_residual_rank"
    elif residual_rank_col in df.columns:
        base_col = residual_rank_col
    else:
        base_col = f"target_rank_{args.horizon}d"

    # Ranking objectives (lambdarank) require integer labels [0-4].
    # Regression objectives (huber, rmse, etc.) use the continuous rank [0,1] directly.
    _model_objective = get_model_class(args.model).BEST_PARAMS.get("objective", "")
    _is_ranking = _model_objective in ("lambdarank", "rank_xendcg")
    if _is_ranking and base_col in df.columns:
        df[rank_label_col] = np.clip((df[base_col] * 5).astype(int), 0, 4)
        target_col = rank_label_col
    else:
        target_col = base_col  # continuous residual rank [0,1]

    # Load benchmark index returns
    _bench_label = getattr(args, "benchmark", "kospi200")
    _bench_index_code = BENCHMARK_INDEX_MAP.get(_bench_label)
    if _bench_label == "universe_cap":
        # Cap-weighted universe: pre-compute from df (no DB query needed)
        _fwd = eval_fwd_col if eval_fwd_col in df.columns else fwd_col
        if "market_cap" in df.columns and _fwd in df.columns:
            _uw = df[["date", "market_cap", _fwd]].dropna()
            _cap_sum = _uw.groupby("date")["market_cap"].sum()
            _cap_ret = (_uw[_fwd] * _uw["market_cap"]).groupby(_uw["date"]).sum()
            bench_returns_by_date = (_cap_ret / _cap_sum).dropna().to_dict()
            print(f"[Benchmark] cap-weighted universe: {len(bench_returns_by_date)} dates", flush=True)
        else:
            print("[Benchmark] WARNING: market_cap not available, falling back to equal-weight universe", flush=True)
            bench_returns_by_date = {}
    elif _bench_index_code:
        bench_returns_by_date = _load_benchmark_returns(args.db, _bench_index_code, args.horizon)
        if not bench_returns_by_date:
            print(f"[Benchmark] WARNING: falling back to universe average (no data for {_bench_index_code})", flush=True)
    else:
        bench_returns_by_date = {}

    splits = walk_forward_split(df, train_years=args.train_years)
    if not splits:
        print("No walk-forward splits available. Widen date range or reduce train years.")
        return
    cpu_count = os.cpu_count() or 4
    workers = max(1, args.workers)
    split_years = [int(s[2]["test_year"]) for s in splits]

    if args.model_jobs > 0:
        model_jobs = args.model_jobs
    else:
        model_jobs = max(1, cpu_count // workers) if workers > 1 else -1

    # Resolve model params for summary
    ModelClassInfo = get_model_class(args.model)
    model_params = ModelClassInfo.BEST_PARAMS.copy()
    model_params["learning_rate"] = args.learning_rate
    model_params["n_estimators"] = args.n_estimators

    # ── Config Summary ──
    print("\n" + "=" * 70)
    print("  BACKTEST CONFIG")
    print("=" * 70)
    print(f"\n{'--- Data ---':^70}")
    print(f"  Period:           {args.start} ~ {args.end}")
    _max_cap = getattr(args, "max_market_cap", None)
    _cap_str = f"{args.min_market_cap:,} ~ {_max_cap:,}" if _max_cap else f">= {args.min_market_cap:,}"
    print(f"  Universe:         market_cap {_cap_str}")
    print(f"  Rows:             {len(df):,}   Features: {len(feature_cols)}")
    print(f"\n{'--- Model ---':^70}")
    print(f"  Type:             {args.model}")
    obj = model_params.get('objective', 'N/A')
    obj_detail = ""
    if obj == "lambdarank":
        trunc = model_params.get('lambdarank_truncation_level', 'N/A')
        obj_detail = f" (truncation={trunc}, eval_at={model_params.get('eval_at', 'N/A')})"
    elif "huber" in str(obj):
        obj_detail = f" (huber_delta={model_params.get('huber_delta', 'N/A')})"
    print(f"  Objective:        {obj}{obj_detail}")
    print(f"  Target:           {target_col}")
    print(f"  Target Source:    {base_col}")
    print(f"  LR / Estimators:  {args.learning_rate} / {args.n_estimators}")
    print(f"  Early Stop:       patience={args.patience}")
    depth = model_params.get('max_depth', 'N/A')
    print(f"  Leaves / Depth:   {model_params.get('num_leaves', 'N/A')} / max_depth={depth}")
    print(f"  Min Data/Leaf:    {model_params.get('min_data_in_leaf', 'N/A')}")
    print(f"  Feature Frac:     {model_params.get('feature_fraction', 'N/A')}")
    print(f"  Time Decay:       {args.time_decay}")
    print(f"\n{'--- Walk-Forward ---':^70}")
    print(f"  Train Window:     {args.train_years} years (rolling)")
    print(f"  Folds:            {len(splits)}   Test Years: {split_years}")
    print(f"  Embargo:          {args.embargo_days} days")
    if exclude_years:
        print(f"  Excluded Years:   {sorted(exclude_years)}")
    print(f"\n{'--- Portfolio ---':^70}")
    print(f"  Top N:            {args.top_n}")
    print(f"  Portfolio Size:   {args.portfolio_size:,} KRW  (discrete share rounding)")
    print(f"  Rebalance/Horizon: every {args.horizon} trading days")
    _bench_display_map = {
        "universe": "universe (equal-weight)",
        "universe_cap": "universe (cap-weighted)",
    }
    _bench_display = _bench_display_map.get(_bench_label) or _bench_index_code or _bench_label
    print(f"  Benchmark:        {_bench_display}  [{_bench_label}]")
    print(f"  Buy Rank:         <= {args.buy_rank}   Hold Rank: <= {args.hold_rank}")
    print(f"  Fees:             buy={effective_buy_fee:.2f}%  sell={effective_sell_fee:.2f}%")
    print(f"  Sector Neutral:   {effective_sector_neutral}")
    print(f"  Weighting:        {'signal-proportional (score_rank)' if getattr(args, 'signal_weight', False) else 'equal-weight'}")
    cash_out_flag = getattr(args, "cash_out", False)
    print(f"  Cash-Out (20d):   {cash_out_flag}")
    print(
        "  Turnover Test:    "
        f"hold_rank<={args.turnover_test_hold_rank}, "
        f"smoothing_alpha={args.turnover_test_smoothing_alpha:.2f}"
    )
    if args.stress_mode:
        print(f"  Stress Mode:      ON (vol_exclude={args.vol_exclude_pct:.0%})")
    if exec_lag > 0 and twap_days == 0:
        print(f"  Exec Lag:         T+{exec_lag} {exec_price}  [{eval_fwd_col}]  ← Test 1")
    if stop_loss_pct > 0:
        print(f"  Stop-Loss:        {stop_loss_pct:.0%}  (intraperiod cap, cash for remainder)")
    if twap_days > 0:
        H = args.horizon
        print(f"  TWAP:             {twap_days}d — entry avg(T+1~T+{twap_days}), exit avg(T+{H-twap_days+1}~T+{H})  [{eval_fwd_col}]")
    if getattr(args, "min_daily_value", 0) > 0:
        print(f"  Liquidity Floor:  daily_value >= {args.min_daily_value:,} KRW  ← Test 5")
    if permute_feature:
        print(f"  Permutation:      feature='{permute_feature}' (ALL rows shuffled)  ← Test 4")
    print("=" * 70 + "\n", flush=True)

    rows = []
    sector_rows = []
    fold_payloads = [
        {
            "train_df": train_df,
            "test_df": test_df,
            "info": info,
            "feature_cols": feature_cols,
            "target_col": target_col,
            "fwd_col": fwd_col,
            "eval_fwd_col": eval_fwd_col,
            "min_daily_value": getattr(args, "min_daily_value", 0),
            "top_n": args.top_n,
            "rebalance_days": args.horizon,
            "time_decay": args.time_decay,
            "model_jobs": model_jobs,
            "buy_fee_rate": effective_buy_fee / 100.0,
            "sell_fee_rate": effective_sell_fee / 100.0,
            "learning_rate": args.learning_rate,
            "n_estimators": args.n_estimators,
            "patience": args.patience,
            "min_market_cap": args.min_market_cap,
            "max_market_cap": getattr(args, "max_market_cap", None),
            "stress_mode": args.stress_mode,
            "vol_exclude_pct": args.vol_exclude_pct,
            "sector_neutral_score": effective_sector_neutral,
            "buy_rank": args.buy_rank,
            "hold_rank": args.hold_rank,
            "embargo_days": args.embargo_days,
            "cash_out": args.cash_out,
            "weighting": getattr(args, "weighting", "equal"),
            "bench_returns_by_date": bench_returns_by_date,
            "model_class": args.model,
            "run_turnover_test": not args.disable_turnover_test,
            "turnover_test_hold_rank": args.turnover_test_hold_rank,
            "turnover_test_smoothing_alpha": args.turnover_test_smoothing_alpha,
            "portfolio_size": args.portfolio_size,
            "stop_loss_pct": stop_loss_pct,
        }
        for train_df, test_df, info in splits
    ]

    if workers == 1 or len(fold_payloads) == 1:
        # Sequential: carry holdings across folds to avoid 100% turnover at fold boundaries
        fold_results = []
        carry_holdings: list[str] = []
        carry_holdings_tuned: list[str] = []
        carry_scores_tuned: dict[str, float] = {}
        for p in fold_payloads:
            p["prev_holdings"] = carry_holdings
            p["prev_holdings_tuned"] = carry_holdings_tuned
            p["prev_scores_tuned"] = carry_scores_tuned
            res = _run_fold(p)
            fold_results.append(res)
            carry_holdings = res.get("final_holdings", [])
            carry_holdings_tuned = res.get("final_holdings_tuned", [])
            carry_scores_tuned = res.get("final_scores_tuned", {})
    else:
        fold_results = []
        try:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(_run_fold, p) for p in fold_payloads]
                for fut in as_completed(futures):
                    fold_results.append(fut.result())
                    done_years = sorted([int(r["test_year"]) for r in fold_results])
                    print(f"[Backtest] completed folds so far: {done_years}", flush=True)
        except (PermissionError, OSError) as exc:
            print(f"[Backtest] multiprocessing unavailable ({exc}); fallback to sequential", flush=True)
            carry_holdings = []
            carry_holdings_tuned = []
            carry_scores_tuned = {}
            fold_results = []
            for p in fold_payloads:
                p["prev_holdings"] = carry_holdings
                p["prev_holdings_tuned"] = carry_holdings_tuned
                p["prev_scores_tuned"] = carry_scores_tuned
                res = _run_fold(p)
                fold_results.append(res)
                carry_holdings = res.get("final_holdings", [])
                carry_holdings_tuned = res.get("final_holdings_tuned", [])
                carry_scores_tuned = res.get("final_scores_tuned", {})

    fold_results.sort(key=lambda x: x["test_year"])
    pick_rows = []
    for res in fold_results:
        rows.extend(res["rows"])
        sector_rows.extend(res.get("sector_rows", []))
        pick_rows.extend(res.get("pick_rows", []))

    results = pd.DataFrame(rows)
    if not results.empty:
        results = results.sort_values(["date", "test_year"]).reset_index(drop=True)
    if not results.empty:
        # ── Output folder: runs/<name>/ ────────────────────────────────────
        run_name = Path(args.output).stem   # strip any accidental .csv suffix
        run_dir  = Path("runs") / run_name
        run_dir.mkdir(parents=True, exist_ok=True)

        out_csv = run_dir / "results.csv"
        results.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"Saved detailed results to {out_csv}")


        if args.save_picks and pick_rows:
            picks_df = pd.DataFrame(pick_rows).sort_values(["date", "rank_pos"])
            picks_df.to_csv(run_dir / "picks.csv", index=False, encoding="utf-8-sig")
            print(f"Saved picks to {run_dir / 'picks.csv'} ({len(picks_df)} rows)")
            _generate_picks_chart(picks_df, fwd_col=eval_fwd_col, output_path=str(run_dir / "picks.png"))

    latest_model = None
    if splits:
        latest_split = max(splits, key=lambda x: x[2]["test_year"])
        latest_train_df = latest_split[0]
        train_years = sorted(latest_train_df["date"].str[:4].unique())
        val_year = train_years[-1]
        sub_train = latest_train_df[latest_train_df["date"].str[:4] != val_year]
        val_df = latest_train_df[latest_train_df["date"].str[:4] == val_year]
        if sub_train.empty:
            sub_train, val_df = latest_train_df, None
        FinalModelClass = get_model_class(args.model)
        latest_model = FinalModelClass(feature_cols=feature_cols, target_col=target_col, time_decay=args.time_decay)
        params = latest_model.BEST_PARAMS.copy()
        params["n_jobs"] = max(1, cpu_count // 2)
        params["learning_rate"] = args.learning_rate
        params["n_estimators"] = args.n_estimators
        latest_model.patience = args.patience
        latest_model.train(sub_train, val_df, params=params)
        latest_model.metadata = {
            "min_market_cap": args.min_market_cap,
            "max_market_cap": getattr(args, "max_market_cap", None),
            "horizon": args.horizon,
            "top_n": args.top_n,
            "sector_neutral_score": effective_sector_neutral,
            "min_daily_value": getattr(args, "min_daily_value", 0),
            "backtest_end": args.end,
        }
        run_name = Path(args.output).stem
        run_dir  = Path("runs") / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        model_path = run_dir / "model.pkl"
        latest_model.save(str(model_path))
        print(f"Saved unified model to {model_path}")

    run_name = Path(args.output).stem
    run_dir  = Path("runs") / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    # ── Feature Importance (avg gain across folds) ────────────────────────
    _fi_rows = [r.get("feature_importance") for r in fold_results if r.get("feature_importance")]
    if _fi_rows:
        all_features = list(_fi_rows[0].keys())
        avg_importance = {f: sum(d.get(f, 0) for d in _fi_rows) / len(_fi_rows) for f in all_features}
        total = sum(avg_importance.values()) or 1.0
        sorted_fi = sorted(avg_importance.items(), key=lambda x: x[1], reverse=True)

        print("\n" + "=" * 70)
        print("  FEATURE IMPORTANCE (avg gain across folds)")
        print("=" * 70)
        print(f"  {'Feature':<35} {'Avg Gain%':>9}  Bar")
        print("-" * 70)
        for feat, imp in sorted_fi:
            pct = imp / total * 100
            bar = "█" * int(pct / 1.5)
            dead = "  ← dead" if pct < 0.05 else ""
            print(f"  {feat:<35} {pct:>8.2f}%  {bar}{dead}")
        print("=" * 70)

    summarize(results, sector_rows, output_path=str(run_dir / "report.png"), model=latest_model)

    # ── Auto-generate interactive dashboard ───────────────────────────────
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import dashboard as _dash
        print("\n[Dashboard] Generating interactive HTML dashboard ...")
        results_dt = results.copy()
        results_dt["date"] = pd.to_datetime(results_dt["date"].astype(str).str[:8], format="%Y%m%d")

        universe_df = _dash.query_universe(
            args.db,
            results_dt["date"].dt.strftime("%Y%m%d").tolist(),
            args.min_market_cap,
        )
        picks_df = _dash.parse_top_picks(results_dt)
        sector_df_dash = pd.DataFrame(sector_rows) if sector_rows else pd.DataFrame()

        figs = {
            "cumret":        _dash.fig_cumret(results_dt),
            "3d_picks":      _dash.fig_3d_picks(picks_df),
            "3d_quintile":   _dash.fig_3d_quintile(results_dt),
            "3d_alpha":      _dash.fig_3d_risk_return(results_dt, universe_df),
            "return_dist":   _dash.fig_return_dist(results_dt),
            "ic":            _dash.fig_ic_bar(results_dt),
            "annual_sharpe": _dash.fig_annual_sharpe(results_dt),
            "drawdown":      _dash.fig_drawdown(results_dt),
            "turnover":      _dash.fig_turnover(results_dt),
            "sector":        _dash.fig_sector_bar(sector_df_dash),
        }
        html = _dash.build_html(figs, title=run_name)
        dash_path = run_dir / "dashboard.html"
        dash_path.write_text(html, encoding="utf-8")
        size_mb = dash_path.stat().st_size / 1_048_576
        print(f"[Dashboard] ✅ Saved → {dash_path}  ({size_mb:.1f} MB)")
        print(f"  open {dash_path}")
    except Exception as _e:
        print(f"[Dashboard] Warning: dashboard generation failed ({_e}). Run manually: python3 scripts/dashboard.py {run_name}")


def main() -> None:
    class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.MetavarTypeHelpFormatter):
        """Show defaults and type-based metavars in --help output."""

    parser = argparse.ArgumentParser(
        description="Run unified model backtest",
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "--model",
        type=str,
        default="lgbm",
        choices=["lgbm", "xgboost", "catboost"],
        help="Model family",
    )
    parser.add_argument("--db", type=str, default="data/krx_stock_data.db", help="SQLite DB path")
    parser.add_argument("--start", type=str, default="20100101", help="Start date (YYYYMMDD)")
    parser.add_argument("--end", type=str, default=None, help="End date (YYYYMMDD, default: latest date in DB)")
    parser.add_argument("--horizon", type=int, default=63, help="Forward return horizon (trading days)")
    parser.add_argument(
        "--benchmark", type=str, default="kospi200",
        choices=list(BENCHMARK_INDEX_MAP.keys()),
        help="Benchmark index for performance comparison "
             "(kospi200, kospi, kosdaq, kosdaq150, universe). Default: kospi200",
    )
    parser.add_argument("--top-n", type=int, default=30, help="Portfolio size at each rebalance")
    parser.add_argument("--portfolio-size", type=int, default=100_000_000,
                        help="Portfolio size in KRW for discrete share rounding (default: 100,000,000 = 100M KRW)")
    parser.add_argument("--train-years", type=int, default=5, help="Walk-forward training window in years")
    parser.add_argument("--min-market-cap", type=int, default=500_000_000_000, help="Minimum market cap filter")
    parser.add_argument("--max-market-cap", type=int, default=None, help="Maximum market cap filter (e.g. 5000000000000 = 5T KRW, targets SMID-cap universe)")
    parser.add_argument("--time-decay", type=float, default=0.2, help="Sample time-decay strength")
    parser.add_argument("--learning-rate", type=float, default=0.005, help="Model learning rate")
    parser.add_argument("--n-estimators", type=int, default=3000, help="Max boosting rounds")
    parser.add_argument("--patience", type=int, default=300, help="Early-stopping rounds")
    parser.add_argument("--output", type=str, default="run",
                        help="Run name — all outputs saved to runs/<name>/ (results.csv, report.png, model.pkl, ...)")
    parser.add_argument("--model-out", type=str, default="",
                        help="(ignored) model saved to runs/<name>/model.pkl automatically")
    parser.add_argument("--workers", type=int, default=1, help="Parallel walk-forward workers (default 1 = sequential, preserves holdings across folds; >1 = faster but resets holdings at fold boundaries)")
    parser.add_argument("--model-jobs", type=int, default=0, help="Model threads per worker (0=auto)")
    parser.add_argument("--buy-fee", type=float, default=0.05, help="Buy fee percent per trade")
    parser.add_argument("--sell-fee", type=float, default=0.25, help="Sell fee percent per trade")
    parser.add_argument("--stress-mode", action="store_true", help="Enable realism stress tests")
    parser.add_argument("--vol-exclude-pct", type=float, default=0.10, help="Exclude top N%% volatility names")
    parser.add_argument("--sector-neutral-score", action="store_true", default=True, help="Enable sector-neutral ranking")
    parser.add_argument("--no-sector-neutral", action="store_true", help="Disable sector-neutral ranking")
    parser.add_argument("--buy-rank", type=int, default=10, help="Buy only if rank <= threshold")
    parser.add_argument("--hold-rank", type=int, default=90, help="Hold while rank <= threshold")
    parser.add_argument("--embargo-days", type=int, default=21, help="Purged embargo gap in trading days")
    parser.add_argument("--cash-out", action="store_true", default=True, help="Enable 20d regime cash-out rule")
    parser.add_argument("--no-cash-out", action="store_true", help="Disable cash-out rule")
    parser.add_argument("--exclude-years", type=str, default="", help="Comma-separated years to remove (e.g. 2023,2024)")
    parser.add_argument("--turnover-test-hold-rank", type=int, default=120, help="Hold-rank in turnover test variant")
    parser.add_argument("--turnover-test-smoothing-alpha", type=float, default=0.70, help="EMA alpha for turnover test")
    parser.add_argument("--disable-turnover-test", action="store_true", help="Disable turnover test variant")
    parser.add_argument("--save-picks", action="store_true", help="Save picked stocks per rebalance date to CSV")
    parser.add_argument("--composite-target", action="store_true", help="Use composite multi-horizon target (0.4*rank_21d + 0.4*rank_42d + 0.2*rank_63d) instead of single-horizon residual rank")
    parser.add_argument("--weighting", type=str, default="equal",
                        choices=["equal", "signal", "signal_vol"],
                        help="Portfolio weighting: equal (default), signal (∝ score_rank), signal_vol (∝ score_rank / volatility_21d)")
    parser.add_argument("--no-cache", action="store_true", help="Disable feature cache")
    parser.add_argument("--log-level", type=str, default="WARNING", help="Python logging level")
    # ── Stress Tests ──────────────────────────────────────────────────────
    parser.add_argument("--exec-lag", type=int, default=1,
                        help="Test 1 (Execution Lag): execute at T+N (default: 1 = next session)")
    parser.add_argument("--exec-price", type=str, default="close", choices=["open", "close"],
                        help="Execution price basis when --exec-lag > 0 (default: close)")
    parser.add_argument("--min-daily-value", type=int, default=0,
                        help="Test 5 (Liquidity): exclude stocks with daily trading value < N KRW (0=off, e.g. 10000000000 for 10B KRW)")
    parser.add_argument("--twap-days", type=int, default=0,
                        help="TWAP execution: spread buy/sell over N trading days. "
                             "entry=avg(close T+1..T+N), exit=avg(close T+H-N+1..T+H). "
                             "Suspended days (value=0) excluded. Capped at horizon//3. "
                             "Overrides --exec-lag. (0=off, e.g. 5)")
    parser.add_argument("--permute-feature", type=str, default="",
                        help="Test 4 (Feature Permutation): shuffle specified feature(s) across ALL rows. "
                             "Use 'all' to permute every feature. Comma-separated for multiple. "
                             "If IC/Sharpe collapses → feature has real signal. "
                             "If performance maintained after 'all' → look-ahead leakage. (''=off)")
    parser.add_argument("--stop-loss", type=float, default=0.0,
                        help="Intraperiod stop-loss threshold (0=off, e.g. 0.10 = 10%%). "
                             "If a holding drops >N%% from entry during the period, "
                             "return is capped at -N%% and remainder is held as cash. "
                             "Requires --exec-lag >= 1.")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))
    run(args)


if __name__ == "__main__":
    main()
