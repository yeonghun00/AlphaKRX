# ETL Pipelines

Four independent ETL pipelines populate `data/krx_stock_data.db`. See [DATABASE.md](DATABASE.md) for the full database schema.

---

## Unified Runner (`scripts/run_etl.py`)

Recommended entry point. Manages all 4 pipelines, auto-detects gaps, and skips data that already exists.

### Daily update (most common)

```bash
python3 scripts/run_etl.py update --markets kospi,kosdaq --workers 4
```

What each pipeline does:
- **Prices**: fetches from `MAX(date)+1` to today, skips existing dates
- **Index constituents**: processes months from latest stored month+1 to now
- **Delisted stocks**: full refresh (single HTTP call, idempotent)
- **Financials**: only processes new ZIP files not yet in `.processed_files` marker

### Historical backfill

```bash
python3 scripts/run_etl.py backfill --start-date 20100101 --end-date 20251231
```

### Skip specific pipelines

```bash
# Only run prices and delisted
python3 scripts/run_etl.py update --skip index financial

# Only run financials
python3 scripts/run_etl.py update --skip prices index delisted
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--markets` | `kospi,kosdaq` | Markets for price fetching |
| `--workers` | `4` | Parallel workers for index scraping |
| `--skip` | none | Pipelines to skip: `prices`, `index`, `delisted`, `financial` |

Before running, prints a status table showing each pipeline's latest data and estimated gap.

---

## Pipeline 1: Prices + Stock Master (`etl/price_etl.py`)

**Source**: KRX market data API
**Tables updated**: `stocks`, `daily_prices`, `stock_history`

Fetches daily OHLCV and market cap for all KOSPI/KOSDAQ stocks. Also maintains the stock master table with name and sector history.

---

## Pipeline 2: Index Constituents (`etl/index_constituents_etl.py`)

**Source**: KRX index website (via Selenium + Chrome)
**Table updated**: `index_constituents`

```bash
# Update (latest month only)
python3 etl/index_constituents_etl.py \
  --mode update --strategy skip --workers 4 --config config.json

# Backfill (full history from 2010)
python3 etl/index_constituents_etl.py \
  --mode backfill --start-date 2010-01-01 --workers 4 --config config.json
```

**Notes**:
- Requires Chrome + matching ChromeDriver installed
- `--strategy overwrite` replaces existing rows; `skip` keeps existing dates
- Each snapshot records which stocks belong to which KRX indices on that month
- Used for: (1) `constituent_index_count` feature, (2) sector assignment per stock

---

## Pipeline 3: Delisted Stocks (`etl/delisted_stocks_etl.py`)

**Source**: KRX KIND endpoint
**Table updated**: `delisted_stocks`

```bash
python3 etl/delisted_stocks_etl.py
```

Rebuilds the entire table each run (idempotent). The model uses this to cut off each delisted stock's data at its delisting date, preventing survivorship bias.

---

## Pipeline 4: Financial Statements (`etl/financial_etl.py`)

**Source**: Raw ZIP files in `data/raw_financial/` (manually downloaded from DART)
**Tables updated**: `financial_periods`, `financial_items_bs_cf`, `financial_items_pl`

```bash
python3 etl/financial_etl.py data/krx_stock_data.db data/raw_financial
```

**Notes**:
- ZIPs contain BS (balance sheet), PL (income statement), and CF (cash flow) data
- Item codes normalized from `ifrs_X` → `ifrs-full_X` format
- Only consolidated (`연결`) statements used by the model
- `available_date` enforces PIT safety — financial data never used before public disclosure

### Downloading Financial ZIP Files from DART

Financial statement data must be downloaded manually from the DART bulk download page:

**URL**: https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do

**Steps:**
1. Go to the URL above (no login required)
2. Select report type:
   - `사업보고서` (Annual) — for full-year data
   - `분기보고서` (Quarterly) / `반기보고서` (Semi-annual) — for intra-year updates
3. Select the year
4. Download all three file types: **BS** (balance sheet), **PL** (income statement), **CF** (cash flow)
5. Place all downloaded ZIP files into `data/raw_financial/`
6. Run the ETL: `python3 etl/financial_etl.py data/krx_stock_data.db data/raw_financial`

**For a full backfill (2010–present):** download annual ZIPs for each year 2010–present — approximately 45 files (15 years × 3 types). The ETL tracks which ZIPs have been processed via `.processed_files` so re-running is safe.

**Update frequency:** quarterly — download new ZIPs after each earnings season (typically April, August, November for Q1/H1/Q3; April for annual).

---

## Validation After ETL

```bash
# Row counts
sqlite3 data/krx_stock_data.db "SELECT COUNT(*) FROM daily_prices;"
sqlite3 data/krx_stock_data.db "SELECT COUNT(*) FROM index_constituents;"
sqlite3 data/krx_stock_data.db "SELECT COUNT(*) FROM delisted_stocks;"
sqlite3 data/krx_stock_data.db "SELECT COUNT(*) FROM financial_periods;"

# Data freshness
sqlite3 data/krx_stock_data.db "SELECT MAX(date) FROM daily_prices;"
sqlite3 data/krx_stock_data.db "SELECT MAX(date) FROM index_constituents;"
```

---

## Common Issues

| Problem | Fix |
|---------|-----|
| Selenium/Chrome errors in constituents ETL | Install/update Chrome and matching ChromeDriver |
| Financial ETL loads 0 rows | Check that ZIP files exist in `data/raw_financial/` |
| Very slow backfill | Use `--workers 4` for constituents; split date ranges for prices |
| `market_type` column missing | Run `price_etl.py` first — it creates the `daily_prices` table |
