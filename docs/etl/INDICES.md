# Indices Schema

Market index price and membership data. These tables drive benchmark returns and market regime features.

**ETL source:** `etl/index_etl.py` — KRX market data API (`kospi_dd_trd`, `kosdaq_dd_trd`)

---

## `indices` — Index Master

**Primary key:** `index_code`
**Rows:** 60 distinct index codes

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `index_code` | TEXT | NO | Unique index identifier string |
| `current_name` | TEXT | NO | Current index name (Korean) |
| `index_class` | TEXT | NO | `KOSPI` or `KOSDAQ` |
| `is_active` | BOOLEAN | NO | Whether index is currently published |
| `updated_at` | TIMESTAMP | NO | Last update timestamp |

**Sample index codes:**

| `index_code` | Name | Used as |
|---|---|---|
| `KOSPI_코스피_200` | KOSPI 200 | Default benchmark |
| `KOSPI_코스피` | KOSPI Composite | Alt benchmark |
| `KOSDAQ_코스닥` | KOSDAQ Composite | Alt benchmark |
| `KOSDAQ_코스닥_150` | KOSDAQ 150 | Alt benchmark |
| `KOSPI_코스피_100` | KOSPI 100 | — |
| `KOSPI_코스피_50` | KOSPI 50 | — |
| `KOSDAQ_IT` | KOSDAQ IT | Sector index |
| `KOSDAQ_금융` | KOSDAQ Finance | Sector index |

---

## `index_daily_prices` — Index OHLCV

**Primary key:** `(index_code, date)`
**Rows:** 275,353
**Date range:** 2010-01-04 → 2026-03-20

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `index_code` | TEXT | NO | References `indices.index_code` |
| `date` | TEXT | NO | Trading date (YYYYMMDD) |
| `closing_index` | REAL | YES | Index closing value |
| `change` | REAL | YES | Point change from previous close |
| `change_rate` | REAL | YES | % change from previous close |
| `opening_index` | REAL | YES | Opening value |
| `high_index` | REAL | YES | Intraday high |
| `low_index` | REAL | YES | Intraday low |
| `trading_volume` | INTEGER | YES | Shares traded across constituents |
| `trading_value` | INTEGER | YES | Value traded (KRW) |
| `market_cap` | INTEGER | YES | Total market cap of index (KRW) |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

**How this table drives features (`_pipeline.py`):**

**1. Benchmark returns** — `_load_benchmark_returns()`:
```python
idx["fwd"] = idx["closing_index"].shift(-horizon) / idx["closing_index"] - 1
# Returns dict: date → N-day forward return for the benchmark
```
Used in: portfolio alpha calculation, statistical significance tests.

**2. Market regime features** — `_load_market_regime()`:
```python
idx["market_regime_120d"] = idx["closing_index"] / idx["closing_index"].rolling(120).mean() - 1
idx["market_regime_20d"]  = idx["closing_index"] / idx["closing_index"].rolling(20).mean() - 1
idx["market_ret_1d"]      = idx["closing_index"].pct_change(1)
idx["market_forward_return_Nd"] = idx["closing_index"].shift(-N) / idx["closing_index"] - 1
```

**Cash-out rule (portfolio construction):**
- `market_regime_20d < 0` → market is below 20-day MA → reduce position by 50%
- Combined with VKOSPI signal from `deriv_index_daily` for additional cash-out

**3. Residual return target:**
```python
target_residual = forward_return - (rolling_beta_60d × market_forward_return)
```
The model trains on beta-adjusted residual returns, not raw returns. Missing `market_forward_return` silently falls back to raw returns.

---

## `index_history` — Index Name Changes

**Primary key:** `(index_code, effective_date)`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | Auto-increment PK |
| `index_code` | TEXT | NO | References `indices.index_code` |
| `effective_date` | TEXT | NO | Date of change (YYYYMMDD) |
| `name` | TEXT | YES | Index name at that date |
| `index_class` | TEXT | YES | `KOSPI` or `KOSDAQ` at that date |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

**Note:** Not currently used by the feature pipeline. Useful for auditing index rebranding events.

---

## Verification Queries

```sql
-- Check data freshness
SELECT index_code, MAX(date) AS latest_date
FROM index_daily_prices
WHERE index_code IN ('KOSPI_코스피_200', 'KOSDAQ_코스닥', 'KOSDAQ_코스닥_150')
GROUP BY index_code;

-- Verify KOSPI 200 has continuous history from 2010
SELECT strftime('%Y', date) AS year, COUNT(*) AS trading_days
FROM index_daily_prices
WHERE index_code = 'KOSPI_코스피_200'
GROUP BY year ORDER BY year;
-- Each year should have ~248 trading days

-- Check for gaps in market regime feature (consecutive dates)
SELECT date,
       LAG(date) OVER (ORDER BY date) AS prev_date,
       julianday(date) - julianday(LAG(date) OVER (ORDER BY date)) AS gap
FROM index_daily_prices
WHERE index_code = 'KOSPI_코스피_200'
HAVING gap > 5    -- more than a long weekend
ORDER BY date;
```
