# Architecture

## System Diagram

```
KRX APIs / Raw Financial ZIPs
        |
   ETL Pipelines  ──►  data/krx_stock_data.db (SQLite)
        |
  ml/features/_pipeline.py   (data loading + merging)
        |
  ml/features/registry.py    (9 feature groups, @register pattern)
        |
  ml/models/lgbm.py          (LightGBM Huber ranker, default)
  ml/models/xgboost.py       (XGBoost alternative)
  ml/models/catboost.py      (CatBoost alternative)
        |
   ┌────┴──────────┐
Backtest           Live
scripts/           scripts/
run_backtest.py    run_live.py
   |                   |
runs/<name>/       Kiwoom REST API
  results.csv        (orders)
  picks.csv
  model.pkl
```

---

## Directory Structure

```
algostock/
├── etl/                          # Data ingestion
│   ├── krx_api.py                # KRX API client (rate-limited, parallel)
│   ├── price_etl.py              # Prices + stock master
│   ├── index_constituents_etl.py # Index membership snapshots
│   ├── delisted_stocks_etl.py    # Delisted stock list
│   ├── index_etl.py              # Market index ETL
│   ├── adj_price_etl.py          # Adjusted price chain
│   └── financial_etl.py          # IFRS financial statements
├── ml/
│   ├── features/                 # 9 feature groups (registry pattern)
│   │   ├── registry.py           # FeatureGroup base + @register
│   │   ├── _pipeline.py          # DB loading, merging, orchestration
│   │   ├── momentum.py
│   │   ├── volume.py
│   │   ├── volatility.py
│   │   ├── fundamental.py
│   │   ├── market.py
│   │   ├── sector.py
│   │   ├── sector_neutral.py
│   │   ├── distress.py
│   │   └── sector_rotation.py
│   └── models/
│       ├── base.py               # BaseRanker (save/load/predict)
│       ├── lgbm.py               # LGBMRanker (default)
│       ├── xgboost.py
│       └── catboost.py
├── scripts/
│   ├── run_backtest.py           # Walk-forward backtest + model save
│   ├── get_picks.py              # Today's picks from saved model
│   ├── run_live.py               # Rebalance schedule + Kiwoom orders
│   ├── run_etl.py                # Unified ETL runner
│   ├── auto_live.sh              # Daily launchd wrapper
│   └── setup_scheduler.sh        # Scheduler install/remove
├── tools/                        # One-off utilities
├── verification/
│   ├── verify_backtest.py        # Independent result cross-check
│   └── README.md
├── runs/                         # One folder per backtest run
│   └── <run_name>/
│       ├── results.csv
│       ├── picks.csv
│       ├── model.pkl
│       ├── report.png
│       └── CONFIG.md             # Run parameters
├── live/
│   ├── state.json                # Current holdings + last rebal
│   ├── logs/                     # Daily execution logs
│   └── orders/                   # Per-date order JSON logs
└── data/krx_stock_data.db
```

---

## Key Design Principles

**Point-in-time (PIT) safety**
Financial data is only used after its `available_date` (45/90-day rule). No future information leaks into training or evaluation. See [bias/DATA.md](bias/DATA.md).

**Walk-forward validation**
The model is never tested on training data. Rolling N-year training window, tested on the next calendar year. 21-day embargo between train and test windows.

**Transaction-cost-aware**
Buy/sell fees deducted on every rebalance. Hysteresis (`buy-rank` / `hold-rank`) reduces unnecessary turnover.

**Sector-aware**
Sector z-scores, relative momentum, breadth, and rotation signals ensure the model ranks stocks within their sector context rather than across the full universe.

**Survivorship-bias-free**
Delisted stocks are included in the universe up to their delisting date. Pre-delisting returns are recomputed from the last traded price. See [bias/DATA.md](bias/DATA.md).

**Multi-model support**
`BaseRanker` defines the interface. Swap between LightGBM, XGBoost, and CatBoost with `--model lgbm/xgboost/catboost`. Adding a new model requires ~20 lines. See [model/MODEL.md](model/MODEL.md).
