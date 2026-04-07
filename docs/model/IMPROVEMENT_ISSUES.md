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

**D. Fix validation set construction** ⚠ TESTED AND REVERTED

Multi-regime val (last 25% of each year) improved IC IR (0.83→1.23) but increased Beta (0.44→0.61) and Down Capture (0.22→0.45). 2022 bear year result degraded -4%→-13%. Model learned market-correlated signals from Q4 seasonal patterns. Reverted.

**E. IC-based early stopping** ⚠ PARTIALLY IMPLEMENTED

Root cause: early stopping watched **Huber loss** but we care about **IC (rank correlation)**. These diverge — Huber minimum ≠ IC maximum, so the model stopped at the wrong point.

Attempted: remove Huber metric, use IC as sole early stopping metric via `feval`.
Result: IC spikes at iter 1-5 (model captures strong cross-sectional signal in first tree), then crashes. IC early stopping fires at best_iter=1, producing degenerate 1-tree models. Even worse than original.

**Current approach: Huber for early stopping (stable) + IC logged via feval (diagnostic).** `first_metric_only=True` ensures early stopping only watches Huber. IC is visible in the log for monitoring but doesn't drive stopping. Training objective stays Huber.

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

Categories likely absent from current 34 features:

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

With 34 features, `feature_frac=0.4` means each tree sees ~14 features. If features are correlated, the model repeatedly hits the same signal. At 0.65 (~23 features/tree), coverage improves.

---

## What NOT to Do

| Temptation | Why to Avoid |
|---|---|
| Switch model type (LightGBM → XGBoost / NN) | Architecture is not the bottleneck |
| Add more raw data | 1M+ rows is already sufficient |
| Tune LR / estimators before fixing capacity | LR only matters once trees are expressive enough |
| Add correlated feature variants | Redundancy worsens, not improves, quintile spread |
| `constituent_index_count` + `sector_breadth_21d` + `sector_constituent_share` | **Confirmed lookahead bias** — `index_constituents` DB stored current snapshot back-filled to all history. Removed 2026-04-07. See `docs/AUDIT.md` ISSUE 9 |
| Signal-proportional weighting (`--weighting signal`) | Higher total return but worse Sharpe/Calmar/MaxDD vs equal-weight; IC=0.06 too weak to justify concentration risk |
| Risk-adjusted weighting (`--weighting signal_vol`) | Strictly dominated: Sharpe 1.34→1.21, Calmar 1.54→1.07. Low-vol stocks overweighted → capital concentration in low-conviction names |
| Composite multi-horizon target (0.4×21d+0.4×42d+0.2×63d) | Sharpe 1.34→1.12, quintile unchanged. Mid-quintile noise increases from horizon mismatch. Quintile problem is alpha breadth, not label noise |

---

## Action Plan

### Phase 1 — Model Capacity (TESTED AND REVERTED)

Attempted: `num_leaves` 7→31, `max_depth` 3→6, `min_data_in_leaf` 1500→500, `lambda_l2` 1.0→3.0, `min_n_estimators=200` floor.

**Result: Reverted.** Capacity increase inflated train IC (0.13–0.28 → 0.28–0.43) without proportional OOS improvement. Sharpe degraded 1.30→1.15, Calmar 1.50→1.15, Max DD worsened. The near-null model warnings in 2019/2021 (best_iter=15/23) are caused by **validation set regime mismatch**, not insufficient capacity — those folds performed fine OOS (+11.99%, +41.07%). No further capacity tuning recommended until Fix D is implemented.

**Real fix: Fix D — validation set construction (implemented, see below).**

### Phase 2 — Target Improvement ⚠ TESTED AND REVERTED

Attempted: composite multi-horizon target `0.4*rank_21d + 0.4*rank_42d + 0.2*rank_63d`.

**Result: Reverted.** Quintile monotonicity did NOT improve (still NOT MONOTONIC). Overall performance degraded: Sharpe 1.04→~0.9 (clean baseline), Total Return 310%→246%, Alpha +99%→+35%, Hit Rate 52%→~48%. Mixing 21d/63d signals into a 42d portfolio adds noise to mid-quintile discrimination rather than reducing it. Root cause of quintile breakage is **alpha diversity**, not label noise — target blending does not address this.

### Phase 3 — Feature Audit + Diversity
- [x] Run SHAP/gain importance audit on current 34 features (post-lookahead removal)
  - Top 5 features = 43.2% gain (acceptable concentration)
  - Redundancy: ROE+sector_zscore_ROE and GPA+sector_zscore_GPA are duplicate signals (26.4% combined)
  - 13 momentum variants = 21.9% gain, fragmented
  - Dead feature: `sector_zscore_volume_ratio_21d` = 0.0% gain
  - Missing: earnings quality, earnings surprise, analyst revision
- [x] Add earnings quality features (`accrual_ratio`, `cfo_to_ni`) — ⚠ TESTED TWICE, BOTH REVERTED
  - v1: `fillna(0.0)` → artificial binary split → best_iter=1 in 2021 fold, Sharpe 1.08
  - v2: sector-date median fill (correct imputation) → same best_iter=1 in 2021 fold, Long-Short Sharpe 0.67→0.40, Sharpe 1.30→1.04. Reverted.
  - Root cause: earnings quality is **regime-conditional**. During COVID recovery (2020 val set), cash-burning cyclicals outperform — opposite of signal direction. Requires regime conditioning, which is incompatible with current training design. Do not attempt again without regime-aware architecture.
- [x] Check DB for analyst revision / SUE data — **not available** (DB is DART only, no consensus estimates)
- [x] Add YoY quarterly earnings growth (`earnings_growth_yoy`) from DART quarterly filings ✅ CONFIRMED WORKING
  - Derived via YTD subtraction (Q2 standalone = H1 YTD − Q1 YTD, etc.)
  - PIT-safe via available_date, staleness guard >150 days
  - Sector-date median fill for missing periods
  - Coverage: 2016+, ~1,800–2,700 stocks/quarter (sufficient for 200B universe)
  - Result (vs contaminated baseline): Sharpe 1.30→1.34, Calmar 1.50→1.54, Hit Rate 56%→66%, Long-Short Sharpe 0.67→0.77, 5/5 stat tests pass
  - Result (vs clean baseline, post lookahead removal, universe_cap benchmark): Sharpe 0.96, Calmar 0.82, Long-Short Sharpe 0.38 — positive incremental signal confirmed
  - Key: 2021 fold +7.64%→+47.33% (captured post-COVID earnings acceleration, no regime-inversion problem)
- [x] Re-run backtest, compare quintile spread vs baseline — **quintile remains NOT MONOTONIC** (Q1:+2.68% Q2:+3.16% Q3:+2.60% Q4:+3.21% Q5:+3.38%). Spread unchanged. Root cause is alpha breadth (independent signals), not fixable via target/model changes alone.

**Status:** No further improvements available with current DB.

---

## Success Metrics

| Metric | Current | Target |
|---|---|---|
| Worst fold best_iter | 1 (2019) | ≥200 across all folds |
| IC ratio worst fold | 0.19 (2018) | ≥0.40 across all folds |
| Q1→Q5 spread | ~0.7% | ≥1.5% |
| Quintile monotonicity | NOT monotonic | Monotonic |
| Long-Short Sharpe | **0.38** (clean, universe_cap) | ≥1.0 |
| Portfolio Sharpe | **0.96** (clean, universe_cap) | ≥1.0 |
