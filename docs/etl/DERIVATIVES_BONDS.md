# Derivatives & Bonds Schema

Market volatility, futures, and fixed income data. Used as macro regime features in the model.

**ETL source:** `etl/index_etl.py` — KRX API endpoints:
- Derivatives: `drvprod_dd_trd`
- Bond indices: `bon_dd_trd`
- Government bonds: `kts_bydd_trd`

---

## Derivatives Tables

### `deriv_indices` — Derivatives Index Master

**Primary key:** `index_code`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `index_code` | TEXT | NO | Unique identifier |
| `current_name` | TEXT | NO | Index name (Korean) |
| `index_class` | TEXT | YES | Category (`선물지수`, `옵션지수`, `전략지수`, `상품지수`) |
| `is_active` | BOOLEAN | NO | Currently published |
| `updated_at` | TIMESTAMP | NO | Last update |

**Tracked index codes (sample):**

| `index_code` | Name | Notes |
|---|---|---|
| `DERIV_선물지수_코스피_200_선물지수` | KOSPI 200 Futures Index | Equity futures |
| `DERIV_선물지수_미국달러선물지수` | USD Futures Index | FX futures |
| `DERIV_선물지수_국채선물지수` | Government Bond Futures | Rate futures |
| `DERIV_전략지수_코스피_200_변동성지수` | **VKOSPI** (Volatility Index) | **Used in model** |
| `DERIV_선물지수_엔선물지수` | JPY Futures Index | FX futures |
| `DERIV_선물지수_유로선물지수` | EUR Futures Index | FX futures |

---

### `deriv_index_daily` — Derivatives Index Daily Data

**Primary key:** `(index_code, date)`
**Rows:** 418,617
**Date range:** 2010-01-04 → 2026-03-20

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `index_code` | TEXT | NO | References `deriv_indices.index_code` |
| `date` | TEXT | NO | Trading date (YYYYMMDD) |
| `closing_index` | REAL | YES | Closing index value |
| `change` | REAL | YES | Point change |
| `change_rate` | REAL | YES | % change |
| `opening_index` | REAL | YES | Opening value |
| `high_index` | REAL | YES | Intraday high |
| `low_index` | REAL | YES | Intraday low |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

**How VKOSPI is used in the model (`_pipeline.py` — `_load_macro_regime()`):**

```python
# Load VKOSPI (Korea Volatility Index, analogous to VIX)
vkos = deriv[deriv["index_code"] == "DERIV_전략지수_코스피_200_변동성지수"]["closing_index"]

# Compute rolling 252-day percentile rank (0 = lowest vol in past year, 1 = highest)
def pct_norm(s, window=252):
    return s.rolling(window, min_periods=60).rank(pct=True)

macro["vkospi_level_pct"] = pct_norm(vkos)
```

**Cash-out rule trigger:**
```python
if vkospi_level_pct > 0.80:   # fear in top 20% of past year
    cash_weight += 0.50        # additional 50% to cash
```

**Missing data handling:** If VKOSPI data is missing for a date, `vkospi_level_pct` is filled with `0.5` (neutral). This means the fear signal is neutralised for any date with missing VKOSPI. Pre-2010 or data gap periods will silently behave as if volatility is normal.

**Verification:**
```sql
-- Check VKOSPI data coverage
SELECT MIN(date), MAX(date), COUNT(*)
FROM deriv_index_daily
WHERE index_code = 'DERIV_전략지수_코스피_200_변동성지수';

-- Sample recent VKOSPI values (should be 10-40 range)
SELECT date, closing_index AS vkospi
FROM deriv_index_daily
WHERE index_code = 'DERIV_전략지수_코스피_200_변동성지수'
ORDER BY date DESC LIMIT 10;
```

---

## Bond Index Tables

### `bond_indices` — Bond Index Master

**Primary key:** `index_code`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `index_code` | TEXT | NO | Unique identifier |
| `current_name` | TEXT | NO | Index name (Korean) |
| `is_active` | BOOLEAN | NO | Currently published |
| `updated_at` | TIMESTAMP | NO | Last update |

**Tracked indices:**
- `BOND_KRX_채권지수` — KRX Bond Index (broad)
- `BOND_KTB_지수` — Korea Treasury Bond Index
- `BOND_국고채프라임지수` — Government Bond Prime Index

---

### `bond_index_daily` — Bond Index Daily Data

**Primary key:** `(index_code, date)`
**Rows:** 5,898
**Date range:** 2010-02-15 → 2026-03-20

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `index_code` | TEXT | NO | References `bond_indices.index_code` |
| `date` | TEXT | NO | Trading date (YYYYMMDD) |
| `total_return_index` | REAL | YES | Total return (price + coupon reinvested) |
| `total_return_change` | REAL | YES | Daily change in total return index |
| `net_price_index` | REAL | YES | Clean price index (excludes accrued interest) |
| `net_price_change` | REAL | YES | Daily change |
| `zero_reinvest_index` | REAL | YES | Zero-coupon reinvestment index |
| `zero_reinvest_change` | REAL | YES | Daily change |
| `call_reinvest_index` | REAL | YES | Call-rate reinvestment index |
| `call_reinvest_change` | REAL | YES | Daily change |
| `market_price_index` | REAL | YES | Dirty price index (includes accrued) |
| `market_price_change` | REAL | YES | Daily change |
| `avg_duration` | REAL | YES | Portfolio weighted average duration |
| `avg_convexity` | REAL | YES | Portfolio weighted average convexity |
| `avg_yield` | REAL | YES | Portfolio weighted average yield (%) |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

**Current usage:** Bond index data is stored but **not currently used** as a model feature. It is available for future macro features (yield level, credit spread, duration risk premium).

---

## Government Bond Tables

### `govt_bonds` — Government Bond Issue Master

**Primary key:** `issue_code`
**Rows:** 372 distinct bond issues

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `issue_code` | TEXT | NO | Unique bond issue code |
| `current_name` | TEXT | NO | Bond name |
| `market_name` | TEXT | YES | Market segment |
| `maturity_type` | TEXT | YES | Tenor: `1`, `2`, `3`, `5`, `10`, `20`, `30` (years) |
| `issue_type` | TEXT | YES | Bond type (e.g. government, monetary stabilisation) |
| `is_active` | BOOLEAN | NO | Currently trading |
| `updated_at` | TIMESTAMP | NO | Last update |

---

### `govt_bond_daily` — Government Bond Daily Prices & Yields

**Primary key:** `(issue_code, date)`
**Rows:** 30,515
**Date range:** 2010-01-04 → 2026-03-20

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `issue_code` | TEXT | NO | References `govt_bonds.issue_code` |
| `date` | TEXT | NO | Trading date (YYYYMMDD) |
| `closing_price` | REAL | YES | Clean price (face value = 100) |
| `price_change` | REAL | YES | Daily price change |
| `closing_yield` | REAL | YES | Yield to maturity at close (%) |
| `opening_price` | REAL | YES | Opening clean price |
| `opening_yield` | REAL | YES | Opening yield |
| `high_price` | REAL | YES | Intraday high price |
| `high_yield` | REAL | YES | Yield at intraday high |
| `low_price` | REAL | YES | Intraday low price |
| `low_yield` | REAL | YES | Yield at intraday low |
| `trading_volume` | INTEGER | YES | Contracts traded |
| `trading_value` | INTEGER | YES | Value traded (KRW) |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

---

### `govt_bond_history` — Bond Issue Name/Type Changes

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | Auto-increment PK |
| `issue_code` | TEXT | NO | References `govt_bonds.issue_code` |
| `effective_date` | TEXT | NO | Date of change |
| `name` | TEXT | YES | Bond name at that date |
| `market_name` | TEXT | YES | Market segment at that date |
| `maturity_type` | TEXT | YES | Tenor at that date |
| `issue_type` | TEXT | YES | Bond type at that date |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

**Current usage:** Government bond data is stored but **not currently used** as a model feature. Available for future use: yield curve slope (10Y - 3Y spread), rate level regime, credit risk premium.

---

## Macro Feature Pipeline Summary

Of all the derivatives and bond tables, only `deriv_index_daily` is actively used:

```
deriv_index_daily (VKOSPI)
    │
    ▼ _load_macro_regime()

vkospi_level_pct = rolling_252d_percentile(VKOSPI closing_index)
                                                   │
                                                   ▼
                                         macro_regime DataFrame
                                                   │
                                            merged onto data
                                         (left join on date)
                                                   │
                                         NaN filled with 0.5
```

**Potential future features from stored data:**
- `bond_index_daily.avg_yield` → interest rate level regime
- `govt_bond_daily.closing_yield` → yield curve slope (10Y - 3Y)
- `bond_index_daily.total_return_index` → bond vs equity relative performance signal
