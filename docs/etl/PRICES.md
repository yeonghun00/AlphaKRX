# Prices Schema

**ETL source:** `etl/price_etl.py` (KRX market data API), `etl/adj_price_etl.py` (computed locally)

---

## `stocks` — Stock Master

**Primary key:** `stock_code`
**Rows:** 4,755 (active + inactive)
**Updated by:** `price_etl.py` on every daily run

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `stock_code` | TEXT | NO | 6-digit KRX code (e.g. `005930`) |
| `current_name` | TEXT | NO | Latest official company name |
| `current_market_type` | TEXT | YES | `kospi`, `kosdaq`, or `kodex` (ETFs) |
| `current_sector_type` | TEXT | YES | KRX sector classification (Korean string) |
| `shares_outstanding` | INTEGER | YES | Current shares outstanding |
| `is_active` | BOOLEAN | NO | `1` = currently listed, `0` = delisted |
| `updated_at` | TIMESTAMP | NO | Last ETL update timestamp |

**Notes:**
- `current_sector_type` is the KRX administrative sector, not the IFRS industry code. The feature pipeline uses `financial_periods.industry_name` for sector assignment instead (PIT-safe).
- ETFs (`kodex` market type) are present in the DB but filtered out by the `market_type IN (kospi, kosdaq)` clause in `_load_prices()`.

---

## `stock_history` — Name & Market Changes Over Time

**Primary key:** `(stock_code, effective_date)`
**Updated by:** `price_etl.py` — inserts a new row whenever name or market changes

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | Auto-increment PK |
| `stock_code` | TEXT | NO | References `stocks.stock_code` |
| `effective_date` | TEXT | NO | Date of this snapshot (YYYYMMDD) |
| `name` | TEXT | YES | Company name at that date |
| `market_type` | TEXT | YES | Market (`kospi`/`kosdaq`) at that date |
| `sector_type` | TEXT | YES | KRX sector at that date |
| `shares_outstanding` | INTEGER | YES | Shares outstanding at that date |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

**Notes:**
- Useful for auditing corporate restructurings, market migrations (KOSDAQ → KOSPI), and name changes.
- Currently **not used** by the feature pipeline. The pipeline uses `stocks.current_market_type` as a static value.

---

## `daily_prices` — Raw OHLCV + Market Cap

**Primary key:** `(stock_code, date)`
**Rows:** 8,797,312
**Date range:** 2011-01-04 → 2026-03-20
**Updated by:** `price_etl.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `stock_code` | TEXT | NO | References `stocks.stock_code` |
| `date` | TEXT | NO | Trading date (YYYYMMDD) |
| `closing_price` | INTEGER | YES | Close price (KRW, raw unadjusted) |
| `opening_price` | INTEGER | YES | Open price (KRW, raw unadjusted) |
| `high_price` | INTEGER | YES | Intraday high (KRW, raw unadjusted) |
| `low_price` | INTEGER | YES | Intraday low (KRW, raw unadjusted) |
| `volume` | INTEGER | YES | Shares traded |
| `value` | INTEGER | YES | Value traded (KRW) |
| `market_cap` | INTEGER | YES | Market capitalisation (KRW) — **not split-adjusted** |
| `change` | INTEGER | YES | Raw price change from previous close |
| `change_rate` | REAL | YES | % change from previous close (KRX-reported) |
| `market_type` | TEXT | NO | `kospi` or `kosdaq` (default `kospi`) |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

**Important caveats:**
- `closing_price`, `opening_price`, etc. are **raw unadjusted prices**. After a 50:1 split (e.g. Samsung 2018-05-04), prices drop ~98% in this table. Use `adj_daily_prices` for return calculations.
- `market_cap` = KRX-reported market cap on the day, which is derived from the same raw price. It is **not** split-adjusted for historical comparison.
- `change_rate` is the KRX-reported daily % change on **unadjusted** prices. This is the key input for `adj_price_etl.py` — a split shows as a large negative `change_rate` on the ex-date.
- Rows where `volume = 0` indicate trading halts (거래정지). These are present in the DB but filtered out in `_load_prices()` via `AND dp.volume > 0`.

**Universe filtering in feature pipeline (`_pipeline.py:148`):**
```sql
WHERE dp.volume > 0             -- exclude trading halts
  AND dp.closing_price > 0      -- exclude zero-price anomalies
  AND dp.market_cap >= ?        -- min market cap filter
  AND dp.market_type IN (...)   -- kospi and/or kosdaq only
```

---

## `adj_daily_prices` — Split-Adjusted Prices

**Primary key:** `(stock_code, date)`
**Rows:** 8,797,312 (1:1 with `daily_prices`)
**Date range:** 2011-01-04 → 2026-03-20
**Updated by:** `adj_price_etl.py` — must be run after `price_etl.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `stock_code` | TEXT | NO | References `stocks.stock_code` |
| `date` | TEXT | NO | Trading date (YYYYMMDD) |
| `adj_factor` | REAL | YES | Cumulative backward adjustment factor |
| `adj_closing_price` | REAL | YES | Split-adjusted close (KRW) |
| `adj_opening_price` | REAL | YES | Split-adjusted open (KRW) |
| `adj_high_price` | REAL | YES | Split-adjusted high (KRW) |
| `adj_low_price` | REAL | YES | Split-adjusted low (KRW) |

**Algorithm (backward-chained from last known price):**
```
adj_factor[t] = Π_{i=t+1}^{T_N}  1 / (1 + change_rate[i]/100)

In log-space:
  log(adj_factor[t]) = suffix_sum( -log1p(change_rate/100) )

adj_closing_price[t] = closing_price[T_N] × adj_factor[t]
adj_opening_price[t] = opening_price[t] × (adj_closing_price[t] / closing_price[t])
```

Where `T_N` = last trading date for the stock (or delisting date).

**Scope of adjustment:**
- ✅ Covered: stock splits, reverse splits, rights issues, face-value changes
- ❌ Not covered: cash dividends (intentionally excluded)

**How it's used in feature pipeline (`_pipeline.py:816`):**
```python
_pc = "adj_closing_price" if "adj_closing_price" in data.columns else "closing_price"
```
If this table is not populated, the pipeline silently falls back to raw `closing_price` with no warning. All forward return calculations would then include split artifacts.

**Verification (Samsung 50:1 split, 2018-05-04):**
```sql
SELECT date, closing_price, adj_closing_price, adj_factor
FROM daily_prices dp
JOIN adj_daily_prices adj USING (stock_code, date)
WHERE dp.stock_code = '005930'
  AND dp.date BETWEEN '20180502' AND '20180506';
-- adj_factor should jump from ~1.0 to ~0.02 on 2018-05-04
```

---

## How Tables Relate

```
stocks ──────────────────────┐
   │                         │
   ├── daily_prices           ├── stock_history
   │       │                  │   (name/market changes over time)
   │       └── adj_daily_prices
   │           (LEFT JOIN on stock_code, date)
   │
   └── delisted_stocks
       (stock_code FK, delisting_date)
```
