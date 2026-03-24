# Financials Schema

**ETL source:** `etl/financial_etl.py`
**Data source:** Manual ZIP downloads from DART (https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do)

---

## Overview

Three tables form the financial statement pipeline:

```
financial_periods          ← one row per filing (company × quarter × consolidation type)
    │
    ├── financial_items_bs_cf   ← balance sheet + cash flow line items
    └── financial_items_pl      ← income statement line items
```

The key design constraint: **every row in `financial_periods` has an `available_date`** computed from the 45/90-day public disclosure rule. The feature pipeline enforces this via `merge_asof(direction="backward")` so no financial data is ever used before it was publicly available.

---

## `financial_periods` — Filing Metadata

**Primary key:** `id`
**Rows:** 158,094
**Date range (available_date):** 2015-05-16 → 2026-01-16
**Distinct companies:** 3,015

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | Auto-increment PK |
| `stock_code` | TEXT | NO | 6-digit KRX company code |
| `company_name` | TEXT | YES | Company name at time of filing |
| `market_type` | TEXT | YES | `kospi` or `kosdaq` |
| `industry_code` | TEXT | YES | KRX industry classification code |
| `industry_name` | TEXT | YES | KRX industry name (Korean) — used as sector label in features |
| `fiscal_month` | INTEGER | YES | Fiscal year-end month (usually `12`) |
| `fiscal_date` | TEXT | NO | Period end date (YYYY-MM-DD) |
| `available_date` | TEXT | NO | **PIT enforcement date** — earliest date this row can be used |
| `report_type` | TEXT | YES | `사업보고서` (annual), `1분기보고서` (Q1), `반기보고서` (H1/Q2), `3분기보고서` (Q3) |
| `consolidation_type` | TEXT | YES | `연결` (consolidated) or `별도` (standalone) |
| `currency` | TEXT | NO | Always `KRW` |
| `created_at` | TIMESTAMP | NO | Insert timestamp |

**`available_date` computation (`financial_etl.py` — `get_available_date()`):**

For December fiscal year (most companies):

| Quarter | Fiscal period ends | Available date |
|---------|-------------------|----------------|
| Q1 | March 31 | May 16 (~45 days) |
| Q2 / H1 | June 30 | August 16 (~45 days) |
| Q3 | September 30 | November 15 (~45 days) |
| Q4 / Annual | December 31 | April 1 next year (~90 days) |

For non-December fiscal years: 45-day lag for interim reports, 90-day lag for annual.

**Known edge case:** The formula for non-December fiscal years adds fixed calendar months (`+2` for quarterly, `+3` for annual) without accounting for month-end boundary effects. Companies with October or November fiscal year-ends may have incorrect `available_date` values — the year increment may be missing.

**Feature pipeline usage:**
```python
# Only disclosures before the trade date are loaded:
WHERE REPLACE(fp.available_date, '-', '') <= ?    # ? = feature_date

# Attached to price data via backward merge:
merge_asof(left_on="date_dt", right_on="available_dt",
           by="stock_code", direction="backward")
```

**Staleness guard:** If the most recent filing is >450 days old (15 months), all financial features are set to NaN for that stock on that date. Prevents stale annual figures from persisting indefinitely.

---

## `financial_items_bs_cf` — Balance Sheet & Cash Flow Items

**Primary key:** `id`
**Rows:** 13,491,922
**Statement types:** `BS` (Balance Sheet / 재무상태표), `CF` (Cash Flow / 현금흐름표)

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | Auto-increment PK |
| `period_id` | INTEGER | NO | FK → `financial_periods.id` |
| `statement_type` | TEXT | NO | `BS` or `CF` |
| `item_code` | TEXT | NO | Raw DART IFRS code (e.g. `ifrs_Equity`) |
| `item_code_normalized` | TEXT | YES | Normalised code (e.g. `ifrs-full_Equity`) |
| `item_name` | TEXT | NO | Korean item name |
| `amount_current` | REAL | YES | Current period amount (KRW) |
| `amount_prev` | REAL | YES | Prior period amount (KRW) |
| `amount_prev2` | REAL | YES | Two-period-prior amount (KRW) |

**Key IFRS codes used by the model:**

| Normalised code | Description | Used for |
|----------------|-------------|---------|
| `ifrs-full_Equity` | Total shareholders' equity | ROE denominator, leverage |
| `ifrs-full_Assets` | Total assets | GPA denominator |
| `ifrs-full_CashFlowsFromUsedInOperatingActivities` | Operating cash flow | Bad accrual filter, distress |
| `ifrs-full_CurrentAssets` | Current assets | (available, not currently used) |
| `ifrs-full_CurrentLiabilities` | Current liabilities | (available, not currently used) |

**Code normalisation:** Raw DART codes use the format `ifrs_X`. The ETL normalises these to `ifrs-full_X` to match the IFRS taxonomy. Mapping table is in `financial_etl.py` (`ITEM_CODE_MAPPING`).

**Only consolidated statements used:** The feature pipeline filters `WHERE consolidation_type = '연결'`. Standalone (`별도`) statements are stored but ignored.

---

## `financial_items_pl` — Income Statement Items

**Primary key:** `id`
**Rows:** 3,871,357

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | Auto-increment PK |
| `period_id` | INTEGER | NO | FK → `financial_periods.id` |
| `item_code` | TEXT | NO | Raw DART IFRS code |
| `item_code_normalized` | TEXT | YES | Normalised IFRS code |
| `item_name` | TEXT | NO | Korean item name |
| `amount_current_qtr` | REAL | YES | Current quarter amount (KRW) |
| `amount_current_ytd` | REAL | YES | Year-to-date amount (KRW) — **used by model** |
| `amount_prev_qtr` | REAL | YES | Prior quarter amount (KRW) |
| `amount_prev_ytd` | REAL | YES | Prior year-to-date amount (KRW) |
| `amount_prev_year` | REAL | YES | Full prior year amount (KRW) |
| `amount_prev2_year` | REAL | YES | Two-year-prior full year amount (KRW) |

**Key IFRS codes used by the model:**

| Normalised code | Description | Used for |
|----------------|-------------|---------|
| `ifrs-full_ProfitLoss` | Net income (YTD) | ROE numerator, bad accrual |
| `ifrs-full_GrossProfit` | Gross profit (YTD) | GPA = GrossProfit / Assets |
| `ifrs-full_Revenue` | Revenue (YTD) | (available, not currently used) |

**YTD annualisation:** Because YTD figures grow through the year (Q1 = 3 months, Q2 = 6 months, etc.), the ETL computes an annualisation factor:
```python
months_ytd = ((fiscal_date_month - fiscal_month) % 12).replace(0, 12)
annualization_factor = 12.0 / months_ytd.clip(lower=3)
net_income  = net_income_ytd × annualization_factor
gross_profit = gross_profit_ytd × annualization_factor
operating_cf = operating_cf_ytd × annualization_factor
```
This converts partial-year figures to an annualised run rate for cross-period comparability.

---

## Feature Pipeline — How Financials Become Features

```
financial_periods + financial_items_bs_cf + financial_items_pl
    │
    ▼ _load_financial_ratios_pit()

SELECT fp.stock_code, fp.available_date,
       equity, assets, operating_cf,   ← from bs_cf
       net_income, gross_profit          ← from pl
WHERE consolidation_type = '연결'
  AND available_date <= end_date

    │
    ▼ Compute ratios

ROE = net_income / equity                          (annualised)
GPA = gross_profit / assets                        (annualised)
bad_accrual flag = (net_income > 0) AND (operating_cf < 0)

    │
    ▼ _merge_financial_features()  — PIT join

merge_asof(left_on="date_dt", right_on="available_dt",
           by="stock_code", direction="backward")

    │
    ▼ Fill NaN

ROE, GPA: NaN → sector median → market median → 0.0
net_income, operating_cf: left as NaN (used only in bad_accrual filter)
```

**Staleness guard:** If `(trade_date - available_date) > 450 days`, financial features are set NaN, then re-filled by imputation above.

---

## Data Coverage & Known Gaps

```sql
-- Check filing coverage by year
SELECT strftime('%Y', available_date) AS year,
       COUNT(DISTINCT stock_code) AS companies,
       COUNT(*) AS filings
FROM financial_periods
WHERE consolidation_type = '연결'
GROUP BY year ORDER BY year;
```

**Known gaps:**
- Coverage starts 2015 (earliest `available_date` = 2015-05-16). Pre-2015 backtest years use only price-based features; ROE and GPA are NaN → imputed to sector median.
- Some companies file only standalone (`별도`) — no consolidated data available. These companies will have NaN ROE/GPA for their entire history.
- DART ZIP files must be downloaded manually. Missing quarterly ZIPs create gaps for that period.
