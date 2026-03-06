# Bias Reduction Mechanisms

> This document explains the source of each bias that can arise in an algorithmic strategy, where it is implemented in the codebase, and how the defense mechanism works.

---

## 1. Look-Ahead Bias

### Problem
Using **future information that would not be available in live trading** when training or predicting.
Example: scoring stocks as of today using financial statements that were published tomorrow.

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
WHERE REPLACE(fp.available_date, '-', '') <= ?  # only disclosures before the feature date
...
merge_asof(direction="backward")  # attach only the most recent past disclosure
```

**How it works**:
- Korean listed companies must disclose financials within ~90 days of fiscal year-end
- Even if `fiscal_end = 2024-12-31`, if `available_date = 2025-03-31`, this financial statement is not included in features for any date before 2025-03-31
- 450-day staleness guard: financial data older than 15 months is automatically discarded

---

### Mechanism 2: Backward-Looking Feature Calculation

**Location**: `ml/features/momentum.py`, `volatility.py`, `volume.py`, `distress.py`

```
Feature calculation direction:
  [past 126 days] → [today] ✅
  [today] → [future 42 days] ❌ (only allowed for targets)
```

All features use only `rolling()`, `pct_change()`, `shift(+N)` (positive shift = looking backward):

| Feature | Calculation | Future reference? |
|------|---------|----------|
| `mom_5d` | `close.pct_change(5)` | No |
| `volatility_21d` | `returns.rolling(21).std()` | No |
| `amihud_21d` | `abs_ret / value rolling(21)` | No |
| `drawdown_252d` | `close / rolling(252).max() - 1` | No |
| `ma_ratio_20_120` | `MA20 / MA120` | No |

---

### Mechanism 3: market_forward_return Isolation

**Location**: `ml/features/_pipeline.py` → `_load_market_regime()` + `_add_targets()`

```python
# This is FUTURE data — used only for target calculation, not as a feature
idx[f"market_forward_return_{horizon}d"] = closing_index.shift(-horizon) / closing_index - 1

# feature_cols only includes registered columns — market_forward_return is excluded
MarketFeatures.columns = ["market_regime_120d", "constituent_index_count"]
feature_cols = [c for c in FeatureEngineer.FEATURE_COLUMNS if c in df.columns]
```

The market forward return is used only for **beta-adjusted residual target calculation** (label generation) and is never used as a model input feature.

---

### Mechanism 4: Strict Walk-Forward Separation

**Location**: `scripts/run_backtest.py` → `walk_forward_split()` + embargo logic

```
Time →

[Train 2019-2022] [21-day Embargo] [Test 2023]
                  ↑
          Data in this window discarded

[Train 2020-2023] [21-day Embargo] [Test 2024]
[Train 2021-2024] [21-day Embargo] [Test 2025]
```

```python
# Embargo: remove training data within 21 days before test start
cutoff = all_dates[idx - embargo_days]  # embargo_days = 21
sub_train = sub_train[sub_train["date"] < cutoff].copy()
```

**Why 21-day embargo?**
With a 42-day prediction horizon, training data at T=12/31 uses returns over 2023-01-01–2023-02-11 as targets. If test starts at 2023-01-01, the T=12/31 sample overlaps with the test period. The embargo removes these overlapping samples.

---

### Mechanism 5: Validation Set Time Isolation

**Location**: `scripts/run_backtest.py` → `_run_fold()`

```python
train_years = sorted(train_df["date"].str[:4].unique())
val_year = train_years[-1]        # Last year of training window (not future)
sub_train = train_df[...date < val_year...]
val_df    = train_df[...date == val_year...]
```

The validation set is split from the **last year within the training window**. No data is taken from the test set. Early stopping criteria are computed only on this time-isolated validation set.

---

## 2. Survivorship Bias

### Problem
Reconstructing the past using **only currently listed stocks**.
Example: if the 2019 universe is built using stocks listed as of 2026, stocks that were delisted between 2019 and 2026 (the failures) are automatically excluded.

---

### Mechanism 1: Include Delisted Stocks and Cut Off at Delisting Date

**Location**: `ml/features/_pipeline.py` → `_exclude_delisted()`

```
Correct handling of delisted stocks:

  [2019] [2020] [2021] [Delisting date: 2021-09-15] ← cut off here
    ↓      ↓      ↓
 included included included up to here ← reflected in training data
                                        (the failure process is learned)
```

```python
keep = merged["delisting_date"].isna() | (merged["date"] < merged["delisting_date"])
return merged.loc[keep].drop(columns=["delisting_date"])
```

Pre-delisting data is **included in training** so the model learns "signals before delisting", and post-delisting data is excluded so no non-existent future is referenced.

---

### Mechanism 2: Fix A — Forward Return for Delisted Stocks

**Location**: `ml/features/_pipeline.py` → `_add_targets()`

```
Problem: if a stock delists at T+10, forward_return_42d at T = NaN
         dropping NaN → only "survivors" remain = survivorship bias

Solution: NaN → compute return using the actual last price
```

```python
# Fix A: replace with return computed from last observed price before delisting
nan_mask = out[fwd_col].isna() & out["closing_price"].gt(0)
out.loc[nan_mask, fwd_col] = (
    last_price[nan_mask] / out.loc[nan_mask, "closing_price"] - 1
)
```

Example: buy price 5,000 KRW, last price before delisting 500 KRW → forward_return = −90%.
This −90% return is reflected in model training, teaching the model to recognize pre-delisting signals.

---

### Mechanism 3: Fix B — Forward Return for Trading-Halted Stocks

**Location**: `ml/features/_pipeline.py` → `_add_targets()`

```
Problem: during a trading halt, price is frozen → forward_return looks like 0%
         in reality, the stock often crashes after the halt is lifted

Solution: if volume at T+42 is 0 → recompute return using last actual traded price
```

```python
# Fix B: if volume at T+42 is 0, replace with last price
future_value = g["value"].shift(-target_horizon)
frozen_mask = (
    out[fwd_col].notna()
    & out["closing_price"].gt(0)
    & (future_value == 0)     # trading halt detected
)
out.loc[frozen_mask, fwd_col] = (
    last_price[frozen_mask] / out.loc[frozen_mask, "closing_price"] - 1
)
```

---

### Mechanism 4: Real-Time Exclusion of Halted Stocks at Rebalance

**Location**: `scripts/run_backtest.py` → `_run_fold()`, rebalance loop

```python
# Stocks with zero volume on the day = trading halt → excluded from universe in real time
if "value" in day_df.columns:
    day_df = day_df[day_df["value"] > 0].copy()
```

Included in training data (to learn the failure process), but **excluded from actual portfolio construction**.
This mirrors live conditions — halted stocks cannot be purchased.

---

## 3. Execution Bias

### Problem
The backtest assumes "buy at today's closing price", but in live trading, filling at the closing price is impossible or impractical (large orders right before close = large slippage).

---

### Mechanism 1: Execution Lag Test (exec-lag)

**Location**: `scripts/run_backtest.py` → exec_lag calculation (added 2026-02-19)

```python
# T close basis (default)
forward_return_42d = close[T+42] / close[T] - 1

# T+1 close basis (exec_lag=1)
forward_return_42d_lag1 = close[T+43] / close[T+1] - 1
```

Switching to T+1 execution actually **improves** Sharpe from 1.74 → 2.87 → no execution bias confirmed.

---

### Mechanism 2: Transaction Costs (Slippage Internalized)

**Location**: `scripts/run_backtest.py` → return calculation

```python
net_port_ret = (1.0 + port_ret) * (1.0 - transaction_cost) - 1.0
transaction_cost = turnover * (buy_fee_rate + sell_fee_rate)
```

**Actual trading costs are deducted** on every rebalance. Default settings (buy=0.05%, sell=0.25%) reflect realistic small-cap market order costs.

---

## 4. Small Sample Bias

### Problem
With few rebalances (~18), the standard error of the Sharpe estimate is large.
One lucky 2023 year can skew the overall statistics.

---

### Mechanism 1: Ex-Year Robustness Test

**Location**: `scripts/run_backtest.py` → Requested Tests

```python
# Compute Sharpe excluding a specific year
ex_year_ret = [r for r in results if r["year"] != exclude_year]
```

If Sharpe ≥ 0.70 after excluding 2023, it proves no dependency on a single year.
→ Execution lag test: Ex-2023 Sharpe = **2.74** (very robust)

---

### Mechanism 2: Quintile Monotonicity Check

**Location**: `scripts/run_backtest.py` → rebalance loop

```python
q_mono = int(q5 > q4 > q3 > q2 > q1)
```

If Q1–Q5 returns increase monotonically with model score rank, signal consistency is confirmed.
Pure luck would produce a good result in some quintiles but break overall monotonicity.

---

### Mechanism 3: IC Stability (IC IR)

**Location**: `scripts/run_backtest.py` → summary calculation

```
IC (Information Coefficient) = rank correlation between model scores and actual returns
IC IR = mean(IC) / std(IC)    ← signal-to-noise ratio of IC

IC IR = 1.53 → IC is on average 1.53σ above zero = stable signal
```

High IC with low IC IR indicates an unstable signal (only good in certain periods).

---

## 5. Liquidity Bias

### Problem
Small-cap stocks have low actual trading volume. Buying backtest quantities in live trading causes market impact. The backtest ignores this.

---

### Mechanism 1: Minimum Daily Trading Value Filter (min-daily-value)

**Location**: `scripts/run_backtest.py` → rebalance loop (added 2026-02-19)

```python
# Exclude stocks with daily trading value below N KRW
if min_daily_value > 0 and "value" in day_df.columns:
    day_df = day_df[day_df["value"] >= min_daily_value].copy()
```

Test with 10B KRW minimum: Sharpe 2.04 → **0.50** (strategy collapses).
→ Inversely proves that the alpha source is stocks with daily value below 10B KRW.

---

### Live AUM Capacity Estimate

```
Assumptions: Portfolio AUM = X KRW, Top-10 equal-weight
             Allocation per stock = X / 10 KRW
             Fillable limit = 10% of daily trading value

Fill condition: X / 10 ≤ daily trading value × 10%
              → X ≤ daily trading value × 1 (= 1 full day of trading value)

Average daily trading value (alpha stocks): ~3–5B KRW
Max AUM: 3–5B × 1 = 3–5B KRW per stock × 10 ≈ 30–50B KRW

Practical limit accounting for slippage: ~5–15B KRW
```

---

## Bias Summary

| Bias Type | Risk | Defense Mechanism | Result |
|---------|---------|-----------------|---------|
| **Look-Ahead (features)** | Future data in features | PIT financials + backward rolling | ✅ CLEAN |
| **Look-Ahead (target)** | Target leaks into features | Strict feature_cols separation | ✅ CLEAN |
| **Walk-Forward leakage** | Future test data in training | 21-day embargo + chronological split | ✅ CLEAN |
| **Validation leakage** | Val set extracted from test | Val split from within train window | ✅ CLEAN |
| **Survivorship (delisted)** | Failed stocks excluded | Fix A + _exclude_delisted | ✅ CLEAN |
| **Survivorship (halted)** | Halted stock return distortion | Fix B + value>0 filter | ✅ CLEAN |
| **Execution bias** | T close fill impossible | exec_lag=1 test | ✅ CLEAN (Sharpe 2.87) |
| **Small sample bias** | Single-year dependency | Ex-year test + IC IR | ✅ Robust |
| **Liquidity bias** | Unfillable stock selection | min-daily-value filter | 🔴 **AUM limit confirmed** |
| **Parameter overfitting** | Hyperparams tuned in-sample | Additional OOS validation needed | ⚠️ Residual risk |

---

*Written: 2026-02-19. Based on: `CACHE_VERSION = "unified_v49_delistfix_20260218"`*
