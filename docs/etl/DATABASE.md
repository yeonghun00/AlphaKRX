# Database Schema

SQLite database: `data/krx_stock_data.db`

---

## `stocks` — Stock Master

| Column | Type | Description |
|--------|------|-------------|
| `stock_code` | TEXT PK | 6-digit KRX code (e.g. `005930`) |
| `current_name` | TEXT | Latest company name |
| `current_market_type` | TEXT | `kospi` or `kosdaq` |
| `current_sector_type` | TEXT | KRX sector classification |
| `shares_outstanding` | INTEGER | Current shares outstanding |
| `is_active` | BOOLEAN | Whether the stock is still listed |

---

## `stock_history` — Name/Market Changes Over Time

| Column | Type | Description |
|--------|------|-------------|
| `stock_code` | TEXT FK | References `stocks` |
| `effective_date` | TEXT | Date of this snapshot (YYYYMMDD) |
| `name` | TEXT | Company name at that date |
| `market_type` | TEXT | Market at that date |

---

## `daily_prices` — OHLCV + Market Cap

Primary key: `(stock_code, date)`

| Column | Type | Description |
|--------|------|-------------|
| `stock_code` | TEXT FK | References `stocks` |
| `date` | TEXT | Trading date (YYYYMMDD) |
| `closing_price` | INTEGER | Close price (KRW) |
| `opening_price` | INTEGER | Open price |
| `high_price` | INTEGER | Day high |
| `low_price` | INTEGER | Day low |
| `volume` | INTEGER | Shares traded |
| `value` | INTEGER | Value traded (KRW) |
| `market_cap` | INTEGER | Market capitalization (KRW) |
| `change` | INTEGER | Price change from prev close |
| `change_rate` | REAL | % change |

---

## `index_constituents` — Monthly Index Membership Snapshots

| Column | Type | Description |
|--------|------|-------------|
| `date` | TEXT | Snapshot date (YYYY-MM-DD format) |
| `stock_code` | TEXT | Member stock code |
| `index_code` | TEXT | Index identifier (e.g. `KOSPI_코스피_200`, `KOSDAQ_코스닥_IT`) |

Used for two purposes:
1. Counting how many indices a stock belongs to (`constituent_index_count` feature)
2. Assigning each stock a sector based on its most specific (smallest) non-broad index

---

## `delisted_stocks`

| Column | Type | Description |
|--------|------|-------------|
| `stock_code` | TEXT UNIQUE | Delisted stock code |
| `company_name` | TEXT | Company name |
| `delisting_date` | DATE | When it was delisted (YYYY-MM-DD) |
| `delisting_reason` | TEXT | Reason for delisting |

---

## `financial_periods` — Statement Metadata

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment ID |
| `stock_code` | TEXT | Company code |
| `fiscal_date` | TEXT | Period end date (YYYY-MM-DD) |
| `available_date` | TEXT | First date this data can be used (PIT-safe) |
| `consolidation_type` | TEXT | `연결` (consolidated) or `별도` (separate) |
| `fiscal_month` | INTEGER | Fiscal year-end month |
| `report_type` | TEXT | Annual/quarterly indicator |

`available_date` uses the **45/90-day disclosure rule**:
- Q1/Q2/Q3: available ~45 days after fiscal period end
- Q4 (annual): available ~90 days after fiscal period end

Example (December fiscal year):

| Quarter | Ends | Available |
|---------|------|-----------|
| Q1 | Mar 31 | May 16 |
| Q2 | Jun 30 | Aug 16 |
| Q3 | Sep 30 | Nov 15 |
| Q4 | Dec 31 | Apr 1 (next year) |

---

## `financial_items_bs_cf` — Balance Sheet + Cash Flow

| Column | Type | Description |
|--------|------|-------------|
| `period_id` | INTEGER FK | References `financial_periods.id` |
| `item_code_normalized` | TEXT | Normalized IFRS code (e.g. `ifrs-full_Equity`) |
| `item_name` | TEXT | Human-readable item name |
| `amount_current` | REAL | Current period amount |
| `amount_prev` | REAL | Previous period amount |

Key items used by the model: `ifrs-full_Equity`, `ifrs-full_Assets`, `ifrs-full_CashFlowsFromUsedInOperatingActivities`

---

## `financial_items_pl` — Income Statement

| Column | Type | Description |
|--------|------|-------------|
| `period_id` | INTEGER FK | References `financial_periods.id` |
| `item_code_normalized` | TEXT | Normalized IFRS code |
| `item_name` | TEXT | Human-readable item name |
| `amount_current_ytd` | REAL | Year-to-date amount |
| `amount_current_qtr` | REAL | Current quarter amount |

Key items used by the model: `ifrs-full_ProfitLoss` (net income), `ifrs-full_GrossProfit`
