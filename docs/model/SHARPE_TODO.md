# Sharpe Ratio Improvement TODO

**Baseline (2026-04-17):** Sharpe 0.96 | Long-Short Sharpe 0.38 | Quintile NOT monotonic (Q3 > Q4)  
**Target:** Sharpe ≥ 1.10 | Long-Short Sharpe ≥ 0.60 | Quintile monotonic

---

## Final Backtest Results (2026-04-18) ✅
Active changes: SWA + two-stage re-ranking + accrual_regime_aware (inv-vol reverted)

| Metric | Baseline | Result | Status |
|---|---|---|---|
| Sharpe | 0.96 | **1.13** | ✅ target ≥1.10 met |
| Long-Short Sharpe | 0.38 | **0.65** | ✅ target ≥0.60 met |
| Total Return | 310% | **407%** | ✅ |
| Alpha | +77.85% | **+124.18%** | ✅ |
| Calmar | 0.82 | **0.90** | ✅ |
| Max Drawdown | -20.66% | **-21.87%** | ✅ held |
| Beta | 0.40 | **0.42** | ✅ held |
| Down Capture | 0.20 | **0.22** | ✅ held |
| IC Mean | 0.0557 | **0.0626** | ✅ |
| IC IR | 0.77 | **0.86** | ✅ |
| Stat sig at 1% | 3/5 | **4/5** | ✅ |
| Quintile | NOT monotonic | **MONOTONIC** | ✅ |

**accrual_regime_aware** at 1.84% importance — alive and contributing.

**Investigation log:**
- All-4-changes run: beta spiked 0.40→0.47, down capture 0.20→0.38
- Isolation test (no two-stage): beta 0.47→0.48 — confirmed inv-vol was the culprit, not re-ranking
- Reverted inv-vol only → all metrics recovered and exceeded targets

---

## Status Legend
- `[done]` — implemented, backtest-confirmed
- `[reverted]` — implemented, then rolled back with reason
- `[todo]` — planned, not yet implemented
- `[blocked]` — needs prerequisite or data check first
- `[skip]` — ruled out (see reason)

---

## Phase 1 — Noise Reduction (Low Risk)

### [done] SWA: Stochastic Weight Averaging in predict()
**File:** `ml/models/lgbm.py` — `predict()` method  
**What:** Instead of using a single `best_iteration` checkpoint, average predictions from three points along the gradient path: `[max(1, n-50), n, min(num_trees, n+50)]`.  
**Why:** Degenerate folds (best_iter=15 in 2019, best_iter=23 in 2021) perform fine OOS but may have noisy single-point predictions. SWA smooths this without requiring a hard iteration floor or changing the training procedure.  
**LightGBM API verified:** `num_trees()` (not `boosted_round()`), `best_iteration` is 1-indexed in LightGBM 4.6.0.  
**Expected impact:** Stabilizes Q3/Q4 ordering in degenerate folds. Minor Sharpe lift (+0.02–0.05).

```python
# In predict(swa=True):
iters = sorted({max(1, n - 50), n, min(total, n + 50)})
return np.mean([self.model.predict(X, num_iteration=i) for i in iters], axis=0)
```

**Backtest command:** `python3 scripts/run_backtest.py --output phase1_swa`  
**Monitor:** best_iter per fold, quintile monotonicity

---

### [reverted] Inverse-Vol Sample Weighting
**File:** `scripts/run_backtest.py` — `_run_fold()`, before `model.train()`  
**What:** Weight training samples by `1 / (1 + vol / median_vol)`, clipped at lower=0.20. Reduces gradient contribution of high-volatility crisis periods (2020 crash) without erasing them.  
**Why:** 2020 COVID crash volatility is 4–5× normal. Without downweighting, gradient steps during crash data "scream" louder than 10 years of normal trading, causing beta leakage and regime-specific overfitting.  
**Formula math:**
- Normal vol (1× median) → weight ≈ 0.50
- Crisis vol (4× median) → weight ≈ 0.20 (floor, not zero — model still learns crisis behavior)
- Calm vol (0.1× median) → weight ≈ 0.91 (max ~1.0, upper clip not needed)

```python
vol = sub_train["volatility_21d"].fillna(median).clip(lower=1e-6)
raw_w = 1.0 / (1.0 + vol / vol.median())
raw_w = raw_w.clip(lower=0.20)   # keep upper clip off — formula max is ~1.0
vol_weight = (raw_w / raw_w.mean()).to_numpy()
model.train(sub_train, val_df, params=params, sample_weight=vol_weight)
```

**Backtest command:** `python3 scripts/run_backtest.py --output phase1_swa_invvol`  
**Monitor:** overall beta (target: 0.44 → ~0.35), down_capture, 2021 fold alpha

**REVERTED (2026-04-18):** Isolation test (all-4-changes vs no-two-stage) showed beta 0.47→0.48 when two-stage removed — confirming inv-vol is the beta culprit, not re-ranking. Root cause: downweighting 2020 crash removes the period where the model learned to avoid high-beta stocks in downturns. Beta went 0.40→0.48, Down Capture 0.20→0.42. The theoretical benefit (less regime noise) was outweighed by losing defensive signal.

---

## Phase 2 — Signal Architecture (Medium Risk)

### [done] Two-Stage Market-Type Re-Ranking
**File:** `scripts/run_backtest.py` — scoring block after `model.predict()` (~line 284)  
**What:** After scoring all stocks, re-rank scores separately within `market_type` groups (`kospi`, `kosdaq`) using `groupby("market_type").rank(pct=True)`. Portfolio picks the best 20% of each market type rather than comparing across them.  
**Why:**
- A top-ROE KOSPI conglomerate (Samsung SDI, SK Hynix) is driven by global macro and semiconductor cycles
- A top-ROE KOSDAQ stock may be a cyclical equipment maker or a retail-driven theme play
- Ranking them together puts structurally different return drivers in the same quintile → Q3/Q4 inversion
- `market_type` is already loaded in the pipeline (`daily_prices.market_type ∈ {kospi, kosdaq, kodex}`)

```python
# After existing sector_neutral_score block:
if "market_type" in day_df.columns and day_df["market_type"].nunique() > 1:
    day_df["score_rank"] = day_df.groupby("market_type")["score_rank"].rank(
        method="first", pct=True
    )
```

**Backtest command:** `python3 scripts/run_backtest.py --output phase2_two_stage`  
**Monitor:** Long-Short Sharpe (target: 0.38 → 0.60+), quintile monotonicity, sector concentration

---

### [done] Regime-Aware Accruals Feature
**File:** `ml/features/earnings_quality.py` + registered in `ml/features/__init__.py`  
**Feature column:** `accrual_regime_aware` (35th feature, total now 35)  
**What:** Multiply accrual ratio by `sign(market_regime_120d)` to flip signal polarity based on market state.
- Bull/recovery regime: high accruals = quality red flag (short)
- Contraction regime: high accruals = restocking/demand signal (long)

**Why previous attempts failed:**
- v1 `fillna(0.0)` → artificial binary split → best_iter=1 in 2021 fold
- v2 sector-date median fill → same best_iter=1 in 2021 fold
- Root cause: 2020 val set (COVID bounce) has opposite signal direction vs rest of history — not a fill problem, but a regime-sign problem

**Why this version is different:** The flip is applied at feature level before training, not at model level. The model sees a feature that is already regime-corrected, so the gradient doesn't fight the sign reversal.

**Coverage confirmed:** `ifrs-full_CashFlowsFromUsedInOperatingActivities` — KOSDAQ 2052/2139 (~96%), KOSPI 913 stocks. No coverage issue; sector z-score normalization not needed.

**Smoke test passed:** Zero NaNs, bounded [-3, 3], regime flip verified:
- High-accrual stocks in bull: mean score = +0.65 ✓
- High-accrual stocks in bear: mean score = −0.61 ✓

**Backtest command:** `python3 scripts/run_backtest.py --output phase2_all`  
**Monitor:** 2021 fold best_iter (should be > 50 with SWA), Long-Short Sharpe, down_capture

---

## Phase 3 — Structural (Higher Complexity)

### [todo] Dual-Model KOSPI/KOSDAQ Training
**What:** If two-stage re-ranking (Phase 2) improves Long-Short Sharpe to 0.55+, the next step is training two separate LGBMRanker instances — one on KOSPI universe, one on KOSDAQ — and combining their scores at percentile scale.  
**Why:** Re-ranking fixes the comparison problem but both models still share the same learned weights. Separate models can learn KOSPI-specific factors (macro sensitivity, book value) vs KOSDAQ-specific factors (earnings acceleration, retail momentum).  
**Complexity:** ~150 lines, requires pipeline changes to split feature df by market_type before training.  
**Prerequisite:** Phase 2 two-stage re-ranking confirmed working.

---

## What NOT to Retry

| Approach | Why It Failed | Status |
|---|---|---|
| Model capacity increase (num_leaves 7→31) | Train IC inflated, OOS Sharpe degraded 1.30→1.15 | Reverted |
| Multi-horizon composite target (0.4×21d+0.4×42d+0.2×63d) | Sharpe 0.96→0.90, quintile unchanged, mid-quintile noise increased | Reverted |
| Multi-regime validation (last 25% each year) | Beta 0.44→0.61, Down Capture 0.22→0.45, 2022 bear -4%→-13% | Reverted |
| CPCV validation blocks | Same structural failure as multi-regime val — Q4 seasonal leakage | Do not attempt |
| Raw earnings quality (accruals, CFO/NI) | best_iter=1 in 2021 fold both attempts, Long-Short 0.67→0.40 | Reverted (retry only with regime-flip) |
| Signal-proportional weighting | Higher return but worse Sharpe/Calmar/MaxDD | Reverted |
| Risk-adjusted vol weighting (--weighting signal_vol) | Strictly dominated: Sharpe 1.34→1.21 | Reverted |
| 5-day reversal at 42-day rebalance | Signal decays in 48–72h, stale at rebalance time | Skip |
| Inverse-vol sample weighting | Removed 2020 crash data → model lost defensive signal → beta 0.40→0.48, down capture 0.20→0.42 | Reverted |

---

## Success Metrics

| Metric | Baseline | Target | Final | Status |
|---|---|---|---|---|
| Portfolio Sharpe | 0.96 | ≥ 1.10 | **1.13** | ✅ |
| Long-Short Sharpe | 0.38 | ≥ 0.60 | **0.65** | ✅ |
| Quintile monotonic | No (Q3>Q4) | Yes | **Yes** | ✅ |
| Overall beta | 0.40 | ≤ 0.42 | **0.42** | ✅ |
| Down capture | 0.20 | ≤ 0.25 | **0.22** | ✅ |
| Worst-fold best_iter | 15 (2019) | ≥ 50 | **2 (2019)** | ❌ still degenerate |
