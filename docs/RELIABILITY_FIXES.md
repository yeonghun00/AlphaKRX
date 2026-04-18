# Reliability Fixes Checklist

Issues identified 2026-04-18. Fix in order: code fixes first, then methodology.

---

## Quick Code Fixes

- [x] **#1 Volatility filter pre-split** (`run_backtest.py:~590`)
  - Bug: `--stress-mode` vol filter applied globally before walk-forward splits → test-set stocks filtered using future vol quantiles
  - Fix: move filter inside fold loop, compute quantile on train_df only

- [x] **#2 Embargo uses calendar dates not trading days** (`run_backtest.py:~97`)
  - Bug: `all_dates[idx - embargo_days]` indexes sorted calendar-date list; embargo gap may land on weekends/holidays
  - Fix: build trading-day list from actual data, index into that instead

- [x] **#3 Financial staleness 450 → 180 days** (`ml/features/_pipeline.py:572`)
  - Bug: a filing stays active for 15 months; realistic reporting lag is 30–90 days
  - Fix: changed `> 450` to `> 180` (180 optimal: 120 dropped too many slow annual filers)

- [x] **#4 Latest model trained without embargo** (`scripts/run_backtest.py:~1073`)
  - Bug: final `model.pkl` trained on full latest train set, no embargo applied unlike fold training
  - Fix: apply `cutoff = max(train_df["date"]) - 21 trading days` before training final model

---

## Methodology Changes

- [x] **#5 Hyperparameter + feature selection bias**
  - Bug: params and surviving features both chosen by iterating across all folds; no blind holdout
  - Fix: `--holdout-start-year 2024` skips 2024-2026 test folds during dev; remove flag exactly once for the final honest Sharpe

- [x] **#6 Slippage / transaction cost underestimation**
  - Bug: only fixed 0.05%/0.25% commission; bid-ask spread not modeled
  - Fix: `--slippage-pct` adds a flat % to both buy and sell fees; typical SMID-cap range 0.10–0.50%
  - Recommended test: run with `--slippage-pct 0.3` for a realistic baseline

---

## Accept and Document

- [x] **#3b Quintile non-monotonicity (Q2>Q3)**
  - Root cause: statistical noise — only 50 rebalance points; Q2/Q3 boundary 0.72% difference is within sampling variance
  - Two-stage KOSPI/KOSDAQ re-ranking is active and correctly implemented; no code fix needed
  - Key signal intact: Q5 (3.75%) >> Q1 (2.41%), Q5>Q4>Q3 holds

- [x] **#7 2020 event dependency**
  - Not fixable; run backtest ex-2020 and report both numbers as honest disclosure
  - Threshold: if ex-2020 Sharpe ≥ 0.8, strategy still has a case

- [x] **#8 Liquidity capacity wall**
  - Already documented: Sharpe collapses 2.04→0.50 at 10B KRW daily volume filter
  - Operational limit: AUM ≤ 5–15B KRW enforced in live trading
