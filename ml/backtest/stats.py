from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


def compute_core_stats(results: pd.DataFrame) -> dict:
    """Compute all backtest statistics from results DataFrame."""
    s = {}
    s["n_rebalances"] = len(results)
    s["n_years"] = max(results["year"].nunique(), 1)

    s["total_return"] = (1.0 + results["portfolio_return"]).prod() - 1.0
    s["benchmark_return"] = (1.0 + results["benchmark_return"]).prod() - 1.0
    s["alpha"] = s["total_return"] - s["benchmark_return"]

    cum = (1.0 + results["portfolio_return"]).cumprod()
    drawdown = cum / cum.cummax() - 1.0
    s["max_dd"] = float(drawdown.min())
    s["cum_portfolio"] = cum
    s["cum_benchmark"] = (1.0 + results["benchmark_return"]).cumprod()
    s["drawdown"] = drawdown

    uw = 0
    max_uw = 0
    for flag in (drawdown < 0).tolist():
        uw = uw + 1 if flag else 0
        max_uw = max(max_uw, uw)
    s["max_underwater"] = max_uw

    rebals_per_year = max(len(results) / s["n_years"], 1)
    s["ann_vol"] = float(results["portfolio_return"].std() * np.sqrt(rebals_per_year))
    s["ann_return"] = (1.0 + s["total_return"]) ** (1.0 / s["n_years"]) - 1.0
    s["sharpe"] = s["ann_return"] / s["ann_vol"] if s["ann_vol"] > 0 else 0.0
    s["calmar"] = s["ann_return"] / abs(s["max_dd"]) if s["max_dd"] < 0 else np.nan

    wins = results[results["alpha"] > 0]["alpha"]
    losses = results[results["alpha"] <= 0]["alpha"]
    s["hit_rate"] = float((results["alpha"] > 0).mean())
    s["avg_win"] = float(wins.mean()) if len(wins) > 0 else 0.0
    s["avg_loss"] = float(losses.mean()) if len(losses) > 0 else 0.0
    total_profit = float(wins.sum()) if len(wins) > 0 else 0.0
    total_loss = float(losses.abs().sum()) if len(losses) > 0 else 0.0
    s["profit_factor"] = total_profit / total_loss if total_loss > 0 else np.inf
    s["win_loss_ratio"] = abs(s["avg_win"] / s["avg_loss"]) if s["avg_loss"] != 0 else np.inf

    if "ic_spearman" in results.columns:
        s["ic_mean"] = float(results["ic_spearman"].mean())
        ic_std = float(results["ic_spearman"].std())
        s["ic_ir"] = s["ic_mean"] / ic_std if ic_std > 0 else np.nan
    else:
        s["ic_mean"] = np.nan
        s["ic_ir"] = np.nan

    up_mask = results["benchmark_return"] > 0
    down_mask = results["benchmark_return"] < 0
    if up_mask.sum() > 0:
        s["up_capture"] = float(results.loc[up_mask, "portfolio_return"].mean() / results.loc[up_mask, "benchmark_return"].mean())
    else:
        s["up_capture"] = np.nan
    if down_mask.sum() > 0:
        s["down_capture"] = float(results.loc[down_mask, "portfolio_return"].mean() / results.loc[down_mask, "benchmark_return"].mean())
    else:
        s["down_capture"] = np.nan

    s["rolling_sharpe_12"] = (
        results["portfolio_return"].rolling(12).mean()
        / results["portfolio_return"].rolling(12).std().replace(0, np.nan)
        * np.sqrt(12)
    )

    cov_window = 12
    port_r = results["portfolio_return"]
    bench_r = results["benchmark_return"]
    roll_cov = port_r.rolling(cov_window).cov(bench_r)
    roll_var = bench_r.rolling(cov_window).var()
    s["rolling_beta"] = (roll_cov / roll_var.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    s["overall_beta"] = float(port_r.cov(bench_r) / bench_r.var()) if bench_r.var() > 0 else np.nan

    s["avg_turnover"] = float(results["turnover"].mean()) if "turnover" in results.columns else np.nan
    s["total_tx_cost"] = float(results["transaction_cost"].sum()) if "transaction_cost" in results.columns else np.nan
    s["avg_cash_drag"] = float(results["cash_drag_pct"].mean()) if "cash_drag_pct" in results.columns else np.nan
    s["avg_sl_triggered"] = float(results["sl_triggered_rate"].mean()) if "sl_triggered_rate" in results.columns and results["sl_triggered_rate"].gt(0).any() else 0.0

    annual = results.groupby("year").agg(
        ann_port=("portfolio_return", lambda x: (1 + x).prod() - 1),
        ann_bench=("benchmark_return", lambda x: (1 + x).prod() - 1),
        ann_vol=("portfolio_return", lambda x: x.std() * np.sqrt(max(len(x), 1))),
    )
    annual["ann_alpha"] = annual["ann_port"] - annual["ann_bench"]
    annual["ann_sharpe"] = annual["ann_port"] / annual["ann_vol"].replace(0, np.nan)
    s["annual"] = annual

    if {"q1_ret", "q2_ret", "q3_ret", "q4_ret", "q5_ret"}.issubset(results.columns):
        s["q_means"] = results[["q1_ret", "q2_ret", "q3_ret", "q4_ret", "q5_ret"]].mean()
        s["q_mono"] = bool(
            s["q_means"]["q5_ret"] > s["q_means"]["q4_ret"] > s["q_means"]["q3_ret"]
            > s["q_means"]["q2_ret"] > s["q_means"]["q1_ret"]
        )
    else:
        s["q_means"] = None
        s["q_mono"] = False

    s["sig"] = compute_stat_significance(s, results)

    return s


def compute_stat_significance(s: dict, results: pd.DataFrame) -> dict:
    """Compute statistical significance metrics for the backtest."""
    sig: dict = {}
    port_r = results["portfolio_return"].dropna()
    alpha_r = results["alpha"].dropna() if "alpha" in results.columns else port_r
    n = len(port_r)
    rebals_per_year = max(n / max(s["n_years"], 1), 1)

    r_mean = float(port_r.mean())
    r_std = float(port_r.std(ddof=1))
    if r_std > 0 and n > 1:
        ols_tstat = r_mean / (r_std / np.sqrt(n))
        ols_pval = 2.0 * float(scipy_stats.t.sf(abs(ols_tstat), df=n - 1))
    else:
        ols_tstat = np.nan
        ols_pval = np.nan
    sig["ols_tstat"] = ols_tstat
    sig["ols_pval"] = ols_pval

    nw_lags = max(1, int(np.ceil(4.0 * (n / 100.0) ** (2.0 / 9.0))))
    r_dm = (port_r - r_mean).values
    nw_var = float(np.mean(r_dm ** 2))
    for lag in range(1, nw_lags + 1):
        w = 1.0 - lag / (nw_lags + 1.0)
        gamma = float(np.mean(r_dm[lag:] * r_dm[:-lag]))
        nw_var += 2.0 * w * gamma
    nw_se = np.sqrt(max(nw_var, 0.0) / n)
    if nw_se > 0:
        nw_tstat = r_mean / nw_se
        nw_pval = 2.0 * float(scipy_stats.t.sf(abs(nw_tstat), df=n - 1))
    else:
        nw_tstat = np.nan
        nw_pval = np.nan
    sig["nw_tstat"] = nw_tstat
    sig["nw_pval"] = nw_pval
    sig["nw_lags"] = nw_lags

    sr_period = r_mean / r_std if r_std > 0 else np.nan
    if pd.notna(sr_period):
        sharpe_tstat = sr_period * np.sqrt(n)
        sharpe_pval = 2.0 * float(scipy_stats.t.sf(abs(sharpe_tstat), df=n - 1))
    else:
        sharpe_tstat = np.nan
        sharpe_pval = np.nan
    sig["sharpe_tstat"] = sharpe_tstat
    sig["sharpe_pval"] = sharpe_pval

    if "ic_spearman" in results.columns:
        ic_series = results["ic_spearman"].dropna()
        ic_n = len(ic_series)
        ic_ir = s.get("ic_ir", np.nan)
        if pd.notna(ic_ir) and ic_n > 1:
            ic_tstat = float(ic_ir) * np.sqrt(ic_n)
            ic_pval = 2.0 * float(scipy_stats.t.sf(abs(ic_tstat), df=ic_n - 1))
        else:
            ic_tstat = np.nan
            ic_pval = np.nan
        sig["ic_tstat"] = ic_tstat
        sig["ic_pval"] = ic_pval
    else:
        sig["ic_tstat"] = np.nan
        sig["ic_pval"] = np.nan

    np.random.seed(42)
    n_boot = 2000
    boot_sharpes = []
    for _ in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        boot_r = port_r.iloc[idx]
        boot_mean = boot_r.mean()
        boot_std = boot_r.std(ddof=1)
        if boot_std > 0:
            boot_sharpes.append(boot_mean / boot_std * np.sqrt(rebals_per_year))
    boot_sharpes = np.array(boot_sharpes)
    sig["sharpe_ci_lower"] = float(np.percentile(boot_sharpes, 2.5))
    sig["sharpe_ci_upper"] = float(np.percentile(boot_sharpes, 97.5))

    hit_rate = (alpha_r > 0).mean()
    n_hits = int((alpha_r > 0).sum())
    if n > 0:
        binom_result = scipy_stats.binomtest(n_hits, n, 0.5, alternative="greater")
        binom_pval = float(binom_result.pvalue)
    else:
        binom_pval = np.nan
    sig["binom_pval"] = binom_pval

    n_sig_5pct = sum(
        1 for p in [ols_pval, nw_pval, sharpe_pval, sig.get("ic_pval", np.nan), binom_pval]
        if pd.notna(p) and p < 0.05
    )
    n_sig_1pct = sum(
        1 for p in [ols_pval, nw_pval, sharpe_pval, sig.get("ic_pval", np.nan), binom_pval]
        if pd.notna(p) and p < 0.01
    )
    verdict_note = f"{n_sig_5pct}/5 tests pass at 5%; {n_sig_1pct}/5 pass at 1%"
    sig["verdict_note"] = verdict_note
    sig["n_sig_5pct"] = n_sig_5pct
    sig["n_sig_1pct"] = n_sig_1pct

    return sig


def compute_performance(returns: pd.Series, years: pd.Series | None = None) -> dict:
    """Compute annualized return/vol/sharpe for a return series."""
    r = returns.dropna()
    if r.empty:
        return {"total_return": np.nan, "ann_return": np.nan, "ann_vol": np.nan, "sharpe": np.nan}

    if years is not None:
        y = years.loc[r.index]
        n_years = max(int(y.nunique()), 1)
    else:
        n_years = 1
    rebals_per_year = max(len(r) / n_years, 1)

    total_return = float((1.0 + r).prod() - 1.0)
    ann_return = float((1.0 + total_return) ** (1.0 / n_years) - 1.0)
    ann_vol = float(r.std() * np.sqrt(rebals_per_year))
    sharpe = ann_return / ann_vol if ann_vol > 0 else np.nan
    return {
        "total_return": total_return,
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
    }


def parse_exclude_years(raw: str) -> set[str]:
    years: set[str] = set()
    if not raw:
        return years
    for token in raw.split(","):
        t = token.strip()
        if len(t) == 4 and t.isdigit():
            years.add(t)
    return years
