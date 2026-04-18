# Bias Reduction: Execution, Sample & Liquidity

> Part 2 of bias documentation. See [DATA.md](DATA.md) for look-ahead and survivorship bias controls.

---

## 3. Execution Bias

### Problem
The backtest assumes "buy/sell at today's closing price", but in live trading, filling at the exact closing price is impractical — especially for larger orders right before close.

---

### Mechanism 1: Execution Lag Test

**Location**: `scripts/run_backtest.py` → exec_lag parameter

```python
# Default: T close basis
forward_return_42d = close[T+42] / close[T] - 1

# exec_lag=1: T+1 close basis (execute next day's open/close)
forward_return_42d_lag1 = close[T+43] / close[T+1] - 1
```

Switching to T+1 execution produces comparable or better Sharpe. No execution bias confirmed — the alpha is robust to a one-day delay.

---

### Mechanism 2: Transaction Costs + Slippage

**Location**: `scripts/run_backtest.py` → return calculation

```python
net_port_ret = (1.0 + port_ret) * (1.0 - transaction_cost) - 1.0
transaction_cost = turnover * (buy_fee_rate + sell_fee_rate)
# effective_buy_fee  = buy_fee  + slippage_pct  (default: 0.05 + 0.30 = 0.35%)
# effective_sell_fee = sell_fee + slippage_pct  (default: 0.25 + 0.30 = 0.55%)
```

Actual trading costs are deducted on **every rebalance**. Default `--slippage-pct 0.3` adds 0.30% per side on top of commission to model SMID-cap bid-ask spread. Typical range: 0.10% (liquid names) to 0.50% (thin liquidity). Total tx cost over 9 years at default settings: **27.12%** (~3.0%/year).

---

## 4. Small Sample Bias

### Problem
With ~18–48 rebalances over the backtest period, the standard error of the Sharpe estimate is large. One lucky year can skew overall statistics.

---

### Mechanism 1: Ex-Best-Year Robustness Test

```python
# Dynamically find and exclude the single best year (highest total return)
best_year = results.groupby("year")["portfolio_return"].sum().idxmax()
ex_best = results[results["year"] != best_year]
```

If Sharpe ≥ 0.70 after excluding the best year, the strategy does not depend on one outlier year.
Result: Ex-2020 Sharpe = **0.89** — passes the 0.70 threshold.

---

### Mechanism 2: Quintile Monotonicity Check

```python
q_mono = int(q5 > q4 > q3 > q2 > q1)
```

If Q1–Q5 returns increase monotonically with model rank, signal consistency is confirmed. Pure luck would produce good top-quintile returns but break overall monotonicity.

---

### Mechanism 3: IC Stability (IC IR)

```
IC  = rank correlation between model scores and actual returns (per rebalance)
IC IR = mean(IC) / std(IC)   ← signal-to-noise ratio

IC IR = 0.82 → IC is on average 0.82σ above zero = stable signal
```

High IC with low IC IR = unstable (only works in certain market regimes). High IC with high IC IR = consistently predictive signal.

---

## 5. Liquidity Bias

### Problem
Small-cap stocks in the backtest have low real-world trading volume. Buying backtest quantities in live trading causes significant market impact that the backtest ignores.

---

### Mechanism 1: Minimum Daily Trading Value Filter

```python
# Exclude stocks with daily trading value below N KRW
if min_daily_value > 0 and "value" in day_df.columns:
    day_df = day_df[day_df["value"] >= min_daily_value].copy()
```

Test result with 10B KRW minimum: Sharpe 2.04 → **0.50** (strategy collapses).
This **confirms** that alpha comes from stocks with daily value below 10B KRW — the strategy is capacity-constrained.

---

### Live AUM Capacity Estimate

```
Assumptions:
  Portfolio AUM = X KRW, top-10 equal-weight
  Allocation per stock = X / 10 KRW
  Fillable limit = 10% of daily trading value (impact threshold)

Fill condition:
  X / 10 ≤ daily_value × 10%
  → X ≤ daily_value × 1 (= 1 full day of trading value)

Average daily trading value (alpha stocks): ~3–5B KRW
Max AUM: 3–5B × 10 stocks = 30–50B KRW (theoretical)
Practical limit accounting for slippage: ~5–15B KRW
```

---

## Bias Summary

| Bias Type | Risk | Defense | Result |
|-----------|------|---------|--------|
| **Look-ahead (features)** | Future data in features | PIT financials + backward rolling only; 3 index-constituent features removed 2026-04-07 (see AUDIT.md ISSUE 9) | ✅ CLEAN |
| **Look-ahead (target)** | Target leaks into features | Strict `feature_cols` separation | ✅ CLEAN |
| **Look-ahead (accrual filter)** | Bad accrual filter applied retroactively | CRITICAL — filter uses future-available financial data | 🔴 KNOWN (see AUDIT.md Issue #1) |
| **Walk-forward leakage** | Future test data in training | 43-day embargo (auto-set to horizon + exec_lag) + chronological split | ✅ CLEAN |
| **Validation leakage** | Val set extracted from test | Val split from within train window | ✅ CLEAN |
| **Survivorship (delisted)** | Failed stocks excluded | Fix A + `_exclude_delisted` | ✅ CLEAN |
| **Survivorship (halted)** | Halted stock return distortion | Fix B + `value > 0` filter | ✅ CLEAN |
| **Stuck live position (halt)** | Sell order on halted holding fails | `build_orders()` skips halted sells, carries forward | ✅ FIXED |
| **Long-duration halt (>42d)** | Forward return ≈ 0% in training | Accepted limitation — affects <0.1% of rows, filtered by liquidity floor | ⚠️ Known |
| **Execution bias** | T-close fill impossible | exec_lag=1 (T+1 close execution) | ✅ CLEAN |
| **Small sample bias** | Single-year dependency | Ex-best-year test (Ex-2025 Sharpe 0.77) | ✅ Robust |
| **Liquidity bias** | Unfillable stock selection | min-daily-value filter test | 🔴 AUM limit ~5–15B KRW |
| **Hyperparameter selection** | Params chosen after seeing fold results | None — structural limit of iterative development | ⚠️ Residual |
| **Feature selection (snooping)** | 34 surviving features selected through iterative testing | None — structural limit | ⚠️ Residual |
| **Sector label PIT** | Industry label may lag actual reclassification date | `financial_periods.available_date` (data limit, not fixable) | ⚠️ Partial |
| **Transaction cost model** | Bid-ask spread for SMID-caps | `--slippage-pct 0.3` default (0.30%/side); configurable | ✅ Modeled |
| **Hyperparameter selection** | Params chosen after seeing fold results | `--holdout-start-year 2024` freezes 2024-2026 during dev | ⚠️ Residual (holdout pending) |
| **Feature selection (snooping)** | 34 surviving features selected through iterative testing | `--holdout-start-year 2024` — holdout read only once for final Sharpe | ⚠️ Residual (holdout pending) |
| **Down Capture inflation** | 0.26 may reflect residual bias, not just skill | Needs live validation | ⚠️ Unverified |
| **Volatility filter pre-split** | Stress-mode vol filter used future quantiles | Moved inside fold loop — train-only quantile | ✅ FIXED 2026-04-19 |
| **Final model embargo** | model.pkl trained without embargo gap | Embargo applied before final model training | ✅ FIXED 2026-04-19 |
| **Financial staleness** | Stale fundamentals active for 15 months | Reduced to 180 days (covers slow annual filers) | ✅ FIXED 2026-04-19 |

---

*Last updated: 2026-04-19 — see runs/run for actual backtest results*
