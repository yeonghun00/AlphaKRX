# Backtest Verification Tool

Independently re-verifies backtest results (`picks.csv`) against **FinanceDataReader (Naver Finance)**.

---

## Usage

```bash
# Basic run (by run name)
python3 verification/verify_backtest.py --run myrun

# With 5% tolerance (recommended)
python3 verification/verify_backtest.py --run myrun --tolerance 0.05

# Specify picks.csv directly
python3 verification/verify_backtest.py --picks runs/myrun/picks.csv --tolerance 0.05

# Specify output folder
python3 verification/verify_backtest.py --run myrun --out my_verification_output
```

### All Options

| Option | Default | Description |
|---|---|---|
| `--run NAME` | — | Auto-loads `runs/NAME/picks.csv` |
| `--picks PATH` | — | Direct path to picks.csv |
| `--tolerance FLOAT` | `0.02` | Return difference threshold for match (0.05 = ±5%) |
| `--out PATH` | `verification/` inside picks folder | Output folder |
| `--fwd-col NAME` | auto-detect | Forward return column name (usually auto-detected) |
| `--delay FLOAT` | `0.3` | Seconds between API requests (rate limiting) |

---

## How It Works

### Data Source: Naver Finance Adjusted Prices

```
fdr.DataReader('NAVER:005930', start, end)
```

- **Naver Finance** returns adjusted closing prices — same adjustment direction as pykrx (our ETL)
- KRX source returns raw (unadjusted) closing prices, so it is not used

### Price Reference Alignment

Same basis as the backtest:

| | Backtest (`run_backtest.py`) | Verification Tool |
|---|---|---|
| **Buy price** | `opening_price.shift(-1)` = T+1 open | `_next_open()`: first trading day open after signal date |
| **Sell price** | `opening_price.shift(-(horizon+1))` = T+43 open | `_open_on()`: open on sell date |
| **Sell date** | T+43 date (= `sell_date` column) | Used as-is |

Holiday handling: if no data exists for that date, automatically falls back to the next trading day within 10 calendar days.

---

## Interpreting Results

### Verification Summary

```
Total trade-records             : 660
  Fully verified (both returns)  : 638
    ✅  Match  (|Δ| ≤ 5%)        : 633  (99.2%)
    ⚠️   Discrepancy (|Δ| > 5%)   : 5
  🔴  Delisted / unavailable      : 0
  ❓  No sell date                : 22

Return accuracy:
  Mean   |Δreturn|  : 0.118%
  Median |Δreturn|  : 0.013%
```

### Status Meanings

| Status | Meaning |
|---|---|
| `match` | Difference between FDR and BT return is within tolerance |
| `discrepancy` | Difference exceeds tolerance — see cause analysis below |
| `delisted_or_unavailable` | No data in FDR (delisted or missing) |
| `no_sell_date` | Sell date is NaN — still open position (backtest tail) |
| `fdr_price_missing` | FDR has data but no price for that specific date |
| `bt_return_missing` | No forward return value in picks.csv |

### Recommended Tolerance: `--tolerance 0.05`

`0.02` (2%) is too strict. Reasons:
- pykrx and Naver both use adjusted prices but apply slightly different TERP formulas for rights offerings
- A ~1–2% price level difference between sources accumulates across both buy and sell sides, producing ~2–4% return error

`0.05` (5%) is the practical threshold:
- Systemic errors (code bugs, look-ahead bias) show up as large-scale patterns exceeding this level
- Pure data-provider adjustment factor differences stay within 5%

---

## Discrepancy Root Causes

### 1. Normal — Adjustment Factor Difference Between Data Providers

**Pattern:** `sell_ratio ≈ 1.000`, `buy_ratio ≠ 1.000`

Sell price matches exactly but buy price differs → a corporate action (rights offering, stock split, etc.) occurred near the buy date, and pykrx and Naver applied different adjustment factors.

→ **Not a backtest error.** Both providers correctly compute adjusted prices using their own methodology.

Example:
```
Stock A  20230504  buy_ratio=1.000  ← perfect match
Stock A  20230706  buy_ratio=1.000  ← perfect match
Stock A  20230905  buy_ratio=1.071  ← corporate action near this date
```

### 2. Warning — Corporate Action During Holding Period

**Pattern:** `buy_ratio ≈ 1.000`, `sell_ratio ≈ 1.000` but return signs are opposite

A stock split or rights offering during the holding period changes the price unit. Naver may not retroactively adjust prices at that point. → In these cases **the pykrx-based backtest return is economically correct**.

### 3. Investigate — Both Prices Differ Significantly

When both `buy_ratio` and `sell_ratio` are far from 1.0 and returns differ substantially → investigate that stock's data individually.

---

## Output Files

Saved to `runs/<run>/verification/` (or path specified by `--out`):

| File | Contents |
|---|---|
| `verification_detail.csv` | All trade details (BT prices, FDR prices, return comparison) |
| `discrepancy_report.csv` | Trades exceeding tolerance only |
| `delisted_report.csv` | Delisted / data-unavailable stocks |
| `verification_summary.txt` | Text report matching console output |

---

## Verification Limitations

This tool verifies **data accuracy and return calculation logic** only. Out of scope:

| Factor | Description |
|---|---|
| **Market impact** | Effect of actual buy orders on the order book (small-cap slippage) |
| **Liquidity risk** | Cases where the open price at market open is unavailable |
| **Transaction costs** | Not in picks.csv; handled separately inside the backtest |
| **Delisted stocks** | No FDR data available → recorded separately in `delisted_report.csv` |

---

## myrun Verification Results (as of 2026-02-24)

```
Source: Naver Finance adjusted prices
Tolerance: ±5%
Buy price basis: T+1 open  /  Sell price basis: sell date open

Match rate  : 633/638 = 99.2%
Mean  |Δ|   : 0.118%
Median |Δ|  : 0.013%
Max   |Δ|   : 22.656%  (SNK 950180, corporate action adjustment factor difference)

Conclusion: Backtest calculation logic is correct. Remaining errors are due to
            rights offering adjustment factor differences between data providers
            and have no impact on backtest reliability.
```
