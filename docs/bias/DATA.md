# Bias Reduction: Look-Ahead & Survivorship

> Explains each bias source, where it is defended in the codebase, and how the mechanism works.
> See [EVAL.md](EVAL.md) for execution bias, small-sample bias, liquidity bias, and the summary table.

---

## 1. Look-Ahead Bias

### Problem
Using **future information** during training or prediction that would not be available in live trading.
Example: scoring stocks today using financial statements published tomorrow.

---

### Mechanism 1: Point-in-Time Financial Data

**Location**: `ml/features/_pipeline.py` → `_load_financial_ratios_pit()`

```
Financial statement disclosure flow:
  Fiscal year-end (12/31) → Disclosure date (Mar–May) → available_date
                                                              ↑
                                                  Only used after this date
```

```python
WHERE REPLACE(fp.available_date, '-', '') <= ?  # only disclosures before feature date
...
merge_asof(direction="backward")  # attach only the most recent past disclosure
```

Korean companies must disclose within ~90 days of fiscal year-end. Even if `fiscal_end = 2024-12-31`, if `available_date = 2025-03-31`, this statement is excluded from any feature date before 2025-03-31. A 450-day staleness guard discards financial data older than 15 months.

---

### Mechanism 2: Backward-Looking Feature Calculation

**Location**: `ml/features/momentum.py`, `volatility.py`, `volume.py`, `distress.py`

All features use only `rolling()`, `pct_change()`, `shift(+N)` (positive shift = looking backward):

| Feature | Calculation | Future reference? |
|---------|-------------|------------------|
| `mom_5d` | `close.pct_change(5)` | No |
| `volatility_21d` | `returns.rolling(21).std()` | No |
| `amihud_21d` | `abs_ret / value rolling(21)` | No |
| `drawdown_252d` | `close / rolling(252).max() - 1` | No |

---

### Mechanism 3: `market_forward_return` Isolation

**Location**: `ml/features/_pipeline.py` → `_load_market_regime()` + `_add_targets()`

```python
# FUTURE data — used only for target calculation, never as a feature
idx[f"market_forward_return_{horizon}d"] = closing_index.shift(-horizon) / closing_index - 1

# feature_cols only includes @register'd columns — market_forward_return is excluded
MarketFeatures.columns = ["market_regime_120d", "constituent_index_count"]
feature_cols = [c for c in FeatureEngineer.FEATURE_COLUMNS if c in df.columns]
```

Market forward return is used only for computing the **beta-adjusted residual target** (label generation). It is never passed to the model as an input feature.

---

### Mechanism 4: Strict Walk-Forward Separation

**Location**: `scripts/run_backtest.py` → `walk_forward_split()` + embargo logic

```
Time →

[Train 2019–2022]  [21-day Embargo]  [Test 2023]
                   ↑
           Data in this window discarded

[Train 2020–2023]  [21-day Embargo]  [Test 2024]
[Train 2021–2024]  [21-day Embargo]  [Test 2025]
```

```python
# Embargo: remove training data within 21 days before test start
cutoff = all_dates[idx - embargo_days]  # embargo_days = 21
sub_train = sub_train[sub_train["date"] < cutoff].copy()
```

With a 42-day horizon, training data at T=12/31 uses returns over the next 42 trading days as its target, overlapping with the test period. The embargo removes these overlapping samples.

---

### Mechanism 5: Validation Set Time Isolation

**Location**: `scripts/run_backtest.py` → `_run_fold()`

```python
train_years = sorted(train_df["date"].str[:4].unique())
val_year = train_years[-1]          # last year within training window
sub_train = train_df[...date < val_year...]
val_df    = train_df[...date == val_year...]
```

The validation set is the **last year within the training window**, not from the test set. Early stopping is evaluated only on this time-isolated validation set.

---

## 2. Survivorship Bias

### Problem
Reconstructing the past using **only currently listed stocks**.
Example: a 2019 universe built from 2026's listings silently excludes every company that failed between 2019 and 2026.

---

### Mechanism 1: Include Delisted Stocks, Cut Off at Delisting Date

**Location**: `ml/features/_pipeline.py` → `_exclude_delisted()`

```
[2019] [2020] [2021] [Delisting: 2021-09-15] ← cut off here
  ↓      ↓      ↓
included up to delisting date (failure process is learned)
```

```python
keep = merged["delisting_date"].isna() | (merged["date"] < merged["delisting_date"])
return merged.loc[keep].drop(columns=["delisting_date"])
```

Pre-delisting data is **included in training** so the model learns "signals before delisting". Post-delisting data is excluded.

---

### Mechanism 2: Fix A — Forward Return for Delisted Stocks

**Location**: `ml/features/_pipeline.py` → `_add_targets()`

```
Problem: if a stock delists at T+10, forward_return_42d at T = NaN
         dropping NaN → only survivors remain = survivorship bias

Solution: replace NaN with the return computed from the actual last price
```

```python
nan_mask = out[fwd_col].isna() & out["closing_price"].gt(0)
out.loc[nan_mask, fwd_col] = (
    last_price[nan_mask] / out.loc[nan_mask, "closing_price"] - 1
)
```

Example: buy price 5,000 KRW, last price before delisting 500 KRW → forward_return = −90%. This −90% enters training so the model learns pre-delisting warning signals.

---

### Mechanism 3: Fix B — Forward Return for Trading-Halted Stocks

**Location**: `ml/features/_pipeline.py` → `_add_targets()`

```
Problem: during a halt, price is frozen → forward_return = 0% (misleading)
         in reality, the stock often crashes once the halt is lifted

Solution: if volume at T+42 = 0 → recompute return using last actual traded price
```

```python
future_value = g["value"].shift(-target_horizon)
frozen_mask = out[fwd_col].notna() & out["closing_price"].gt(0) & (future_value == 0)
out.loc[frozen_mask, fwd_col] = (
    last_price[frozen_mask] / out.loc[frozen_mask, "closing_price"] - 1
)
```

---

### Mechanism 4: Real-Time Exclusion of Halted Stocks at Rebalance

**Location**: `scripts/run_backtest.py` → rebalance loop

```python
# Stocks with zero volume = trading halt (거래정지) → excluded from universe
if "value" in day_df.columns:
    day_df = day_df[day_df["value"] > 0].copy()
```

Halted stocks are **included in training** (learning the failure pattern) but **excluded from portfolio construction** — mirroring live conditions where halted stocks cannot be purchased.
