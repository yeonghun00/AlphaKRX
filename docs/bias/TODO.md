# Bias Investigation TODO

Remaining bias risks that have not been fully resolved. Ordered by estimated impact.

---

## 🔴 High Priority

### B1. Hyperparameter Selection Bias
**Risk:** Model hyperparameters (num_leaves=7, lr=0.005, min_data_in_leaf=1500, feature_frac=0.4, time_decay=0.2) were chosen through iterative experimentation that involved looking at backtest results across all folds. The reported Sharpe is measured on data that informed the parameter choices.

**Why it matters:** True OOS performance is likely lower than reported. The gap is unknown but real.

**How to check:**
- Fix all hyperparameters blindly before the backtest period and re-run
- Or: reserve the last 2 years (2025–2026) as a completely untouched holdout and never use them during development

**Status:** ⚠️ No fix in place. Structural limit of iterative development.

---

### B2. Feature Selection Bias (Data Snooping)
**Risk:** The 34 surviving features are the result of many rounds of "try a feature, see the backtest, keep or revert." Features that hurt performance were removed; features that helped (or were neutral) stayed. The model has been implicitly fit to the historical data through feature curation.

**Why it matters:** Some of the surviving features may have worked in-sample by chance, not by signal. Expected to degrade live.

**How to check:**
- Compare feature importance stability across folds — features that only contribute in certain years are regime-specific, not general
- Run a permutation test on each surviving feature (already done for `constituent_index_count`; extend to all 34)

**Status:** ⚠️ Partial. SHAP/gain audit done (see IMPROVEMENT_ISSUES.md Phase 3). Permutation test only done for the confirmed lookahead feature.

---

## 🟡 Medium Priority

### B3. Sector Label PIT Approximation
**Risk:** Sector labels come from `financial_periods.industry_name` joined via `merge_asof` on `available_date`. If a company was reclassified (e.g. from Manufacturing → IT), the backtest uses the new sector label for all historical dates before the reclassification was disclosed.

**Why it matters:** Sector neutralization and sector z-score features are affected. A stock scored as IT in 2018 (when it was actually Manufacturing) gets wrong sector z-scores.

**How to check:**
- Query `financial_periods` for stocks that changed `industry_name` across multiple filings
- Check how many stocks had sector changes and how early folds are affected

**Status:** ⚠️ Documented as data limit. No fix without a true historical sector classification time series.

---

### B4. Down Capture 0.20 Needs Live Validation
**Risk:** Down Capture of 0.20 is very low even after removing the confirmed lookahead features. It may reflect: (a) genuine market-neutrality from residualizing the target, (b) residual subtle bias, or (c) the specific benchmark (universe_cap dominated by large-cap names that fell hard in bear years).

**How to check:**
- Run with `--benchmark kospi200` and compare Down Capture — if it's also ~0.20, suggests genuine neutrality
- Once 2–3 live rebalances occur in a down market, compare actual drawdown to backtest prediction

**Status:** ⚠️ Unverified. Needs live confirmation.

---

### B5. Transaction Cost Underestimation
**Risk:** `buy=0.05%, sell=0.25%` is a fixed-rate model. Real costs for mid-cap Korean stocks include:
- Market impact (moving the price when entering/exiting)
- Bid-ask spread (especially on low-volume days)
- Tax: 0.20% securities transaction tax on sells (already partially in the 0.25%)

For a 100M KRW portfolio in stocks with 3–5B KRW daily volume, impact is small. But if AUM grows, costs grow non-linearly.

**How to check:**
- Re-run backtest with `--sell-fee 0.50%` and compare Sharpe
- Track actual fill prices in live trading vs closing price

**Status:** ⚠️ Unverified. Current model is reasonable for stated AUM (~100M KRW).

---

## 🟢 Low Priority (Acknowledged, Not Actionable)

### B6. 2019 Fold Degenerate (best_iter=1)
The 2019 fold produced a near-null model (best_iter=1 due to validation set regime mismatch: val=H2 2018 bear, test=2019 bull). The +10.10% OOS return for 2019 may be noise rather than signal. No fix without redesigning validation set construction (already tested and reverted — see IMPROVEMENT_ISSUES.md Fix D).

### B7. Pre-2016 Financial Data Sparsity
`earnings_growth_yoy` and other fundamental features have limited coverage before 2016. The 2018 fold (trained on 2015–2017) has weaker fundamental signal. Results in early folds are more price-momentum driven than the model intends. Not fixable without older DART data.

### B8. Long-Duration Trading Halt Forward Returns
Documented in DATA.md Fix B. Affects <0.1% of training rows. Accepted.

---

*Last updated: 2026-04-07*
