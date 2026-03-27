# Database Schema Overview

SQLite database: `data/krx_stock_data.db`

**20 tables** across 5 domains. See the linked files for full column-level detail.

| Domain | Tables | Doc |
|--------|--------|-----|
| Equities — Prices | `daily_prices`, `adj_daily_prices`, `stocks`, `stock_history` | [PRICES.md](PRICES.md) |
| Equities — Financials | `financial_periods`, `financial_items_bs_cf`, `financial_items_pl` | [FINANCIALS.md](FINANCIALS.md) |
| Equities — Universe | `delisted_stocks`, `index_constituents`, `index_category_mapping` | [UNIVERSE.md](UNIVERSE.md) |
| Indices | `indices`, `index_daily_prices`, `index_history` | [INDICES.md](INDICES.md) |
| Derivatives & Bonds | `deriv_indices`, `deriv_index_daily`, `bond_indices`, `bond_index_daily`, `govt_bonds`, `govt_bond_daily`, `govt_bond_history` | [DERIVATIVES_BONDS.md](DERIVATIVES_BONDS.md) |

---

## Row Counts & Date Coverage (as of 2026-03)

| Table | Rows | Date Range |
|-------|------|------------|
| `daily_prices` | 8,797,312 | 2011-01-04 → 2026-03-20 |
| `adj_daily_prices` | 8,797,312 | 2011-01-04 → 2026-03-20 |
| `index_constituents` | 2,400,889 | 2010-01-01 → 2026-03-01 |
| `index_daily_prices` | 275,353 | 2010-01-04 → 2026-03-20 |
| `financial_periods` | 158,094 | available 2015-05-16 → 2026-01-16 |
| `financial_items_bs_cf` | 13,491,922 | — |
| `financial_items_pl` | 3,871,357 | — |
| `deriv_index_daily` | 418,617 | 2010-01-04 → 2026-03-20 |
| `bond_index_daily` | 5,898 | 2010-02-15 → 2026-03-20 |
| `govt_bond_daily` | 30,515 | 2010-01-04 → 2026-03-20 |
| `delisted_stocks` | 1,720 | — |
| `stocks` | 4,755 | — |

---

## Key Design Principles

**Point-in-time (PIT) safety for financials:**
Financial data is never used before its public disclosure date. Each row in `financial_periods` has an `available_date` computed from the 45/90-day disclosure rule. The feature pipeline enforces this via `merge_asof(direction="backward")`.

**Backward-chained adjusted prices:**
`adj_daily_prices` uses `change_rate` from `daily_prices` to compute a split/rights-adjusted price via log-space suffix products. Dividends are excluded. The anchor is the last known price for each stock (or delisting date).

**Survivorship-bias control:**
`delisted_stocks` tracks all delisted companies with delisting dates. The feature pipeline includes these stocks up to (but not including) their delisting date.

**Index membership as PIT feature:**
`index_constituents` stores monthly snapshots of which stocks belong to which KRX indices. Used to compute `constituent_index_count` and sector labels.
