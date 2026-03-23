# Live Trading

Live rebalancing via the Kiwoom REST API. `scripts/run_live.py` handles the full cycle: ETL update → schedule check → order placement → state save.

---

## Kiwoom API Setup

Create `.env` in the project root (already in `.gitignore`):

```
KIWOOM_APP_KEY=your_app_key
KIWOOM_APP_SECRET=your_app_secret
KIWOOM_ACCOUNT=12345678-01
KIWOOM_MOCK=true       # true = paper trading, false = real money
```

Start with `KIWOOM_MOCK=true` to verify the full pipeline before going live.

---

## Check Schedule (dry-run)

```bash
python3 scripts/run_live.py --run myrun
```

Shows one of:

- `⏳ N trading days until execution` — not yet, nothing to do
- `📅 Tomorrow is execution day` — previews planned picks
- `✅ Today is execution day` — shows buy/sell orders to be placed

This also runs the ETL update and refreshes today's picks from the saved model.

---

## Execute Orders

```bash
python3 scripts/run_live.py --run myrun --execute
```

On execution day:
1. Calls ETL update (refreshes prices + index data)
2. Loads `runs/myrun/model.pkl` and scores today's universe
3. Computes target portfolio: top `buy-rank` stocks to buy, anything outside `hold-rank` to sell
4. Places sell orders first (free up cash), then buy orders via Kiwoom REST API
5. Saves state to `live/state.json`
6. Logs full run to `live/logs/YYYYMMDD.log`
7. Saves order details to `live/orders/YYYYMMDD.json`

---

## Rebalance Schedule Logic

```
next_execution = last_rebalance_date + horizon + 1 trading day
```

The last rebalance date is read from `runs/myrun/results.csv` (the backtest output). `horizon` is the same value used during training — matching backtest to live ensures the model is applied at the expected holding period.

---

## Automated Scheduling

### Start (runs daily at 07:30 local time)

```bash
./scripts/setup_scheduler.sh start --run myrun --hour 7 --min 30
```

Installs a macOS `launchd` job. Auto-selects the latest run if `--run` is omitted.

### Wake Mac from sleep before scheduled time (optional)

```bash
# Wake 5 min before for a 07:30 schedule:
sudo pmset repeat wakeorpoweron MTWRF 07:25:00
```

### Check status / stop

```bash
./scripts/setup_scheduler.sh status
./scripts/setup_scheduler.sh stop
sudo pmset repeat cancel    # if you set the wake schedule
```

---

## Timezone Note

Korean market opens 9:00 AM KST = 8:00 AM HKT (UTC+8).
Run before 8:00 AM HKT to place opening orders. Running after 8:00 AM HKT means the market is open/closed and Kiwoom may reject orders.

Recommended: schedule at 07:30 HKT with Mac wake at 07:25 HKT.

---

## State Files

| Path | Contents |
|------|----------|
| `live/state.json` | Current holdings + last executed rebalance date |
| `live/logs/YYYYMMDD.log` | Full daily execution log |
| `live/orders/YYYYMMDD.json` | Per-stock order details (symbol, side, qty, price) |

---

## Capacity Limit

The strategy's alpha comes from small/mid-cap stocks with daily trading value ~3–5B KRW. Filling more than ~10% of daily volume without significant slippage limits practical AUM to roughly **5–15B KRW**.

See [bias/EVAL.md](bias/EVAL.md) for the full liquidity bias analysis.
