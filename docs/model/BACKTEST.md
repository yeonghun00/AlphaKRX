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
| `--start` | `20120101` | Backtest start date (YYYYMMDD) |
| `--end` | `20260213` | Backtest end date (YYYYMMDD) |
| `--horizon` | `21` | Forward return horizon (trading days) |
| `--top-n` | `30` | Portfolio size |
| `--rebalance-days` | `63` | Days between rebalances |
| `--train-years` | `3` | Rolling training window (years) |
| `--min-market-cap` | `500000000000` | Min market cap (KRW) |
| `--max-market-cap` | — | Max market cap (KRW) |
| `--time-decay` | `0.4` | Sample recency weighting (0 = flat) |
| `--learning-rate` | `0.01` | Boosting learning rate |
| `--n-estimators` | `2000` | Max boosting rounds |
| `--patience` | `200` | Early stopping patience |
| `--buy-fee` | `0.5` | Buy transaction cost (%) |
| `--sell-fee` | `0.5` | Sell transaction cost (%) |
| `--buy-rank` | `5` | Max rank to buy new stocks |
| `--hold-rank` | `50` | Max rank to hold existing stocks |
| `--embargo-days` | `21` | Purged embargo gap between train and test |
| `--workers` | `4` | Parallel fold workers |
| `--stress-mode` | off | Enable stress testing |
| `--no-cache` | off | Skip feature cache (forces recompute) |
| `--output` | `default` | Run output folder name under `runs/` |
| `--save-picks` | off | Save per-rebalance stock picks to CSV |

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
    "learning_rate": 0.05,
    "feature_fraction": 0.5,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_data_in_leaf": 750,
    "n_estimators": 1000,
    "n_jobs": -1,
    "seed": 42,
}
```

Huber loss (`alpha=0.9`) is robust to return outliers. Shallow trees (`max_depth=3`, `num_leaves=7`) prevent overfitting on limited samples.

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
