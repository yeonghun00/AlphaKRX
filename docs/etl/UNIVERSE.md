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

## Universe at Each Rebalance Date

The feature pipeline constructs the investable universe per rebalance date:

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
