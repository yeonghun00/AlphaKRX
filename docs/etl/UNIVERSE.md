# Universe Schema

Tables that define which stocks are in the investable universe at each point in time.

---

## `delisted_stocks` — Delisted Company Registry

**Primary key:** `stock_code` (UNIQUE)
**Rows:** 1,720
**ETL source:** `etl/delisted_stocks_etl.py` — fetches from KRX KIND endpoint, full refresh on every run (idempotent)

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | Auto-increment PK |
| `stock_code` | TEXT | NO | 6-digit KRX code |
| `company_name` | TEXT | YES | Company name at delisting |
| `delisting_date` | DATE | YES | Date delisting took effect (YYYY-MM-DD) |
| `delisting_reason` | TEXT | YES | Reason code (e.g. merger, bankruptcy, voluntary) |
| `notes` | TEXT | YES | Additional notes |
| `downloaded_at` | TIMESTAMP | NO | When this record was fetched |

**How it is used (survivorship bias control):**

```python
# _pipeline.py — _exclude_delisted()
keep = (merged["delisting_date"].isna()          # still listed
        | (merged["date"] < merged["delisting_date"]))  # before delisting

# Result: stock appears in universe from its IPO through its last trading day.
# On and after delisting_date, the stock is excluded.
```

**Forward return at delisting:** When a stock delists before T+horizon, `shift(-42)` returns NaN (no future rows). The pipeline replaces this with `(last_traded_price / entry_price) - 1`, capturing the actual final return including any crash or M&A premium.

**Update frequency:** Every ETL run (single HTTP call, ~1 second). Always run before backtesting to ensure the latest delisting dates are present.

**Verification:**
```sql
SELECT COUNT(*) FROM delisted_stocks WHERE delisting_date IS NOT NULL;
-- Should be ~1700+

SELECT stock_code, company_name, delisting_date, delisting_reason
FROM delisted_stocks
ORDER BY delisting_date DESC
LIMIT 10;
```

---

## `index_constituents` — Monthly Index Membership Snapshots

**Primary key:** `(id)` with unique constraint on `(date, stock_code, index_code)`
**Rows:** 2,400,889
**Date range:** 2010-01-01 → 2026-03-01 (monthly snapshots)
**ETL source:** `etl/index_constituents_etl.py` — Selenium scraper against KRX website

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | Auto-increment PK |
| `date` | TEXT | NO | Snapshot date (YYYY-MM-DD, always first of month) |
| `stock_code` | TEXT | NO | Member stock code |
| `index_code` | TEXT | NO | Index identifier (e.g. `KOSPI_코스피_200`) |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

**What indices are tracked:**
- `KOSPI_코스피` — full KOSPI composite
- `KOSPI_코스피_200` — top 200 large-caps (model benchmark)
- `KOSPI_코스피_100` — top 100
- `KOSPI_코스피_50` — top 50
- `KOSDAQ_코스닥` — full KOSDAQ composite
- `KOSDAQ_코스닥_150` — top 150 KOSDAQ stocks
- Sector indices: `KOSDAQ_IT`, `KOSDAQ_금융`, etc. (60 distinct index codes)

**Two uses in the feature pipeline:**

1. **`constituent_index_count` feature** — number of indices a stock belongs to at each rebalance date. Higher = more visible, institutional-grade company. Used as a signal for quality/liquidity.
   ```python
   # merge_asof on membership_date (PIT-safe)
   constituent_index_count = count of matching rows for (stock_code, date)
   ```

2. **Sector label assignment** — when `financial_periods.industry_name` is missing for a stock, the pipeline falls back to assigning sector from the most specific (smallest) non-broad index the stock belongs to.

**ETL scraper note:**
- Requires Chrome + matching ChromeDriver
- Scrapes one month at a time using Selenium
- `--strategy skip` (default): keeps existing rows, only appends new months
- `--strategy overwrite`: replaces existing rows for scraped months
- **Known issue:** hardcoded OTP date range in the scraper may cause stale results if not refreshed

**Verification:**
```sql
-- Check monthly coverage (should have ~1 row per month 2010-2026)
SELECT strftime('%Y-%m', date) AS month,
       COUNT(DISTINCT index_code) AS n_indices,
       COUNT(DISTINCT stock_code) AS n_stocks
FROM index_constituents
GROUP BY month
ORDER BY month DESC
LIMIT 12;

-- Check KOSPI 200 member count over time (should be ~200)
SELECT date, COUNT(*) AS members
FROM index_constituents
WHERE index_code = 'KOSPI_코스피_200'
GROUP BY date
ORDER BY date DESC
LIMIT 6;
```

---

## `index_category_mapping` — Index Classification

**Primary key:** `index_code`
**Rows:** 91

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `index_code` | TEXT | NO | Index identifier |
| `category` | TEXT | YES | Korean category name (e.g. `대표지수`, `코스피 200 섹터지수`) |
| `market` | TEXT | YES | `KOSPI` or `KOSDAQ` |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

**Purpose:** Used to classify index codes into broad vs. sector-specific buckets. The sector label fallback logic (see `index_constituents` above) uses this to find the most specific (non-broad) index a stock belongs to.

**Categories present in DB:**
- `종합지수` — Composite index (broadest, KOSPI/KOSDAQ overall)
- `대표지수` — Representative index (KOSPI 200, KOSPI 100, etc.)
- `코스피 200 섹터지수` — KOSPI 200 sector sub-indices

---

## Universe at Each Rebalance Date

The feature pipeline constructs the investable universe per rebalance date by combining all three tables above:

```
daily_prices
  WHERE volume > 0                          ← exclude trading halts
    AND market_cap BETWEEN min AND max      ← size filter
    AND market_type IN (kospi, kosdaq)      ← exclude ETFs

MINUS

delisted_stocks WHERE date >= delisting_date ← remove stocks on/after delisting

FILTER

_apply_hard_universe_filters():
  closing_price >= 2000                     ← min price (low_price_trap proxy)
  avg_value_20d >= bottom 20% of universe   ← liquidity filter
  |ROE| <= 300%                             ← exclude extreme distress / data errors
  bad_accrual == False                      ← exclude earnings manipulation signal
                                            (uses PIT financial data)
```

**Result:** ~100–350 stocks per rebalance date (varies with market cap filter settings).
