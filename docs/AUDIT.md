# AlphaKRX — Quant Review Checklist

A systematic checklist for reviewing this codebase. For each check: **where to look in the code**, **what query to run on the data**, and **what a red flag looks like**.

---

## RESULT INVESTIGATION: 1325% Return (no-cash-out run)

**Config that produced this:** `--no-cash-out --top-n 20 --horizon 42 --buy-rank 20 --hold-rank 80`

This section dissects why this specific result is almost certainly misleading, and what each suspicious metric is actually telling you.

---

### Why 1325% vs 461% — just one flag changed

The only difference between the 461% run and this 1325% run is `--cash-out False` (plus top-n 25→20). Removing the regime filter tripled the total return. That alone should raise suspicion: **a single binary flag should not 3x your returns unless the flag is doing most of the work, not the model.**

What the cash-out rule was actually doing in the 461% run:
- Avg cash drag 32.5% → portfolio was uninvested ~1/3 of the time
- It sat out large parts of the 2018 biotech boom, 2019 rally, 2023–2024 surge
- Those missed gains are now captured in the 1325% run

The model's signal (IC=0.11, quintile monotonicity) is identical in both runs — the feature importances and IC numbers are byte-for-byte the same. The signal did not improve. You just added leverage by staying fully invested.

---

### Red Flag 1: Down Capture of -0.19

**This is the biggest warning sign in the entire result.**

Down capture = `avg(portfolio return when benchmark < 0) / avg(benchmark return when benchmark < 0)`

A negative down capture means: **when the benchmark falls, the portfolio goes up on average.** With a long-only portfolio and no shorting, this should be nearly impossible unless:

**Explanation A — Benchmark mismatch (most likely):**
The benchmark is KOSPI 200 (top 200 large-cap KOSPI stocks — banks, Samsung, Hyundai, POSCO). The portfolio is SMID-cap KOSPI+KOSDAQ heavy in bio/pharma and machinery.

When KOSPI 200 falls, it is often because:
- Large-cap industrials and financials are selling off (rate hikes, export slowdown)
- KOSDAQ growth/bio names are *not* correlated with this and may even rally (flight to growth)

This produces negative down capture against KOSPI 200 without any model skill. It is a **structural sector rotation bet disguised as downside protection.**

Check: run with `--benchmark kosdaq150`. Down capture will likely be 0.5–0.9, not -0.19.

**Explanation B — 42-day period alignment luck:**
Down capture is computed per-rebalance (42-day windows). If the rebalance calendar happened to start its "down market" windows on dates where the portfolio was already positioned in stocks that then rallied, the metric looks great. This is not skill — it is calendar alignment noise with only 54 observations.

**What -0.19 means for investors:** In live trading, you will not achieve negative down capture in a long-only portfolio. Expect 0.4–0.7 when measured properly.

---

### Red Flag 2: 2020 = +129.98% (carries the entire result)

**The 2020 return alone contributes more than the entire benchmark's 9-year return.**

```
If you remove 2020:
  Remaining 8 years compound:
  (1+0.3405)(1+0.3556)(1+0.3667)(1+0.0519)(1-0.3187)(1+0.5594)(1+0.5382)(1+0.4522)
  ≈ 1.34 × 1.36 × 1.37 × 1.05 × 0.68 × 1.56 × 1.54 × 1.45
  ≈ 7.2x total = ~620% over 8 years

With 2020:
  7.2x × 2.30 (2020 return) ≈ 16.6x = ~1326% ✓
```

**2020 was the KOSDAQ COVID biotech boom.** Korean bio names (vaccine developers, COVID diagnostics, biotech) ran 200–500% in 2020. Any strategy that was heavy in KOSDAQ bio in early 2020 would show astronomical returns — not because the model predicted COVID, but because:
- The model was always overweight bio (it appears in top sectors every year)
- 2020 happened to be the year bio went parabolic
- This is **sector concentration luck**, not model alpha

**Test:** Run backtest with `--start 20170101 --end 20200101` (exclude 2020+). If Sharpe drops below 0.8, the strategy's headline number depends on a one-time event.

---

### Red Flag 3: Win/Loss Ratio jumped from 1.03 → 1.50

In the 461% run (with cash-out): Win/Loss = 1.03. Wins and losses nearly equal in size.
In this run (no cash-out): Win/Loss = 1.50. Wins are 50% larger than losses.

**Why this is suspicious:** The model is identical. The universe is the same. The only change is staying fully invested. How does removing cash-out improve the asymmetry between wins and losses?

Two possible explanations:
1. **Cash-out removed the small losses during regime transitions** — when the regime filter triggers exit and re-entry, you sometimes sell before a partial recovery. Removing that noise improves the loss profile.
2. **The benchmark was moving inversely during "down" rebalances** — since down capture is -0.19, the benchmark-negative periods are actually when the portfolio was winning. This produces artificially high win/loss ratio when defined as `portfolio return vs benchmark return`.

Check: look at the raw `portfolio_return` distribution in `results.csv`, not the alpha vs benchmark:
```python
import pandas as pd
r = pd.read_csv("runs/myrun/results.csv")
wins = r[r["portfolio_return"] > 0]["portfolio_return"]
losses = r[r["portfolio_return"] <= 0]["portfolio_return"]
print("Raw win/loss:", wins.mean() / abs(losses.mean()))
# If this is much lower than 1.50, the 1.50 is from benchmark comparison, not absolute returns
```

---

### Red Flag 4: Alpha = 1107% vs benchmark that returned 218%

Alpha is simply computed as: `total_return - benchmark_return = 1326% - 218% = 1108%`

This is **not risk-adjusted alpha**. It is the raw difference in cumulative returns between a SMID-cap KOSDAQ-heavy portfolio and a large-cap KOSPI index.

The "alpha" contains at minimum:
- **Size premium**: Small/mid cap outperforms large cap over long horizons (documented globally)
- **KOSDAQ premium**: KOSDAQ outperformed KOSPI meaningfully in 2017–2025 (bio boom, K-tech)
- **Concentration premium**: Bio/machinery sectors outperformed KOSPI 200 components
- **Model skill**: The actual IC-based ranking contribution

How to decompose: run `--benchmark universe` (equal-weight of your own investable universe). Whatever alpha remains above the universe benchmark is the genuine model contribution.

---

### What the result is probably telling you (honest interpretation)

| Component | Estimated contribution to 1326% |
|---|---|
| KOSDAQ size + sector premium vs KOSPI 200 | ~400–600% |
| 2020 COVID bio boom (one-time event) | ~300–400% |
| Genuine model alpha (ranking skill) | ~200–300% |
| Total | ~1326% |

The model has real signal (IC 0.11, monotonic quintiles, statistically significant). But the headline 1326% is mostly:
1. Wrong benchmark (SMID vs large-cap)
2. One extraordinary year (2020)
3. Structural sector concentration in the assets that happened to win this decade

**The honest number to present is the 461% run (with cash-out, proper execution), benchmarked against `--benchmark universe` or `--benchmark kosdaq150`.**

---

### Checklist specific to this result

| Check | Command | What to look for |
|---|---|---|
| Remove 2020 | Filter results.csv, exclude 2020 | Sharpe should still be >0.7 |
| Fairer benchmark | `--benchmark universe` | Alpha should shrink significantly |
| KOSDAQ benchmark | `--benchmark kosdaq150` | Down capture should go positive |
| Raw win/loss ratio | `portfolio_return` column in results.csv | If raw <1.2, the 1.50 is benchmark-relative illusion |
| Exclude bio/pharma | 🔴 Planned — add `--exclude-sector` | Does alpha survive without bio? |
| Sector cap | `--max-sector-weight 0.25` (once implemented) | Returns drop, but are they more honest? |

---

---

## DATA PIPELINE AUDIT — Code Deep Dive

This section audits every step from raw data → database → features → model input. These are findings from reading the actual source code, not assumptions.

---

### ISSUE 1 (CRITICAL): Bad Accrual Filter Uses Financial Data Retroactively

**File:** `ml/features/_pipeline.py`, `_apply_hard_universe_filters()` ~line 628–646

```python
if "net_income" in df.columns and "operating_cf" in df.columns:
    bad_accrual = (df["net_income"] > 0) & (df["operating_cf"] < 0)
    mask &= ~bad_accrual
```

**The problem:** This filter uses `net_income` and `operating_cf` from financial statements — data that becomes available 45–90 days after the fiscal period ends. But this filter is applied to the entire dataset as a hard exclusion, not point-in-time.

**What actually happens:**
- Stock reports Q1 earnings on May 16 (available_date)
- Q1 shows bad accrual (net_income > 0, operating_cf < 0)
- The filter retroactively removes this stock from the universe starting **March 1** — before the data was public
- Forward returns for March 1 → May 15 are computed without this stock
- In reality you would have traded it during that period

**Impact on results:** Stocks that eventually show bad accrual are cleansed from the universe earlier than possible in reality. This removes future losers before they can hurt you — a form of look-ahead bias that inflates returns.

**How to verify:**
```python
# Check how many stock-days are removed by the bad_accrual filter
# vs how many would be removed if PIT-enforced
before_filter = len(df)
df_filtered = df[~((df["net_income"] > 0) & (df["operating_cf"] < 0))]
print(f"Bad accrual removes {before_filter - len(df_filtered)} rows")
```

---

### ISSUE 2 (HIGH): Forward Return Uses Row-Index Shift, Not Calendar Shift

**File:** `ml/features/_pipeline.py`, lines 815–819

```python
data = data.sort_values(["stock_code", "date"])
_g = data.groupby("stock_code")
data[_fwd_col] = _g[_pc].shift(-target_horizon) / data[_pc] - 1
```

**The problem:** `shift(-42)` moves back 42 **rows**, not 42 **trading days**. If any stock has missing rows (data errors, early listing gaps, thin trading in 2010–2012), `shift(-42)` lands on the wrong calendar date.

**Example:**
- Stock has rows for 2020-01-02, 2020-01-03, then jumps to 2020-03-01 (gap due to trading halt)
- `shift(-42)` at 2020-01-02 lands at row +42, which is actually many months ahead
- Forward return for that date is computed over a longer period than 42 days — inflating returns during volatile gap periods

**Most affected:** Thinly traded small-caps near the bottom of the market-cap range, early years (2010–2014) where data coverage was sparse.

**How to verify:**
```sql
-- Find stocks with large date gaps in price history
SELECT stock_code,
       date,
       LAG(date) OVER (PARTITION BY stock_code ORDER BY date) AS prev_date,
       julianday(date) - julianday(LAG(date) OVER (PARTITION BY stock_code ORDER BY date)) AS gap_days
FROM daily_prices
WHERE gap_days > 10  -- more than 2 trading weeks missing
ORDER BY gap_days DESC
LIMIT 30;
```

---

### ISSUE 3 (HIGH): Adjusted Prices Are Optional — Silent Fallback to Raw

**File:** `ml/features/_pipeline.py`, line 816

```python
_pc = "adj_closing_price" if "adj_closing_price" in data.columns else "closing_price"
```

**The problem:** If the `adj_daily_prices` table was not populated (ETL step skipped), the code silently uses raw unadjusted prices with no warning. Stock splits create artificial price discontinuities:
- A 5:1 split shows as an instant -80% in raw prices
- Forward return at T picks up this -80% as the "real" return
- The model learns to avoid these stocks even though the investor lost nothing

**How to verify:**
```sql
-- Check if adj_daily_prices table exists and has data
SELECT COUNT(*) FROM adj_daily_prices;

-- Find suspicious single-day drops > 40% (potential unadjusted splits)
SELECT stock_code, date, closing_price,
       LAG(closing_price) OVER (PARTITION BY stock_code ORDER BY date) AS prev_close,
       (closing_price - LAG(closing_price) OVER (PARTITION BY stock_code ORDER BY date))
         / LAG(closing_price) OVER (PARTITION BY stock_code ORDER BY date) AS pct_chg
FROM daily_prices
HAVING pct_chg < -0.40
ORDER BY pct_chg ASC
LIMIT 20;
```

**Red flag:** If `adj_daily_prices` is empty or missing, all returns are computed on raw prices.

---

### ISSUE 4 (HIGH): Missing Data Imputed as "Normal" — Distress Signals Erased

**File:** `ml/features/_pipeline.py`, lines 618, 835–847

```python
# Financial ratios filled with sector median then market median then 0
merged[col] = merged[col].fillna(sector_med).fillna(market_med).fillna(0.0)

# Market regime: missing = neutral
data["market_regime_120d"] = data["market_regime_120d"].fillna(0.0)
data["market_regime_20d"]  = data["market_regime_20d"].fillna(0.0)

# Macro features: missing = 50th percentile
for col in _macro_cols:
    data[col] = data[col].fillna(0.5)
```

**The problem:** Missing financial ratios (ROE, GPA) are almost never random — they indicate:
- Negative equity (ROE undefined)
- Company not yet profitable (GPA near zero)
- Filing delays (potential distress signal)

Filling with sector median disguises these signals as "average quality" stocks. The model never learns to penalize missing data, which means distressed companies look healthier than they are.

**For macro/regime features:** If VKOSPI data didn't exist before 2015, pre-2015 data gets `0.5` (neutral percentile). This means the model was trained on fake "neutral volatility" conditions for the first several years, undermining regime-related features.

**How to verify:**
```python
import pandas as pd
df = pd.read_parquet("...")  # feature cache
# What % of ROE values are filled (sector median) vs real?
print("ROE null rate before fill:", df["roe"].isna().mean())
# If high, a large portion of the training data uses imputed values
```

---

### ISSUE 5 (HIGH): Final `dropna` Removes Distressed Stocks Before Model Sees Them

**File:** `ml/features/_pipeline.py`, lines 985–987

```python
required = [c for c in feature_columns if c in data.columns] + [fwd_col]
data = data.dropna(subset=required)
```

**The problem:** Any stock-day with a single NaN in any required feature is silently dropped. In practice, this removes:
- Newly listed stocks (insufficient rolling window history)
- Stocks with missing financials (distressed, late filers)
- Stocks during data gap periods

**Combined with imputation (Issue 4):** The code first fills NaNs with medians, then drops remaining NaNs. Stocks that survived imputation are kept; those that didn't (for reasons like missing forward return) are dropped. The model is trained on an already-clean dataset.

**IC and return implications:** The IC of 0.11 is computed on this cleaned subset. The true IC on the full universe including NaN-heavy stocks would be lower.

---

### ISSUE 6 (MEDIUM): Sector Assignment Is Not Truly Point-in-Time

**File:** `ml/features/_pipeline.py`, lines 268–291

```python
df = pd.read_sql_query("""
    SELECT DISTINCT stock_code,
           REPLACE(available_date, '-', '') AS available_date,
           industry_name AS sector
    FROM financial_periods
    WHERE industry_name IS NOT NULL
""", ...)
# merge_asof direction="backward"
```

**The problem:** Sector is sourced from `financial_periods.industry_name`, which is stamped with the financial filing's `available_date`. If a company restructures from "Pharmaceuticals" to "Medical Devices" mid-year:
- The new sector appears in the next financial filing's `available_date` (up to 90 days after period end)
- During those 90 days, the stock is labeled with the old sector
- Sector-neutral scoring (z-score within sector) compares it against the wrong peers

Minor in practice but affects the sector-neutral feature quality.

---

### ISSUE 7 (MEDIUM): Market Cap Filter Uses Unadjusted Market Cap

**File:** `ml/features/_pipeline.py`, lines 139–149

```python
WHERE dp.market_cap >= ?   -- raw market_cap from daily_prices
```

**The problem:** Market cap from the KRX API reflects the day's closing price × shares outstanding, but is not adjusted for splits in the same way `adj_closing_price` is. A stock near the 100B KRW threshold can oscillate in/out of the investable universe purely due to split mechanics, creating artificial entry/exit points with no real economic content.

---

### ISSUE 8 (MEDIUM): Non-December Fiscal Year PIT Calculation Has Edge Cases

**File:** `etl/financial_etl.py`, lines 112–127

```python
# For non-December fiscal year stocks:
if month <= 10:
    return f"{year}{month + 2:02d}16"  # adds 2 months (45 days proxy)
```

**The problem:** The formula adds a fixed 2 calendar months regardless of actual reporting patterns. For fiscal years ending in March, June, September, this may be accurate. But for fiscal years ending in October or November, adding 2 months crosses into the next year without the year-increment logic handling it correctly.

**Edge case:** A company with October fiscal year-end: `month=10`, formula gives `{year}1216` (December 16). A company with November fiscal year-end: `month=11`, formula gives `{year}0116` next year — but the year is not incremented. This produces an `available_date` in the **same year** as the filing, potentially 11 months before the actual disclosure.

---

### ISSUE 9 (MEDIUM): Hardcoded Date in Index Constituents ETL

**File:** `etl/index_constituents_etl.py`, ~line 380

```python
from_date = '20260203'   # hardcoded
to_date   = '20260210'   # hardcoded
```

**The problem:** The OTP (One-Time Password) generation for the KRX index constituents scraper has a hardcoded date range. If this date is in the past, the scraper fetches stale index membership data. The feature `constituent_index_count` (10.3% importance in the model) will be incorrect for any period not covered by a fresh scrape.

**Verification:**
```bash
# Check when index_constituents was last updated
sqlite3 data/krx_stock_data.db "SELECT MAX(date) FROM index_constituents;"
# Should be recent (within last month for live use)
```

---

### ISSUE 10 (LOW): Target Variable Falls Back to Raw Returns if Market Data Missing

**File:** `ml/features/_pipeline.py`, lines 724–729

```python
if market_fwd_col in out.columns and "rolling_beta_60d" in out.columns:
    out[residual_col] = out[fwd_col] - (out["rolling_beta_60d"] * out[market_fwd_col])
else:
    out[residual_col] = out[fwd_col]   # fallback: no beta adjustment
    out[residual_rank_col] = out[rank_col]
```

**The problem:** The training target is `target_residual_rank_42d` — the rank of each stock's market-beta-adjusted return. If `market_forward_return_42d` (KOSPI 200 forward return) is missing from the feature set, the model trains on raw return ranks instead of residual return ranks. The model config says `Target: target_residual_rank_42d` — if this silently fell back to raw, the model is doing something different from what is reported.

**How to verify:**
```python
# Check if market_forward_return_42d column exists in training data
print("Market fwd col present:", f"market_forward_return_42d" in df.columns)
print("rolling_beta_60d present:", "rolling_beta_60d" in df.columns)
# If either is False, the residual target is not being used
```

---

### Summary: Data Pipeline Risk Matrix

| Issue | File | Severity | Return Impact | Look-ahead? |
|-------|------|----------|---------------|-------------|
| Bad accrual filter retroactive | `_pipeline.py:628` | **CRITICAL** | +1–3% annual | **Yes** |
| Row-index shift on gapped data | `_pipeline.py:815` | **HIGH** | +0.5–2% annual | Possible |
| Raw prices if adj table empty | `_pipeline.py:816` | **HIGH** | Unpredictable | No |
| Missing data imputed as normal | `_pipeline.py:618` | **HIGH** | +0.5–1% annual | Indirect |
| Final dropna removes distress | `_pipeline.py:987` | **HIGH** | +0.5–1% annual | Indirect |
| Sector not truly PIT | `_pipeline.py:268` | MEDIUM | Minor | Marginal |
| Unadjusted market cap filter | `_pipeline.py:139` | MEDIUM | Minor | No |
| Non-Dec fiscal year PIT bug | `financial_etl.py:112` | MEDIUM | +0.2–0.5% annual | Partial |
| Hardcoded index ETL date | `index_constituents_etl.py:380` | MEDIUM | Feature quality | No |
| Residual target fallback | `_pipeline.py:724` | LOW | Unknown | No |

**Estimated total annual inflation from data issues: +2–7%**
Compounded over 9 years, 5% annual inflation turns a real 400% return into a reported 700–900% return.

---

## A. Look-Ahead Bias

The most common way backtests lie. Check every place future data could leak into past predictions.

---

### A1. Forward return computed on filtered data?

**Why it matters:** If universe filters (market cap, liquidity) run *before* `shift(-N)`, rows get dropped from each stock's series. `shift(-N)` then lands on the wrong calendar date — effectively using a future price that belongs to a different rebalance period.

**Where to check:** `ml/features/_pipeline.py`

```python
# CORRECT order (what the code does):
data[_fwd_col] = _g[_pc].shift(-target_horizon) / data[_pc] - 1   # line 815
data = self._apply_hard_universe_filters(...)                        # line 831 — AFTER

# WRONG order (would be a bug):
data = self._apply_hard_universe_filters(...)
data[_fwd_col] = _g[_pc].shift(-target_horizon) / data[_pc] - 1
```

**Data check:**
```sql
-- Verify no stock has impossible forward returns (e.g., +10000%)
SELECT stock_code, date, closing_price
FROM daily_prices
WHERE closing_price > 0
ORDER BY closing_price DESC
LIMIT 20;
```

**Red flag:** Forward return column computed inside or after universe filter loops.

---

### A2. Financial data used before public disclosure?

**Why it matters:** Q4 earnings for Dec fiscal year are disclosed ~April next year. Using Dec figures in January is 3-month look-ahead.

**Where to check:** `etl/financial_etl.py` — `get_available_date()` function, and `ml/features/_pipeline.py` — SQL query in `_load_financial_ratios_pit()`

```python
# Must see this pattern in the SQL:
WHERE REPLACE(fp.available_date, '-', '') <= ?   # ? = feature date
```

**Data check:**
```sql
-- For any stock, verify financial data available_date is always AFTER the fiscal period end
SELECT fp.stock_code,
       fp.fiscal_period,
       fp.period_end,
       fp.available_date,
       julianday(fp.available_date) - julianday(fp.period_end) AS lag_days
FROM financial_periods fp
WHERE lag_days < 30   -- flag anything disclosed faster than 30 days
ORDER BY lag_days ASC
LIMIT 20;
```

**Red flag:** Any row where `available_date < period_end + 44 days` for Q1/Q2/Q3, or `< period_end + 89 days` for annual.

---

### A3. Features using same-day close price?

**Why it matters:** At rebalance time T (e.g., 9 AM), you don't know today's closing price. Any feature using `close[T]` is using data not yet available.

**Where to check:** `ml/features/` — every feature file. Confirm all rolling windows end at T-1 or earlier, or that the feature is computed post-close and only used at T+1.

**What to look for:**
```python
# SAFE — uses yesterday's close
returns = close.pct_change(1)          # close[T] / close[T-1] - 1 is known by T+1

# SAFE — rolling ends at T
vol = returns.rolling(21).std()        # last data point is close[T-1]

# DANGEROUS — uses today's intraday high/low/open
high_of_day = df["high"]               # not known until market close
```

**Red flag:** Any feature referencing `high`, `low`, or `open` of the same day, used without an execution lag.

---

### A4. Training target leaked as a feature?

**Why it matters:** If `forward_return_42d` accidentally appears in `feature_cols`, the model trains on the exact value it's trying to predict.

**Where to check:** `scripts/run_backtest.py` — where `feature_cols` is defined and passed to the model.

```python
# Verify forward return columns are excluded
assert not any("forward_return" in c for c in feature_cols)
assert not any("target" in c for c in feature_cols)
```

**Data check:**
```python
# Run this on the feature DataFrame before training
import pandas as pd
df = pd.read_parquet("...")  # or load from DB
fwd_cols = [c for c in df.columns if "forward" in c or "target" in c or "fwd" in c]
print("Potential leakage columns:", fwd_cols)
```

**Red flag:** Any future-referencing column name present in `feature_cols`.

---

## B. Survivorship Bias

---

### B1. Are delisted stocks in the training data?

**Why it matters:** If you only train on stocks that survived to today, the model learns to avoid distress signals *after* the fact. Pre-crash patterns look artificially clean.

**Where to check:** `ml/features/_pipeline.py` — `_exclude_delisted()` — confirms stocks are kept until their delisting date, not dropped from history.

**Data check:**
```sql
-- How many delisted stocks are in the database?
SELECT COUNT(*) FROM delisted_stocks;

-- Verify a known delisted stock has pre-delisting price history
SELECT d.stock_code, d.delisting_date, COUNT(p.date) AS trading_days
FROM delisted_stocks d
JOIN daily_prices p ON d.stock_code = p.stock_code
WHERE p.date < d.delisting_date
GROUP BY d.stock_code
LIMIT 10;
```

**Red flag:** `SELECT COUNT(*) FROM delisted_stocks` returns 0 or very few rows. Or delisted stocks have no price history before delisting date.

---

### B2. What return is assigned when a stock delists mid-period?

**Why it matters:** If you hold a stock that delists at T+20 during a 42-day period, the return should be the actual final price — not NaN (which gets dropped, inflating returns) and not 0% (which understates the loss).

**Where to check:** `ml/features/_pipeline.py:821–828` — Fix A and Fix B.

```python
# Fix A: delisted before T+horizon → use last_price
_nm = data[_fwd_col].isna() & data[_pc].gt(0)
data.loc[_nm, _fwd_col] = _last_px[_nm] / data.loc[_nm, _pc] - 1
```

**Data check:**
```sql
-- Find stocks where last price is dramatically lower than entry
-- (confirms crash returns are included, not dropped)
SELECT stock_code,
       MIN(date) AS first_date,
       MAX(date) AS last_date,
       FIRST_VALUE(closing_price) OVER (PARTITION BY stock_code ORDER BY date) AS first_price,
       LAST_VALUE(closing_price)  OVER (PARTITION BY stock_code ORDER BY date
                                        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS last_price
FROM daily_prices
GROUP BY stock_code
HAVING last_price < first_price * 0.1   -- stocks that lost >90%
LIMIT 10;
```

**Red flag:** No stocks with >50% losses in training data. Real markets have bankruptcies.

---

### B3. Universe coverage consistency across years?

**Why it matters:** If early years (2010–2014) have fewer stocks in the DB than later years, early returns look better because the universe is thinner and easier to rank.

**Data check:**
```sql
SELECT strftime('%Y', date) AS year,
       COUNT(DISTINCT stock_code) AS n_stocks,
       AVG(market_cap) AS avg_market_cap,
       COUNT(*) AS total_rows
FROM daily_prices
GROUP BY year
ORDER BY year;
```

**Red flag:** 2010–2013 has significantly fewer stocks than 2018–2025. Expect some drop in early years, but not 50%+ fewer.

---

## C. Overfitting & Walk-Forward Integrity

---

### C1. Is the embargo gap wide enough?

**Why it matters:** With a 42-day holding period, training data from 42 days before test start would contain *future* returns that overlap with the test period. Embargo must be ≥ horizon.

**Where to check:** `scripts/run_backtest.py:1667–1677`

```python
required_embargo = args.horizon + exec_lag   # = 42 + 1 = 43
```

**What to verify manually:**
```python
# In run_backtest.py output, check the printed embargo value
# Should print: "embargo auto-calc: Xd -> 43d"
# If it prints a smaller number, there is leakage
```

**Red flag:** `embargo_days < horizon`. The model would be trained on data whose forward returns overlap with the test window.

---

### C2. Is the validation set drawn from test data?

**Why it matters:** If early stopping (patience=100) uses a validation set that includes test-period data, the model effectively trains on the test set.

**Where to check:** `scripts/run_backtest.py:1256–1262`

```python
val_year = train_years[-1]          # last year of train window = validation
sub_train = train_df[...year != val_year]
val_df    = train_df[...year == val_year]
# test_df is never touched until evaluation
```

**Red flag:** `val_df` contains any dates >= `test_df.date.min()`.

---

### C3. Is the model stable across folds?

**Why it matters:** If model performance varies wildly (e.g., Sharpe 4.5 in 2020, -1.0 in 2021), the average Sharpe is misleading. A consistent model should have smaller year-to-year variance.

**Check the annual table:**
```
| 2017 | 26.36%  | Sharpe 2.06  |
| 2018 | 13.53%  | Sharpe 1.09  |
| 2019 | 10.29%  | Sharpe 0.90  |
| 2020 | 88.77%  | Sharpe 4.48  |  ← outlier year
| 2021 | -8.61%  | Sharpe -0.53 |
| 2022 | -15.66% | Sharpe -1.08 |
| 2023 | 38.04%  | Sharpe 1.62  |
| 2024 | 40.06%  | Sharpe 1.88  |
| 2025 | 26.12%  | Sharpe 2.36  |
```

**What to check:** If 2020 alone accounts for most of the total return (88.77% = COVID recovery boom), remove that year and recompute Sharpe. If it drops from 1.17 to <0.5, the strategy's headline number is driven by a single lucky year.

```python
# Quick check: remove best year and worst year, recompute
results_trimmed = results[~results["year"].isin(["2020"])]
trimmed_return = (1 + results_trimmed["portfolio_return"]).prod() - 1
```

**Red flag:** Removing one year changes total return by >30%.

---

### C4. Parameter sensitivity — are results robust?

**Why it matters:** If the results only work with exactly `horizon=42, top_n=25, buy_rank=20`, the parameters were likely optimised on the test set (even if unintentionally).

**Tests to run:**
```bash
# Vary horizon
python3 scripts/run_backtest.py --horizon 21 --top-n 25 ... --output audit_h21
python3 scripts/run_backtest.py --horizon 63 --top-n 25 ... --output audit_h63

# Vary top-n
python3 scripts/run_backtest.py --horizon 42 --top-n 15 ... --output audit_n15
python3 scripts/run_backtest.py --horizon 42 --top-n 35 ... --output audit_n35

# Vary market cap range
python3 scripts/run_backtest.py --min-market-cap 50000000000  --max-market-cap 500000000000  ... --output audit_small
python3 scripts/run_backtest.py --min-market-cap 200000000000 --max-market-cap 2000000000000 ... --output audit_large
```

**What to check:** Sharpe should remain above 0.8 across most variations. If it only works at one specific setting, it's overfit.

**Red flag:** Sharpe drops below 0.5 when you change any single parameter by 20%.

---

## D. Signal Quality (IC)

---

### D1. Is IC computed on the full universe or only top picks?

**Why it matters:** Computing IC only on selected stocks inflates it — you're measuring correlation after you've already filtered for your best ideas.

**Where to check:** `scripts/run_backtest.py:1438`

```python
# IC is computed BEFORE _build_picks() call — this is correct
ic = day_df[["score_rank", _ret_col]].corr(method="spearman").iloc[0, 1]
# ...
picks, current_holdings, ... = _build_picks(frame=day_df, ...)  # called after
```

**What to verify:**
```python
# Print universe size vs portfolio size at each rebalance
print(f"Universe: {len(day_df)} stocks, Portfolio: {len(picks)} picks")
# Should be something like: Universe: 180 stocks, Portfolio: 25 picks
```

**Red flag:** IC computed after `_build_picks()`, or universe size == portfolio size.

---

### D2. Is IC stable or driven by a few outlier periods?

**Why it matters:** Mean IC of 0.11 could be driven by a handful of rebalances with IC > 0.5 and many near zero. Check the distribution.

**Data check (from results.csv):**
```python
import pandas as pd
results = pd.read_csv("runs/myrun/results.csv")
print(results["ic_spearman"].describe())
print("Negative IC periods:", (results["ic_spearman"] < 0).sum(), "/", len(results))
print("IC > 0.3 periods:", (results["ic_spearman"] > 0.3).sum())
```

**Red flag:** IC standard deviation > 0.20, or >40% of periods have negative IC, or mean IC is being pulled up by 2–3 extreme values.

---

### D3. Does IC decay over time?

**Why it matters:** A factor that worked in 2010–2017 might not work in 2020–2025. If the model is trained on recent years and tested on recent years, decay is hidden.

**Data check:**
```python
results["year"] = results["date"].str[:4]
print(results.groupby("year")["ic_spearman"].mean())
```

**Red flag:** IC drops significantly in the last 2–3 test years compared to early years.

---

## E. Transaction Costs & Liquidity

---

### E1. Are stocks actually liquid enough to trade?

**Why it matters:** The universe includes stocks down to 100B KRW market cap. Some of these trade <500M KRW/day. A 100M KRW position = 20% of daily volume — impossible to fill without moving the price.

**Data check:**
```sql
-- Distribution of daily trading value for stocks in the universe
SELECT
    CASE
        WHEN value < 500000000    THEN '< 500M KRW'
        WHEN value < 2000000000   THEN '500M – 2B KRW'
        WHEN value < 10000000000  THEN '2B – 10B KRW'
        ELSE '> 10B KRW'
    END AS liquidity_bucket,
    COUNT(*) AS row_count,
    COUNT(DISTINCT stock_code) AS n_stocks
FROM daily_prices
WHERE market_cap BETWEEN 100000000000 AND 1000000000000
  AND date >= '20170101'
GROUP BY liquidity_bucket
ORDER BY MIN(value);
```

**Red flag:** >20% of universe rows are in the `< 500M KRW` bucket. These stocks cannot absorb a 100M KRW position without significant market impact.

---

### E2. Does alpha survive realistic transaction costs?

**Why it matters:** The default fees (buy 0.05% + sell 0.25%) do not include bid-ask spread for SMID-cap stocks. Korean SMID-cap spreads are typically 0.10–0.50%.

**Stress test:**
```bash
# Baseline (current fees)
python3 scripts/run_backtest.py --buy-fee 0.05 --sell-fee 0.25 ... --output audit_fees_base

# Realistic (add ~30bps slippage proxy)
python3 scripts/run_backtest.py --buy-fee 0.20 --sell-fee 0.55 ... --output audit_fees_real

# Pessimistic (add ~80bps for illiquid names)
python3 scripts/run_backtest.py --buy-fee 0.50 --sell-fee 1.00 ... --output audit_fees_stress
```

**What to check:** At what fee level does Sharpe drop below 0.5? Below that threshold the strategy is marginal.

---

### E3. Is turnover consistent with the hold-rank setting?

**Why it matters:** hold-rank exists to reduce turnover by protecting existing positions. If turnover is still 60%/rebalance with hold-rank=80, the hysteresis is not working.

**Data check:**
```python
results = pd.read_csv("runs/myrun/results.csv")
print("Avg turnover:", results["turnover"].mean())
print("Turnover distribution:\n", results["turnover"].describe())

# Compare with hold-rank disabled (hold-rank = top-n)
# If turnover is the same, hold-rank logic is broken
```

**Red flag:** Avg turnover > 70% with hold-rank set well above top-n.

---

## F. Benchmark & Alpha Attribution

---

### F1. Is the benchmark appropriate for the strategy universe?

**Why it matters:** Comparing a SMID-cap KOSPI+KOSDAQ strategy against KOSPI 200 (large-cap only) inflates alpha by the size premium and KOSDAQ premium — neither of which comes from model skill.

**Universe vs benchmark:**
| | Strategy | KOSPI 200 |
|---|---|---|
| Size | 100B–1T KRW (SMID) | Top 200 (typically 1T+ KRW) |
| Market | KOSPI + KOSDAQ | KOSPI only |

**Test with fairer benchmarks:**
```bash
python3 scripts/run_backtest.py ... --benchmark universe   --output audit_bench_universe
python3 scripts/run_backtest.py ... --benchmark kosdaq     --output audit_bench_kosdaq
python3 scripts/run_backtest.py ... --benchmark kosdaq150  --output audit_bench_kq150
```

**What to check:** How much alpha remains when you benchmark against your own universe (equal-weight of all investable stocks)?

**Data check:**
```sql
-- Verify KOSDAQ stocks are present in index_constituents
SELECT index_code, COUNT(DISTINCT stock_code) AS n_stocks
FROM index_constituents
WHERE date >= '20170101'
GROUP BY index_code
ORDER BY n_stocks DESC;
```

---

### F2. Is the alpha from the model or from sector/factor exposure?

**Why it matters:** If the portfolio is 50%+ in bio/machinery (as shown in sector attribution), the alpha might just be a KOSDAQ biotech bet that happened to run in 2017–2025.

**Test — remove sector-neutral scoring:**
```bash
# With sector-neutral (current)
python3 scripts/run_backtest.py --sector-neutral ... --output audit_sector_neutral

# Without sector-neutral
python3 scripts/run_backtest.py --no-sector-neutral ... --output audit_no_sector_neutral
```

**Test — restrict to a single sector:**
Run the backtest on only one sector's stocks. If "Special Purpose Machinery" alone produces Sharpe > 1.0, it's sector timing, not quant ranking.

---

## G. Database Integrity

---

### G1. Are prices adjusted for splits and dividends?

**Why it matters:** Unadjusted prices create artificial gaps on split dates. A 5:1 split makes price drop 80% overnight, showing as a massive negative return.

**Data check:**
```sql
-- Find suspicious single-day price drops > 40% (potential unadjusted splits)
SELECT a.stock_code,
       a.date AS date_before,
       a.closing_price AS price_before,
       b.date AS date_after,
       b.closing_price AS price_after,
       (b.closing_price - a.closing_price) / a.closing_price AS pct_change
FROM daily_prices a
JOIN daily_prices b
  ON a.stock_code = b.stock_code
 AND b.date = (SELECT MIN(date) FROM daily_prices
               WHERE stock_code = a.stock_code AND date > a.date)
WHERE pct_change < -0.40
ORDER BY pct_change ASC
LIMIT 20;
```

**Red flag:** Many stocks with single-day drops exactly at round fractions (50%, 33%, 25% = 2:1, 3:1, 4:1 splits).

---

### G2. Are there price data gaps in key periods?

**Why it matters:** Missing data in volatile periods (2020 COVID crash, 2022 bear market) means those periods contributed less to training than they should. Returns look smoother.

**Data check:**
```sql
-- Count trading days per month — gaps show as low counts
SELECT strftime('%Y-%m', date) AS month,
       COUNT(DISTINCT date) AS trading_days
FROM daily_prices
WHERE date >= '20170101'
GROUP BY month
ORDER BY month;
```

**Red flag:** Any month with fewer than 15 trading days (should be ~20). Months with 0–5 days indicate missing data.

---

### G3. Is financial data coverage consistent?

**Why it matters:** If early years have fewer financial filings, features like ROE and GPA will be NaN for most stocks, and the model relies only on price-based signals. This changes what the model actually tests.

**Data check:**
```sql
-- Financial data coverage by year
SELECT strftime('%Y', available_date) AS year,
       COUNT(DISTINCT stock_code) AS n_companies,
       COUNT(*) AS n_filings
FROM financial_periods
GROUP BY year
ORDER BY year;
```

**Red flag:** Financial coverage drops sharply before 2015. If <200 companies have financial data pre-2015, the early backtest years are essentially price-only.

---

### G4. Index constituent coverage check

**Why it matters:** Features like `constituent_index_count` (index membership) depend on the `index_constituents` table being populated for every month. Gaps cause NaN features.

**Data check:**
```sql
-- Check for gaps in monthly constituent snapshots
SELECT strftime('%Y-%m', date) AS month,
       COUNT(DISTINCT index_code) AS n_indices,
       COUNT(DISTINCT stock_code) AS n_stocks
FROM index_constituents
GROUP BY month
ORDER BY month;
```

**Red flag:** Any month missing entirely, or months where `n_indices < 3` (should have KOSPI, KOSPI200, KOSDAQ at minimum).

---

## H. Live Trading vs Backtest Gap

---

### H1. Does the regime filter actually help or just add lag?

**Why it matters:** The 0.02 down capture comes from the cash-out rule. In live trading the 20d MA signal lags the actual market turn by 1–3 weeks. Test what happens when you disable it.

```bash
python3 scripts/run_backtest.py \
  --start 20100101 --end 20260101 --horizon 42 --top-n 25 \
  --train-years 2 --min-market-cap 100000000000 --max-market-cap 1000000000000 \
  --buy-rank 20 --hold-rank 80 --buy-fee 0.05 --sell-fee 0.25 \
  --patience 100 --no-cache --no-cash-out \
  --output audit_no_cashout --save-picks
```

**What to check:** Compare Sharpe and max drawdown. If no-cash-out Sharpe is similar (e.g., 0.9+), the regime filter is adding complexity without proportional benefit.

---

### H2. Does alpha hold at T+1 execution?

**Why it matters:** If returns depend on filling at the exact closing price of the rebalance day, the strategy is not executable — you can't trade at a price that's already set.

**Where to check:** `scripts/run_backtest.py` — `--exec-lag` parameter.

The default config already uses `exec_lag=1` (next-day close). Verify:
```
Exec Lag: T+1 close  [forward_return_42d_lag1_close]  ← Test 1
```

**Red flag:** `exec_lag=0` (same-day close). This is only achievable with a market-on-close order and perfect execution.

---

### H3. Replication test — do picks match reported returns?

**Why it matters:** The reported numbers are only trustworthy if an independent calculation produces the same result.

```bash
python3 verification/verify_backtest.py --run myrun --tolerance 0.05
```

This cross-checks each pick's entry/exit price against Naver Finance adjusted prices. Tolerance of 5% flags trades where the backtest return and the independently-sourced return differ by more than 5%.

**Red flag:** >10% of trades fail the tolerance check, or systematic direction bias (backtest always higher than verification).

---

## Quick Reference — Most Important Checks First

See [DATA_CHECK_TODO.md](../DATA_CHECK_TODO.md) for the current data verification status.

| Priority | Check | Command / Query |
|---|---|---|
| 1 | Financial PIT enforcement | SQL: `available_date <= feature_date` |
| 2 | Delisted stocks in DB | SQL: `SELECT COUNT(*) FROM delisted_stocks` |
| 3 | Forward return order | Code: `shift(-N)` before `_apply_hard_universe_filters` |
| 4 | Embargo width | Code: `embargo >= horizon + exec_lag` |
| 5 | Universe coverage by year | SQL: stocks per year in `daily_prices` |
| 6 | Alpha without regime filter | `--no-cash-out` run |
| 7 | Alpha with fairer benchmark | `--benchmark universe` run |
| 8 | Fee stress test | `--buy-fee 0.20 --sell-fee 0.55` run |
| 9 | Parameter sensitivity | Vary `--horizon`, `--top-n`, `--min-market-cap` |
| 10 | IC distribution | `results["ic_spearman"].describe()` in results.csv |
| 11 | Verification script | `verify_backtest.py --run myrun --tolerance 0.05` |
| 12 | Price split check | SQL: single-day drops > 40% |
