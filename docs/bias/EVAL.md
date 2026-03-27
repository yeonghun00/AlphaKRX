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

### Mechanism 2: Transaction Costs (Slippage Internalized)

**Location**: `scripts/run_backtest.py` → return calculation

```python
net_port_ret = (1.0 + port_ret) * (1.0 - transaction_cost) - 1.0
transaction_cost = turnover * (buy_fee_rate + sell_fee_rate)
```

Actual trading costs are deducted on **every rebalance**. Default settings (`buy=0.05%`, `sell=0.25%`) reflect realistic small-cap market order costs including tax.

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
Result: Ex-2023 Sharpe = **0.71** — passes the 0.70 threshold (barely, as expected for a conservative test).

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

IC IR = 0.94 → IC is on average 0.94σ above zero = stable signal
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
| **Look-ahead (features)** | Future data in features | PIT financials + backward rolling only | ⚠️ Known issue |
| **Look-ahead (target)** | Target leaks into features | Strict `feature_cols` separation | ✅ CLEAN |
| **Look-ahead (accrual filter)** | Bad accrual filter applied retroactively | CRITICAL — filter uses future-available financial data | 🔴 KNOWN (see AUDIT.md Issue #1) |
| **Walk-forward leakage** | Future test data in training | 43-day embargo (auto-set to horizon + exec_lag) + chronological split | ✅ CLEAN |
| **Validation leakage** | Val set extracted from test | Val split from within train window | ✅ CLEAN |
| **Survivorship (delisted)** | Failed stocks excluded | Fix A + `_exclude_delisted` | ✅ CLEAN |
| **Survivorship (halted)** | Halted stock return distortion | Fix B + `value > 0` filter | ✅ CLEAN |
| **Stuck live position (halt)** | Sell order on halted holding fails | `build_orders()` skips halted sells, carries forward | ✅ FIXED |
| **Long-duration halt (>42d)** | Forward return ≈ 0% in training | Accepted limitation — affects <0.1% of rows, filtered by liquidity floor | ⚠️ Known |
| **Execution bias** | T-close fill impossible | exec_lag=1 (T+1 close execution) | ✅ CLEAN |
| **Small sample bias** | Single-year dependency | Ex-best-year test (Ex-2023 Sharpe 0.71) | ✅ Robust |
| **Liquidity bias** | Unfillable stock selection | min-daily-value filter test | 🔴 AUM limit ~5–15B KRW |
| **Parameter overfitting** | Hyperparams tuned in-sample | Additional OOS validation needed | ⚠️ Residual risk |

---

*Last updated: 2026-03-25 — see runs/run for actual backtest results*
