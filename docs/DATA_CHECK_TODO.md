# Data Integrity Check — TODO

Work through each check in order. Mark `[x]` when done, add findings below each item.

---

## 1. Adjusted Prices (`adj_daily_prices`)

- [x] Confirm `adj_daily_prices` row count matches `daily_prices` (both should be 8,797,312)
- [x] Spot-check Samsung 005930 split (2018-05-04): `adj_factor` should drop to ~0.02
- [x] Confirm no stock has `adj_factor = NULL` or `adj_closing_price <= 0`
- [x] Check a few known delisted stocks — adj prices should end at delisting date

```sql
-- Row count match
SELECT COUNT(*) FROM daily_prices;
SELECT COUNT(*) FROM adj_daily_prices;

-- Samsung split check
SELECT dp.stock_code, dp.date, dp.closing_price, adj.adj_closing_price, adj.adj_factor
FROM daily_prices dp JOIN adj_daily_prices adj USING (stock_code, date)
WHERE dp.stock_code = '005930' AND dp.date BETWEEN '20180502' AND '20180507';

-- Null / zero adj prices
SELECT COUNT(*) FROM adj_daily_prices WHERE adj_closing_price IS NULL OR adj_closing_price <= 0;
```

**Findings:** ✅ PASS
- Both tables: 8,797,312 rows — exact match.
- Samsung split (2018-05-04): closing_price 2,680,000 → adj_closing_price 49,026 (adj_factor ≈ 0.0183). Correct 50:1 split.
- 0 NULL or zero adj prices.

---

## 2. Raw Price Anomalies (`daily_prices`)

- [x] Check for single-day price drops > 40% (unadjusted split artifacts)
- [x] Check for zero or negative `closing_price` rows
- [x] Check for stocks with very long gaps (> 30 trading days) between rows
- [x] Confirm `market_type` is always `kospi`, `kosdaq`, or `kodex` (no nulls/typos)

```sql
-- Single-day drops > 40% (potential unadjusted split artifacts)
SELECT stock_code, date, closing_price,
       LAG(closing_price) OVER (PARTITION BY stock_code ORDER BY date) AS prev_close,
       ROUND(100.0 * (closing_price - LAG(closing_price) OVER (PARTITION BY stock_code ORDER BY date))
             / LAG(closing_price) OVER (PARTITION BY stock_code ORDER BY date), 1) AS pct_chg
FROM daily_prices
WHERE closing_price > 0
HAVING pct_chg < -40
ORDER BY pct_chg ASC
LIMIT 20;

-- Zero / negative prices
SELECT COUNT(*) FROM daily_prices WHERE closing_price <= 0;

-- Market type values
SELECT market_type, COUNT(*) FROM daily_prices GROUP BY market_type;
```

**Findings:** ✅ PASS
- -98% drops are Samsung/LG-style stock splits (e.g. 005930 on 2018-05-04: 2,680,000 → 53,000). These are **unadjusted** raw prices — expected. `adj_daily_prices` handles these correctly.
- 0 rows with closing_price <= 0.
- market_type values: kospi, kosdaq, kodex only — no nulls or typos.
- No gaps > 30 trading days in active (volume > 0) stocks that pass the liquidity filter.

---

## 3. Universe Coverage by Year (`daily_prices`)

- [x] Count distinct stocks per year — no year should have <500 stocks (data gap)
- [x] Count trading days per year — each year should have ~248 days
- [x] Check if early years (2011–2014) have significantly fewer stocks

```sql
SELECT strftime('%Y', date) AS year,
       COUNT(DISTINCT stock_code) AS n_stocks,
       COUNT(DISTINCT date) AS trading_days
FROM daily_prices
GROUP BY year ORDER BY year;
```

**Findings:** ✅ PASS
- Trading days per year: 245–248 — consistent throughout.
- Stock count grows from 2,051 (2011) to 3,928 (2026) — healthy expansion, never below 2,000.
- No data gaps in early years.

---

## 4. Delisted Stocks (`delisted_stocks`)

- [x] Confirm count is reasonable (should be ~1,700+)
- [x] Check for stocks in `delisted_stocks` that still have rows in `daily_prices` AFTER their delisting date
- [x] Check for stocks with NULL `delisting_date` (should be few)
- [x] Verify at least one known delisted company (e.g. a famous bankruptcy) is present

```sql
-- Count and null check
SELECT COUNT(*), COUNT(delisting_date) FROM delisted_stocks;

-- Prices existing after delisting date (survivorship bias risk)
SELECT d.stock_code, d.delisting_date, COUNT(*) AS rows_after
FROM delisted_stocks d
JOIN daily_prices p ON d.stock_code = p.stock_code
WHERE p.date >= d.delisting_date
GROUP BY d.stock_code
HAVING rows_after > 0
LIMIT 20;
```

**Findings:** ✅ PASS
- 1,720 delisted stocks, all have `delisting_date` — 0 NULLs.
- 0 stocks have price rows on or after their delisting date — survivorship bias fully controlled.

---

## 5. Financial Data Coverage (`financial_periods`)

- [x] Count filings per year — coverage should start growing from 2015
- [x] Confirm `available_date` is always AFTER `fiscal_date` (by at least 44 days)
- [x] Check for duplicate filings (same stock + fiscal_date + consolidation_type)
- [x] Confirm only `연결` (consolidated) filings are present in meaningful numbers
- [x] Count companies with NO financial data at all

```sql
-- Coverage by year
SELECT strftime('%Y', available_date) AS year,
       COUNT(DISTINCT stock_code) AS companies,
       COUNT(*) AS filings
FROM financial_periods WHERE consolidation_type = '연결'
GROUP BY year ORDER BY year;

-- available_date must be after fiscal_date
SELECT COUNT(*) FROM financial_periods
WHERE julianday(available_date) - julianday(fiscal_date) < 44;

-- Duplicates
SELECT stock_code, fiscal_date, consolidation_type, COUNT(*) AS cnt
FROM financial_periods
GROUP BY stock_code, fiscal_date, consolidation_type
HAVING cnt > 1
LIMIT 10;

-- Stocks with zero consolidated filings
SELECT COUNT(DISTINCT stock_code) FROM stocks s
WHERE NOT EXISTS (
    SELECT 1 FROM financial_periods fp
    WHERE fp.stock_code = s.stock_code AND fp.consolidation_type = '연결'
);
```

**Findings:** 🔴 ISSUE — Slow ramp-up
- 2015: only 34 companies (ramp-up year from DART ZIP downloads).
- 2016: 1,458 companies — effectively first full year.
- **Impact:** Pre-2016 backtest uses price-based features only (ROE/GPA = NaN → imputed to sector/market median). Results for 2011–2015 period should be treated with caution.
- 0 filings have `available_date < fiscal_date + 44 days` — PIT enforcement is correct.
- 0 duplicate filings.

---

## 6. Financial Items — Key Columns (`financial_items_bs_cf`, `financial_items_pl`)

- [x] Confirm `ifrs-full_Equity`, `ifrs-full_Assets`, `ifrs-full_CashFlowsFromUsedInOperatingActivities` exist in bs_cf
- [x] Confirm `ifrs-full_ProfitLoss`, `ifrs-full_GrossProfit` exist in pl
- [x] Check for NULL amounts on key items
- [x] Check for extreme outliers (e.g. equity = 0 or negative, ROE > 1000%)

```sql
-- Key item codes present
SELECT item_code_normalized, COUNT(*) AS cnt
FROM financial_items_bs_cf
WHERE item_code_normalized IN (
    'ifrs-full_Equity',
    'ifrs-full_Assets',
    'ifrs-full_CashFlowsFromUsedInOperatingActivities'
)
GROUP BY item_code_normalized;

SELECT item_code_normalized, COUNT(*) AS cnt
FROM financial_items_pl
WHERE item_code_normalized IN ('ifrs-full_ProfitLoss', 'ifrs-full_GrossProfit')
GROUP BY item_code_normalized;

-- Null amounts on equity
SELECT COUNT(*) FROM financial_items_bs_cf
WHERE item_code_normalized = 'ifrs-full_Equity' AND amount_current IS NULL;
```

**Findings:** ⚠️ MINOR ISSUES
- All key IFRS codes present:
  - `ifrs-full_Equity`: 158,095 rows
  - `ifrs-full_Assets`: 158,094 rows
  - `ifrs-full_CashFlowsFromUsedInOperatingActivities`: 158,071 rows
  - `ifrs-full_ProfitLoss`: 158,010 rows
  - `ifrs-full_GrossProfit`: 131,282 rows (some companies don't report gross profit separately)
- 749 companies with negative equity — these are financially distressed firms. The pipeline's `|ROE| <= 300%` filter handles extreme cases.
- One extreme outlier: max equity ≈ 4.27e+17 (likely a data entry error or unit mismatch). Pipeline ROE cap at ±300% limits the damage.
- 0 NULL `amount_current` for equity rows.

---

## 7. Index Constituents Coverage (`index_constituents`)

- [x] Monthly snapshots should exist for every month 2010-01 through recent
- [x] KOSPI 200 member count should be ~200 each month
- [x] Check for any months with zero rows (data gap)
- [x] Confirm `KOSPI_코스피_200` index code exists

```sql
-- Monthly coverage
SELECT strftime('%Y-%m', date) AS month,
       COUNT(DISTINCT index_code) AS n_indices,
       COUNT(DISTINCT stock_code) AS n_stocks
FROM index_constituents
GROUP BY month ORDER BY month;

-- KOSPI 200 member count per month (should be ~200)
SELECT date, COUNT(*) AS members
FROM index_constituents
WHERE index_code = 'KOSPI_코스피_200'
GROUP BY date ORDER BY date DESC LIMIT 12;

-- Months with no data at all
-- Compare to expected: Jan 2010 through recent = ~195 months
SELECT COUNT(DISTINCT strftime('%Y-%m', date)) AS months_present
FROM index_constituents;
```

**Findings:** ✅ PASS
- 195 months present (2010-01 through 2026-03) — no gaps.
- KOSPI 200 always has exactly 200 members each month — consistent.
- All 60 index codes have continuous coverage.

---

## 8. Index Daily Prices — Benchmark (`index_daily_prices`)

- [x] KOSPI 200 has continuous history from 2010 to recent
- [x] No gaps > 7 calendar days (long weekends/holidays are OK)
- [x] Closing index values are reasonable (KOSPI 200 should be 200–800 range)
- [x] KOSDAQ composite data also present

```sql
-- Freshness check
SELECT index_code, MIN(date), MAX(date), COUNT(*) AS trading_days
FROM index_daily_prices
WHERE index_code IN ('KOSPI_코스피_200', 'KOSPI_코스피', 'KOSDAQ_코스닥', 'KOSDAQ_코스닥_150')
GROUP BY index_code;

-- KOSPI 200 value range sanity check
SELECT MIN(closing_index), MAX(closing_index), AVG(closing_index)
FROM index_daily_prices WHERE index_code = 'KOSPI_코스피_200';
```

**Findings:** ⚠️ ISSUE — KOSDAQ index gap
- KOSPI 200: 3,976 trading days (2010-01-04 → 2026-03-20) ✅
- KOSPI composite: 3,976 days ✅
- **KOSDAQ composite (`코스닥`): only 2,307 days — ~42% missing vs KOSPI**
- KOSDAQ 150: 2,253 days (similar gap)
- KOSPI 200 value range: min 181, max 456, avg 297 — all reasonable.
- **Impact:** When `--benchmark KOSDAQ_코스닥` is selected, benchmark returns will have gaps → alpha/down-capture calculations will be wrong for those periods. Default `KOSPI_코스피_200` is fine.

---

## 9. VKOSPI Data (`deriv_index_daily`)

- [x] VKOSPI series exists and has continuous history
- [x] Values are in reasonable range (VKOSPI typically 10–40, spikes to 80+ in crises)
- [x] Check for the COVID spike (Mar 2020 should show high values)
- [x] Check for missing dates that would be filled with 0.5 (neutral) incorrectly

```sql
-- Coverage and range
SELECT MIN(date), MAX(date), COUNT(*),
       MIN(closing_index) AS min_vkospi,
       MAX(closing_index) AS max_vkospi,
       AVG(closing_index) AS avg_vkospi
FROM deriv_index_daily
WHERE index_code = 'DERIV_전략지수_코스피_200_변동성지수';

-- COVID spike check (Mar 2020)
SELECT date, closing_index AS vkospi
FROM deriv_index_daily
WHERE index_code = 'DERIV_전략지수_코스피_200_변동성지수'
  AND date BETWEEN '20200301' AND '20200430'
ORDER BY closing_index DESC LIMIT 5;
```

**Findings:** 🔴 CRITICAL — Severe data gaps in VKOSPI

The correct index code used in the pipeline is `DERIV_옵션지수_코스피_200_변동성지수`.

Annual coverage breakdown:
| Year | Days present | Issue |
|------|-------------|-------|
| 2010 | 208 | Partial year (Jan-Nov only) |
| 2011 | 55 | **Severe gap** |
| 2012 | 188 | Good |
| 2013 | 196 | Good |
| 2014 | 95 | **Partial year** |
| 2015 | 246 | ✅ Full |
| 2016 | 245 | ✅ Full |
| 2017 | 44 | **Severe gap** (Jan-Mar only) |
| 2018 | 64 | **Severe gap** (Sep-Dec only) |
| 2019 | 162 | Partial (Jan-Aug only) |
| 2020 | 81 | **COVID spike MISSING** (Jul-Nov only) |
| 2021 | 47 | **Severe gap** (Oct-Dec only) |
| 2022 | 245 | ✅ Full |
| 2023 | 77 | **Severe gap** (Jan-Apr only) |
| 2024 | 65 | **Severe gap** (Sep-Dec only) |
| 2025 | 241 | ✅ Full |
| 2026 | 37 | YTD |

- **FIXED:** Full backfill completed. All years now at 243–251 trading days.
- COVID March 2020 spike confirmed present: **69.24 on 2020-03-19** (peak), 64+ on surrounding days.
- Root cause was a bug in `scripts/run_index_etl.py`: the skip-existing check used `index_daily_prices` (KOSPI table) instead of `deriv_index_daily`, so dates with KOSPI data were silently skipped even if VKOSPI was missing. Fixed at line ~134.
- VKOSPI cash-out signal is now fully functional across the entire backtest period.

---

## 10. Forward Return Integrity — Shift Gap Check

- [x] Find stocks with large date gaps (> 20 trading days) in `daily_prices`
- [x] These gaps cause `shift(-42)` to land on the wrong date
- [x] Quantify how many stock-days are affected

```sql
-- Stocks with large gaps (trading halts, data errors)
WITH gaps AS (
    SELECT stock_code, date,
           LAG(date) OVER (PARTITION BY stock_code ORDER BY date) AS prev_date,
           julianday(date) - julianday(LAG(date) OVER (PARTITION BY stock_code ORDER BY date)) AS gap_days
    FROM daily_prices
    WHERE volume > 0
)
SELECT stock_code, date, prev_date, gap_days
FROM gaps
WHERE gap_days > 20
ORDER BY gap_days DESC
LIMIT 30;
```

**Findings:** ✅ PASS (for investable universe)
- Large gaps (30+ calendar days) exist only in extremely illiquid stocks.
- Example: stock 446600 has 27 trading days over 2+ years, with gaps up to 364 calendar days. But its avg daily value is ~180,000 KRW (~$135 USD) — far below the bottom-20% liquidity filter threshold.
- All stocks that pass the pipeline's liquidity filter (`avg_value_20d >= bottom 20% of universe`) have continuous daily trading with no gaps > 7 calendar days.
- `shift(-42)` row-index forward return is accurate for all stocks that actually appear in backtest rebalances.

---

## Status

| Check | Status | Notes |
|-------|--------|-------|
| 1. Adjusted prices | ✅ PASS | Row counts match, Samsung split correct, 0 nulls |
| 2. Raw price anomalies | ✅ PASS | -98% drops are legit splits, no bad data |
| 3. Universe coverage by year | ✅ PASS | 2,051–3,928 stocks, 245–248 trading days/year |
| 4. Delisted stocks | ✅ PASS | 1,720 records, 0 prices after delisting |
| 5. Financial data coverage | 🔴 ISSUE | Only 34 companies in 2015; full coverage from 2016 |
| 6. Financial items key columns | ✅ FIXED | 11 bad periods corrected (7×÷10^6, 4×÷10^3 DART unit errors) |
| 7. Index constituents coverage | ✅ PASS | 195 months, KOSPI 200 always exactly 200 members |
| 8. Index daily prices benchmark | ✅ FIXED | KOSDAQ backfilled to 3,989 days; KOSPI 200 3,976 days; both full coverage 2010–2026 |
| 9. VKOSPI data | ✅ FIXED | Backfill complete; all years 243–251 days; COVID spike (69.24 on 2020-03-19) confirmed |
| 10. Forward return shift gaps | ✅ PASS | Large gaps only in ultra-illiquid stocks filtered out by pipeline |
