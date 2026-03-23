# Setup & First Run

---

## Prerequisites

- Python 3.9+
- Chrome + ChromeDriver (for index constituents ETL — must match Chrome version)
- KRX Open API key (free, sign up at data.krx.co.kr)

```bash
pip install -r requirements.txt
```

---

## Configuration

### 1. API key (`config.json`)

Copy the example and fill in your KRX API key:

```bash
cp config.example.json config.json
```

Edit `config.json`:
```json
{
  "api": {
    "auth_key": "YOUR_KRX_API_KEY_HERE"
  }
}
```

### 2. Kiwoom credentials (live trading only)

Create `.env` in the project root:

```
KIWOOM_APP_KEY=your_app_key
KIWOOM_APP_SECRET=your_app_secret
KIWOOM_ACCOUNT=12345678-01
KIWOOM_MOCK=true
```

---

## Step 1: Load Data

First-time full backfill (takes hours):

```bash
python3 scripts/run_etl.py backfill --start-date 20100101 --end-date 20251231
```

Daily updates after that:

```bash
python3 scripts/run_etl.py update --markets kospi,kosdaq --workers 4
```

Verify data loaded correctly:

```bash
sqlite3 data/krx_stock_data.db "SELECT MAX(date) FROM daily_prices;"
sqlite3 data/krx_stock_data.db "SELECT MAX(date) FROM index_constituents;"
sqlite3 data/krx_stock_data.db "SELECT COUNT(*) FROM financial_periods;"
```

See [etl/ETL.md](etl/ETL.md) and [etl/DATABASE.md](etl/DATABASE.md) for pipeline details.

---

## Step 2: Run a Backtest

```bash
python3 scripts/run_backtest.py \
  --start 20100101 --end 20260101 \
  --horizon 21 --top-n 10 \
  --train-years 2 \
  --min-market-cap 100000000000 --max-market-cap 1000000000000 \
  --buy-rank 10 --hold-rank 120 \
  --buy-fee 0.05 --sell-fee 0.25 \
  --patience 100 --no-cache \
  --output myrun --save-picks
```

See [model/BACKTEST.md](model/BACKTEST.md) for all CLI flags and model hyperparameters.

---

## Step 3: View Results

Output files in `runs/myrun/`:

| File | What to look at |
|------|----------------|
| `report.png` | Equity curve vs benchmark, rolling Sharpe, drawdown |
| `results.csv` | Per-rebalance returns, alpha, IC, turnover |
| `picks.csv` | Every stock pick with score and forward return |
| `stat_significance.csv` | Sharpe t-stat, Newey-West, bootstrap CI |
| `quintiles.csv` | Q1–Q5 average returns (monotonicity check) |
| `rolling_sharpe.csv` | Rolling Sharpe over time |

**Key metrics to check:**

| Metric | Good threshold | What it means |
|--------|---------------|---------------|
| Mean IC | ≥ 0.05 | Rank correlation between scores and returns |
| IC IR | ≥ 1.5 | IC stability (signal-to-noise ratio) |
| Quintile monotonicity | Q5 > Q4 > … > Q1 | Ranking consistency |
| Down capture | < 0.7 | Downside protection vs benchmark |
| Sharpe t-stat | > 2.0 | Statistical significance (use Newey-West) |

---

## Step 4: Get Today's Picks

```bash
python3 scripts/get_picks.py --model-path runs/myrun/model.pkl --top 20
```

---

## Step 5: Live Rebalancing

```bash
# Check schedule (dry-run, no orders placed)
python3 scripts/run_live.py --run myrun

# Execute orders on rebalance day
python3 scripts/run_live.py --run myrun --execute
```

See [LIVE_TRADING.md](LIVE_TRADING.md) for full setup including Kiwoom credentials and the automated scheduler.

---

## Verify Backtest Results Independently

```bash
python3 verification/verify_backtest.py --run myrun --tolerance 0.05
```

Cross-checks picks against Naver Finance adjusted prices. See `verification/README.md`.
