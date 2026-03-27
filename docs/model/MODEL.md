# Model & Backtest

## Architecture

```
DB (data/krx_stock_data.db)
    │
    ▼
ml/features/_pipeline.py     ← data loading, merging, orchestration
    │
    ▼
ml/features/registry.py      ← FeatureGroup base + @register + topological sort
    │
    ├── momentum.py           (intermediates only)
    ├── momentum_academic.py  (4 features)
    ├── volume.py             (2 features)
    ├── volatility.py         (1 feature)
    ├── fundamental.py        (4 features)
    ├── market.py             (2 features)
    ├── sector.py             (6 features)
    ├── sector_neutral.py     (9 features)
    ├── distress.py           (3 features)
    ├── sector_rotation.py    (3 features)
    └── macro_interaction.py  (2 features)
    │
    ▼
ml/models/                    ← multi-model support
    ├── lgbm.py               LGBMRanker (default)
    ├── xgboost.py            XGBRanker
    └── catboost.py           CatBoostRanker
    │
    ▼
scripts/run_backtest.py       ← walk-forward backtest
scripts/get_picks.py          ← live stock picks
```

---

## How It Works

1. `FeatureEngineer` builds a panel of 36 features per stock per trading day from the DB
2. Forward returns are computed as targets (default: 21 trading days ahead)
3. Data is split into yearly walk-forward folds (train on N years, test on the next year)
4. A model (LightGBM/XGBoost/CatBoost) is trained per fold to predict outperformance
5. On each rebalance date, the model scores all eligible stocks, picks the top N, and simulates a portfolio
6. Transaction costs, turnover, and Spearman IC are tracked at every rebalance

See [FEATURES.md](FEATURES.md) for the full feature reference and [BACKTEST.md](BACKTEST.md) for CLI flags and hyperparameters.

---

## Universe Filters

Applied on every rebalance date before scoring:

1. **Penny stock exclusion**: `closing_price >= 2000` KRW
2. **Low liquidity exclusion**: Drop bottom 20% by 20-day average traded value
3. **Accrual quality filter**: Exclude positive net income + negative operating CF
4. **Market cap floor**: Default `500B KRW` (`--min-market-cap`)
5. **Delisted stock exclusion**: Remove stocks after their delisting date

---

## Target Variable

| Priority | Target column | What it is |
|----------|--------------|------------|
| 1st | `target_riskadj_rank_{H}d` | Rank of (forward return / volatility_21d) |
| 2nd | `target_residual_rank_{H}d` | Rank of (forward return − beta × market return) |
| 3rd | `target_rank_{H}d` | Rank of raw forward return |

The model trains on the highest-priority target that has sufficient coverage.

---

## Walk-Forward Validation

```
Fold 1:  Train [2010–2012]  [43-day embargo]  Test [2013]
Fold 2:  Train [2011–2013]  [43-day embargo]  Test [2014]
...
```

- Last year of the training window is held out for early stopping validation (no data from test set)
- 43-day embargo (auto-set to `horizon + exec_lag` at runtime) removes samples that overlap with the test period
- Each fold trains an independent model; final evaluation is out-of-sample across all folds

See [../bias/DATA.md](../bias/DATA.md) for look-ahead and survivorship bias controls, and [../bias/EVAL.md](../bias/EVAL.md) for execution, sample, and liquidity bias.

---

## How to Add a New Feature

1. Create `ml/features/my_feature.py`:

```python
"""My custom features."""
from __future__ import annotations
import pandas as pd
from .registry import FeatureGroup, register

@register
class MyFeatures(FeatureGroup):
    name = "my_feature"
    columns = ["my_col_1", "my_col_2"]        # every column this group produces
    dependencies = ["closing_price", "ret_1d"] # columns produced by other groups

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        g = df.groupby("stock_code")
        df["my_col_1"] = g["closing_price"].pct_change(10)
        df["my_col_2"] = g["ret_1d"].rolling(10).std().droplevel(0)
        return df
```

2. Import it in `ml/features/__init__.py`:

```python
from ml.features import my_feature  # noqa: F401
```

The `@register` decorator adds it to the registry automatically. `FEATURE_COLUMNS` updates, and the model includes it on the next run.

**Key rules:**
- `columns` must list every column `compute()` adds
- `dependencies` must list columns produced by other groups (registry topologically sorts execution order)

---

## How to Add a New Model

1. Create `ml/models/my_model.py`:

```python
from __future__ import annotations
import numpy as np
import pandas as pd
from .base import BaseRanker

class MyRanker(BaseRanker):
    BEST_PARAMS = {"learning_rate": 0.03, "n_estimators": 800}

    def train(self, train_df, val_df=None, params=None, sample_weight=None):
        params = params or self.BEST_PARAMS.copy()
        X = train_df[self.feature_cols].to_numpy()
        y = train_df[self.target_col].to_numpy()
        # ... train model ...
        self.model = trained_model
        return self

    def predict(self, df):
        return self.model.predict(df[self.feature_cols].to_numpy())
```

2. Register in `ml/models/__init__.py`:

```python
from ml.models.my_model import MyRanker

def get_model_class(name):
    models = {
        "lgbm": LGBMRanker,
        "xgboost": XGBRanker,
        "catboost": CatBoostRanker,
        "my_model": MyRanker,    # ← add here
    }
```

3. Use it: `python3 scripts/run_backtest.py --model my_model`
