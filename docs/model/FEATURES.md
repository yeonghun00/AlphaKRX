# Feature Reference

34 features across 13 registered groups (2 groups produce intermediate outputs only, not model features). All computed in `ml/features/` and registered via `@register`.

> **⚠️ Important:** All features must have ≥70% coverage. Low-coverage features cause row loss via `dropna()`. See [MODEL.md](MODEL.md#coverage-rule-critical) for details.

Note: raw momentum columns (`mom_5d`, `mom_21d`, etc.) are **intermediates** — computed but not passed to the model directly. The model uses their sector-neutral versions (`sector_zscore_mom_*`) instead.

See [MODEL.md](MODEL.md) for how the feature registry works and how to add new features.

---

## Academic Momentum (4)

| Feature | What it measures |
|---------|-----------------|
| `high_52w_proximity` | Current price / 52-week high |
| `ma_ratio_20_120` | 20-day MA / 120-day MA |
| `ma_ratio_5_60` | 5-day MA / 60-day MA |
| `momentum_quality` | Consistency of momentum across lookback windows |

---

## Volume & Liquidity (2)

| Feature | What it measures |
|---------|-----------------|
| `volume_ratio_21d` | Today's volume / 21-day average volume |
| `amihud_21d` | 21-day average of \|return\| / value (price impact proxy) |

Note: `turnover_21d` is an intermediate used by sector-neutral features, not a direct model feature.

---

## Volatility & Risk (1)

| Feature | What it measures |
|---------|-----------------|
| `rolling_beta_60d` | 60-day rolling beta vs KOSPI 200 |

Note: `volatility_21d`, `volatility_63d`, and `drawdown_252d` are intermediates used by sector-neutral features.

---

## Fundamental (4, PIT-safe)

| Feature | What it measures |
|---------|-----------------|
| `roe` | Net income / equity |
| `gpa` | Gross profit / assets (Novy-Marx profitability factor) |
| `sector_zscore_roe` | ROE z-scored within sector |
| `sector_zscore_gpa` | GPA z-scored within sector |

Financial data is PIT-safe: only used after `available_date` in `financial_periods`.
See [../bias/DATA.md](../bias/DATA.md) for the 45/90-day disclosure rule.

> **Coverage Note:** All fundamental features require financial statement data which may not exist for all stocks. Current coverage is ~100% for ROE/GPA (imputed from sector median). When adding new financial features, verify coverage ≥70% before adding to `FEATURE_COLUMNS`.

> **⚠ Attempted and reverted twice — `accrual_ratio` / `cfo_to_ni`:**
> - **v1 (fillna=0.0):** Conflated missing/negative NI with "zero accruals" → artificial binary split → best_iter=1 in 2021 fold, Sharpe 1.08.
> - **v2 (sector-date median fill):** Correct imputation, but the core problem persists. During COVID recovery (2020, which is the val set for the 2021 fold), cash-burning/cyclical companies outperformed massively — the opposite of what earnings quality predicts. best_iter=1 recurred, Long-Short Sharpe degraded 0.67→0.40, Sharpe 1.30→1.04. Reverted.
> - **Root cause:** Earnings quality signal is regime-conditional. It requires regime-awareness to work in Korean markets (cyclicals and chaebol dominate COVID bounce). Not compatible with the current regime-agnostic training setup.

---

## Market Context (1)

| Feature | What it measures |
|---------|-----------------|
| `market_regime_120d` | KOSPI 200 current / 120-day MA - 1 |

> `constituent_index_count` — **REMOVED 2026-04-07 (lookahead bias).** See `docs/AUDIT.md` ISSUE 9 for full details.

---

## Sector (4)

| Feature | What it measures |
|---------|-----------------|
| `sector_momentum_21d` | 21-day return of the stock's sector index |
| `sector_momentum_63d` | 63-day return of the stock's sector index |
| `sector_relative_momentum_21d` | Sector 21d return minus KOSPI 21d return |
| `sector_relative_momentum_63d` | Sector 63d return minus KOSPI 63d return |

> `sector_breadth_21d` and `sector_constituent_share` — **REMOVED 2026-04-07 (lookahead bias, same root cause as `constituent_index_count`).** See `docs/AUDIT.md` ISSUE 9.

---

## Sector-Neutralized (9)

Z-score each feature within its sector group. Removes sector-level effects so the model ranks within-sector.

| Feature | Underlying raw feature |
|---------|----------------------|
| `sector_zscore_mom_5d` | `mom_5d` |
| `sector_zscore_mom_21d` | `mom_21d` |
| `sector_zscore_mom_63d` | `mom_63d` |
| `sector_zscore_mom_126d` | `mom_126d` |
| `sector_zscore_turnover_21d` | `turnover_21d` |
| `sector_zscore_volatility_21d` | `volatility_21d` |
| `sector_zscore_volatility_63d` | `volatility_63d` |
| `sector_zscore_drawdown_252d` | `drawdown_252d` |
| `sector_zscore_volume_ratio_21d` | `volume_ratio_21d` |

---

## Distress Detection (3)

| Feature | What it measures |
|---------|-----------------|
| `liquidity_decay_score` | 20-day avg value / 252-day avg value |
| `low_price_trap` | log(price / sector avg price) |
| `distress_composite_score` | Weighted combination (0–1 scale) |

Note: `is_liquidity_distressed` and `is_low_price_trap` are binary intermediate flags used to compute `distress_composite_score`, not direct model features.

---

## Sector Rotation (3)

| Feature | What it measures |
|---------|-----------------|
| `sector_dispersion` | Cross-sectional std dev within sector |
| `sector_dispersion_21d` | 21-day smoothed sector dispersion |
| `sector_rotation_signal` | Positive when sector has good momentum AND low dispersion |

---

## Macro Interaction (2)

| Feature | What it measures |
|---------|-----------------|
| `conditional_momentum` | Momentum signal scaled by volatility regime (VKOSPI) |
| `value_regime_boost` | Value signal boosted in low-volatility regimes |

---

## Earnings Momentum (1, PIT-safe)

| Feature | What it measures |
|---------|-----------------|
| `earnings_growth_yoy` | YoY net income growth for the most recent fiscal quarter |

Derived from DART quarterly filings (Q1/H1/Q3/Annual). Korean filings are cumulative YTD — standalone quarterly NI is recovered by subtraction (e.g. Q2 standalone = H1 YTD − Q1 YTD). YoY growth = (current_Q − prior_year_Q) / |prior_year_Q|, clipped to [−3, 3].

**Coverage:** Quarterly data available from 2016 for ~1,800–2,700 stocks. Early folds (2018 test) have 2 years of quarterly history. Missing → sector-date median fill (neutral, not zero). Staleness guard: data >5 months old is treated as missing.

**Why this works:** Unlike earnings quality (accrual_ratio), earnings acceleration is not regime-inverted during COVID recovery — companies with accelerating earnings outperformed in both the crash and recovery phases.

---

## Feature Implementation Map

| Group file | Features |
|-----------|----------|
| `ml/features/momentum.py` | intermediates only (`mom_5d`, `mom_21d`, `mom_63d`, `mom_126d`, `ret_1d`) |
| `ml/features/momentum_academic.py` | `high_52w_proximity`, `ma_ratio_20_120`, `ma_ratio_5_60`, `momentum_quality` |
| `ml/features/volume.py` | `volume_ratio_21d`, `amihud_21d` |
| `ml/features/volatility.py` | `rolling_beta_60d` |
| `ml/features/fundamental.py` | `roe`, `gpa`, `sector_zscore_roe`, `sector_zscore_gpa` |
| `ml/features/market.py` | `market_regime_120d` |
| `ml/features/sector.py` | sector momentum (4) — breadth/share removed (lookahead) |
| `ml/features/sector_neutral.py` | sector z-scores (9) |
| `ml/features/distress.py` | distress scores (3) |
| `ml/features/sector_rotation.py` | rotation signal (3) |
| `ml/features/macro_interaction.py` | `conditional_momentum`, `value_regime_boost` |
| `ml/features/earnings_momentum.py` | `earnings_growth_yoy` |
