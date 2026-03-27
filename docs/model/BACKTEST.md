# CLI & Model Hyperparameter Reference

---

## `run_backtest.py` — Walk-Forward Backtest

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

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `lgbm` | Model backend: `lgbm`, `xgboost`, `catboost` |
| `--start` | `20100101` | Backtest start date (YYYYMMDD) |
| `--end` | `20260213` | Backtest end date (YYYYMMDD) |
| `--horizon` | `63` | Forward return horizon (trading days) |
| `--top-n` | `30` | Portfolio size |
| `--train-years` | `5` | Rolling training window (years) |
| `--min-market-cap` | `500000000000` | Min market cap (KRW) |
| `--max-market-cap` | — | Max market cap (KRW) |
| `--time-decay` | `0.2` | Sample recency weighting (0=flat, higher=more recent) |
| `--learning-rate` | `0.005` | Boosting learning rate |
| `--n-estimators` | `3000` | Max boosting rounds |
| `--patience` | `300` | Early stopping patience |
| `--buy-fee` | `0.05` | Buy transaction cost (%) |
| `--sell-fee` | `0.25` | Sell transaction cost (%) |
| `--buy-rank` | `10` | Max rank to buy new stocks |
| `--hold-rank` | `90` | Max rank to hold existing stocks |
| `--embargo-days` | `21` (auto) | Purged embargo gap (auto-set to horizon + exec_lag at runtime, e.g., 43 for horizon=21) |
| `--workers` | `4` | Parallel fold workers |
| `--exec-lag` | `1` | Execution lag (0=close, 1=T+1 close) |
| `--benchmark` | `kospi200` | Benchmark: `kospi200`, `kosdaq`, `universe`, or `kosdaq150` |
| `--stress-mode` | off | Enable stress testing with elevated fees (buy 0.5%, sell 0.5%) |
| `--vol-exclude-pct` | `0.10` | Stress mode: exclude top N% most volatile names |
| `--no-cache` | off | Skip feature cache (forces recompute) |
| `--output` | `default` | Run output folder name under `runs/` |
| `--save-picks` | off | Save per-rebalance stock picks to CSV |

### Stress-Test & Advanced Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--exec-price` | `close` | Execution price: `close` or `open` |
| `--twap-days` | `0` | TWAP execution: spread entry/exit over N days (0=off, max=horizon//3) |
| `--stop-loss` | `0` | Intraperiod stop-loss threshold (0=off, e.g. 0.10 = cap at -10%) |
| `--permute-feature` | — | Shuffle features to test robustness: `--permute-feature all` or `--permute-feature roe,gpa` |
| `--exclude-years` | — | Exclude specific years: `--exclude-years 2020,2023` |
| `--min-daily-value` | `0` | Exclude stocks with daily trading value < N KRW (e.g. 10000000000 for 10B KRW) |
| `--sector-neutral-score` | on | Enable sector-neutral ranking (default on) |
| `--no-sector-neutral` | off | Disable sector-neutral ranking |
| `--cash-out` / `--no-cash-out` | on | Enable/disable 20d regime cash-out rule |
| `--turnover-test-hold-rank` | `120` | Hold-rank in turnover reduction test variant |
| `--disable-turnover-test` | off | Disable turnover test variant |
| `--model-jobs` | `0` | Model threads per worker (0=auto) |
| `--log-level` | `WARNING` | Python logging level |

---

## `get_picks.py` — Today's Picks from Saved Model

```bash
python3 scripts/get_picks.py --model-path runs/myrun/model.pkl --top 20
```

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `lgbm` | Model backend |
| `--end` | today | Feature data end date |
| `--top` | `20` | Number of buy picks to show |
| `--bottom` | `10` | Number of avoid picks to show |
| `--horizon` | `21` | Forward return horizon |
| `--min-market-cap` | `500000000000` | Min market cap (KRW) |
| `--model-path` | `models/lgbm_unified.pkl` | Path to saved model |
| `--retrain` | off | Retrain from scratch instead of loading |
| `--no-cache` | off | Skip feature cache |

---

## Model Hyperparameters

### LightGBM (default, `--model lgbm`)

```python
{
    "objective": "huber",
    "metric": "huber",
    "alpha": 0.9,
    "boosting_type": "gbdt",
    "num_leaves": 7,
    "max_depth": 3,
    "lambda_l1": 0.1,
    "lambda_l2": 1.0,
    "min_gain_to_split": 0.01,
    "min_data_in_leaf": 1500,
    "feature_fraction": 0.4,
    "bagging_fraction": 0.7,
    "bagging_freq": 5,
    "learning_rate": 0.005,
    "n_estimators": 3000,
    "n_jobs": -1,
    "seed": 42,
}
```

Huber loss (`alpha=0.9`) is robust to return outliers. Shallow trees (`max_depth=3`, `num_leaves=7`) with strong regularization (`lambda_l1=0.1`, `lambda_l2=1.0`) prevent overfitting. CLI `--learning-rate` overrides the default 0.005.

### XGBoost (`--model xgboost`)

```python
{
    "objective": "reg:pseudohubererror",
    "max_depth": 6,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "colsample_bytree": 0.75,
    "min_child_weight": 80,
    "n_estimators": 800,
}
```

Requires `pip install xgboost`.

### CatBoost (`--model catboost`)

```python
{
    "loss_function": "Huber:delta=1.0",
    "depth": 6,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "colsample_bylevel": 0.75,
    "min_data_in_leaf": 80,
    "iterations": 800,
}
```

Requires `pip install catboost`.
