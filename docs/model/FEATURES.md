# Feature Reference

36 features across 9 groups. All computed in `ml/features/` and registered via `@register`.

See [MODEL.md](MODEL.md) for how the feature registry works and how to add new features.


---

## Momentum (4)

| Feature | What it measures |
|---------|-----------------|
| `mom_5d` | 5-day price return |
| `mom_21d` | 1-month price return |
| `mom_63d` | 3-month price return |
| `mom_126d` | 6-month price return |

---

## Volume & Liquidity (3)

| Feature | What it measures |
|---------|-----------------|
| `volume_ratio_21d` | Today's volume / 21-day average volume |
| `turnover_21d` | 21-day average traded value / market cap |
| `amihud_21d` | 21-day average of \|return\| / value (price impact proxy) |

---

## Volatility & Risk (4)

| Feature | What it measures |
|---------|-----------------|
| `volatility_21d` | Std dev of daily returns over 21 days |
| `volatility_63d` | Std dev of daily returns over 63 days |
| `drawdown_252d` | Current price / 252-day rolling high - 1 |
| `rolling_beta_60d` | 60-day rolling beta vs KOSPI 200 |

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

---

## Market Context (2)

| Feature | What it measures |
|---------|-----------------|
| `market_regime_120d` | KOSPI 200 current / 120-day MA - 1 |
| `constituent_index_count` | Number of KRX indices the stock belongs to |

---

## Sector (7)

| Feature | What it measures |
|---------|-----------------|
| `sector_momentum_21d` | 21-day return of the stock's sector index |
| `sector_momentum_63d` | 63-day return of the stock's sector index |
| `sector_relative_momentum_20d` | Sector 20d return minus KOSPI 20d return |
| `sector_relative_momentum_21d` | Sector 21d return minus KOSPI 21d return |
| `sector_relative_momentum_63d` | Sector 63d return minus KOSPI 63d return |
| `sector_breadth_21d` | % of sector constituents with positive 21d momentum |
| `sector_constituent_share` | Relative size of sector |

---

## Sector-Neutralized (4)

Z-score each feature within its sector group. Removes sector-level effects so the model ranks within-sector.

| Feature | Underlying raw feature |
|---------|----------------------|
| `sector_zscore_mom_21d` | `mom_21d` |
| `sector_zscore_turnover_21d` | `turnover_21d` |
| `sector_zscore_volatility_21d` | `volatility_21d` |
| `sector_zscore_drawdown_252d` | `drawdown_252d` |

---

## Distress Detection (5)

| Feature | What it measures |
|---------|-----------------|
| `liquidity_decay_score` | 20-day avg value / 252-day avg value |
| `low_price_trap` | log(price / sector avg price) |
| `is_liquidity_distressed` | Binary: `liquidity_decay_score <= 0.2` |
| `is_low_price_trap` | Binary: price < 1000 or `low_price_trap < -1.0` |
| `distress_composite_score` | Weighted combination (0–1 scale) |

---

## Sector Rotation (3)

| Feature | What it measures |
|---------|-----------------|
| `sector_dispersion` | Cross-sectional std dev within sector |
| `sector_dispersion_21d` | 21-day smoothed sector dispersion |
| `sector_rotation_signal` | Positive when sector has good momentum AND low dispersion |

---

## Feature Implementation Map

| Group file | Features |
|-----------|----------|
| `ml/features/momentum.py` | `mom_5d`, `mom_21d`, `mom_63d`, `mom_126d` |
| `ml/features/volume.py` | `volume_ratio_21d`, `turnover_21d`, `amihud_21d` |
| `ml/features/volatility.py` | `volatility_21d`, `volatility_63d`, `drawdown_252d`, `rolling_beta_60d` |
| `ml/features/fundamental.py` | `roe`, `gpa`, `sector_zscore_roe`, `sector_zscore_gpa` |
| `ml/features/market.py` | `market_regime_120d`, `constituent_index_count` |
| `ml/features/sector.py` | sector momentum/breadth/share (7) |
| `ml/features/sector_neutral.py` | sector z-scores (4) |
| `ml/features/distress.py` | distress scores (5) |
| `ml/features/sector_rotation.py` | rotation signal (3) |
