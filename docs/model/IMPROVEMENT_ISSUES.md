# Model Improvement Issues

**Backtest Reference:** 2010–2026, LGBM, target=`target_residual_rank_42d`, universe=market_cap≥200B KRW  
**Date Identified:** 2026-04-03

---

## Issue 1: Near-Null Models in Certain Folds

### Observed Symptoms

| Fold | Best Iter | Train IC | Val IC | IC Ratio | Status |
|------|-----------|----------|--------|----------|--------|
| 2018 | 111       | 0.2349   | 0.0459 | 0.20     | OVERFIT |
| 2019 | **15**    | 0.1347   | 0.1213 | 0.90     | OK but degenerate |
| 2021 | **23**    | 0.1740   | 0.0802 | 0.46     | OVERFIT |
| 2026 | 2133      | 0.2770   | 0.1250 | 0.45     | OVERFIT |

Best iterations of 15 and 23 are degenerate — the model took fewer gradient steps than a simple linear regression would need.

### Root Cause

**Model capacity ceiling is hit too fast, not classic overfitting.**

All three constraints are simultaneously active:
```
max_leaves=7  +  max_depth=3  +  min_data_in_leaf=1500  +  lr=0.005
```

On a 250k–350k row dataset, `max_leaves=7` carves only ~7 buckets from the entire feature space per tree. The Huber gradient goes flat in ~15–20 iterations because there is nothing left to learn within these constraints — the model has exhausted its capacity, not overfit in the traditional sense.

**Secondary cause: Validation set regime mismatch.**

The validation set is the last N months of the training window. This means:
- Fold 2019: val = H2 2018 (bear market) → test = 2019 (bull market)
- Fold 2021: val = late 2020 (COVID bounce) → test = 2021 (bull then crash)

Early stopping fires on a validation regime that does not match the test period.

### Fixes

**A. Increase model capacity** ← do this first

```python
# Current (too constrained)
num_leaves=7, max_depth=3, min_data_in_leaf=1500

# Target
num_leaves=31, max_depth=6, min_data_in_leaf=500
```

300k rows with 7 leaves is equivalent to a shallow decision stump. The dataset comfortably supports 31 leaves. Existing regularization (`feature_frac`, `time_decay`, `min_data_in_leaf`) is sufficient to prevent overfitting at higher capacity.

**B. Set minimum iteration floor**

```python
min_n_estimators = 200   # never stop before 200 rounds
early_stopping_rounds = 300
```

A best_iter of 15 is a degenerate solution. Force at least 200 gradient steps.

**C. Increase time decay: 0.2 → 0.5**

At `time_decay=0.2`, data from 3 years ago has relative weight ~0.55. The 2021 fold trains heavily on COVID crash data (2018–2020), which confuses the model with a non-representative regime. At `time_decay=0.5`, recent data dominates and regime-mixing noise is reduced.

```
Current decay weight at 36 months back: exp(-0.2 * 3) ≈ 0.55
Target  decay weight at 36 months back: exp(-0.5 * 3) ≈ 0.22
```

**D. Fix validation set construction** ← structural fix

Replace single-period (most-recent) validation with a multi-period or gap-based approach:

```
Option A: Train on [T-3, T-1] minus last 6m  |  Val = last 6m + random 6m from T-2
Option B: Val = fixed calendar window (e.g., always Q1 of test year)
```

This prevents early stopping from being calibrated on the wrong market regime.

---

## Issue 2: Non-Monotonic / Thin Quintile Spread

### Observed Symptoms

```
Q1(Worst)   Q2      Q3      Q4      Q5(Best)
 +2.37%   +2.58%  +3.71%  +3.08%  +3.28%   [NOT MONOTONIC]
```

- Total Q1→Q5 spread: **~0.9%** per 42-day period — very thin
- Q3 > Q4 breaks monotonicity — model loses discrimination in the middle buckets
- Long-Short (Top 10% - Bottom 10%): **13.29%, Sharpe 0.67** — mediocre rank signal across the full distribution

### Root Cause

**Feature breadth and alpha diversity, not model architecture.**

The model can identify extremes (clear junk vs clear quality) but loses discrimination in Q2–Q4. This is a signal quality problem, not a model capacity problem.

**Double-neutralization compresses signal further:**
- Target is already `residual_rank` (market/sector adjusted)
- Portfolio is sector-neutral on top

This is correct for cleanliness but requires genuinely idiosyncratic factors to work. Correlated price/momentum features get double-removed and leave little spread.

### Fixes

**A. SHAP audit before adding anything** ← do this first

Run feature importance / SHAP and check:
- Do top 5 features explain >70% of the score? → concentration problem
- Are features clustered (e.g., 10 momentum variants)? → redundancy problem

If either is true, adding more correlated features will not help.

**B. Add alpha factor diversity**

Categories likely absent from current 36 features:

| Category | Example Features | Why It Helps |
|---|---|---|
| Earnings quality | Accruals ratio, cash flow / net income | Non-price signal, low correlation to momentum |
| Analyst revision | FY1 EPS revision 1m / 3m | Forward-looking, adds short-term IC lift |
| Earnings surprise | SUE (standardized unexpected earnings) | Strong IC in Korean mid/large caps |
| Fundamental stability | ROE volatility 3yr, margin stability | Penalizes noise companies, stable alpha |
| Short interest | Borrow rate, short % of float | Sentiment signal orthogonal to price |

Each category adds a covariance-orthogonal source of signal. This is the primary lever for widening quintile spread.

**C. Composite multi-horizon target**

```python
# Instead of pure 42d rank
target = 0.4 * rank_21d + 0.4 * rank_42d + 0.2 * rank_63d
```

Single-horizon rank targets are noisy. Blending horizons smooths label noise and produces better-separated quintiles, particularly in the middle buckets.

**D. Increase feature_fraction: 0.4 → 0.65**

With 36 features, `feature_frac=0.4` means each tree sees ~14 features. If features are correlated, the model repeatedly hits the same signal. At 0.65 (~23 features/tree), coverage improves.

---

## What NOT to Do

| Temptation | Why to Avoid |
|---|---|
| Switch model type (LightGBM → XGBoost / NN) | Architecture is not the bottleneck |
| Add more raw data | 1M+ rows is already sufficient |
| Tune LR / estimators before fixing capacity | LR only matters once trees are expressive enough |
| Add correlated feature variants | Redundancy worsens, not improves, quintile spread |

---

## Action Plan

### Phase 1 — Model Capacity (TESTED AND REVERTED)

Attempted: `num_leaves` 7→31, `max_depth` 3→6, `min_data_in_leaf` 1500→500, `lambda_l2` 1.0→3.0, `min_n_estimators=200` floor.

**Result: Reverted.** Capacity increase inflated train IC (0.13–0.28 → 0.28–0.43) without proportional OOS improvement. Sharpe degraded 1.30→1.15, Calmar 1.50→1.15, Max DD worsened. The near-null model warnings in 2019/2021 (best_iter=15/23) are caused by **validation set regime mismatch**, not insufficient capacity — those folds performed fine OOS (+11.99%, +41.07%). No further capacity tuning recommended until Fix D is implemented.

**Real fix: Fix D — validation set construction.**

### Phase 2 — Target Improvement
- [ ] Replace `target_residual_rank_42d` with composite multi-horizon target
- [ ] Validate quintile spread improves before proceeding

**Expected outcome:** Quintile monotonicity restored, spread widens.

### Phase 3 — Feature Audit + Diversity
- [ ] Run SHAP analysis on current 36 features, identify redundant clusters
- [ ] Add earnings quality features (accruals, CFO/NI)
- [ ] Add analyst revision momentum (FY1 EPS revision)
- [ ] Add earnings surprise (SUE)
- [ ] Re-run backtest, compare quintile spread vs baseline

**Expected outcome:** Quintile spread +30–50bps, long-short Sharpe from 0.67 → 1.0+.

---

## Success Metrics

| Metric | Current | Target |
|---|---|---|
| Worst fold best_iter | 15 (2019) | ≥200 across all folds |
| IC ratio worst fold | 0.20 (2018) | ≥0.40 across all folds |
| Q1→Q5 spread | ~0.9% | ≥1.5% |
| Quintile monotonicity | NOT monotonic | Monotonic |
| Long-Short Sharpe | 0.67 | ≥1.0 |
