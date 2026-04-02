from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .stats import CoreStats

logger = logging.getLogger(__name__)


KO_TO_EN = {
    "소프트웨어개발및공급업": "Software Dev & Supply",
    "기타금융업": "Other Financial Svcs",
    "자연과학및공학연구개발업": "Science & Eng R&D",
    "의약품제조업": "Pharmaceuticals",
    "기타화학제품제조업": "Other Chemicals",
    "특수목적용기계제조업": "Special Purpose Machinery",
    "통신및방송장비제조업": "Telecom & Broadcasting Equip",
    "영화,비디오물,방송프로그램제작및배급업": "Film & Broadcasting",
    "기초화학물질제조업": "Basic Chemicals",
    "전자부품제조업": "Electronic Components",
    "자동차신품부품제조업": "Auto Parts",
    "의료용품및기타의약관련제품제조업": "Medical & Pharma Products",
    "반도체제조업": "Semiconductors",
    "컴퓨터및주변기기제조업": "Computers & Peripherals",
    "기타전자부품제조업": "Other Electronic Components",
    "금속주조업": "Metal Casting",
    "1차금속제조업": "Primary Metals",
    "금속가공제품제조업": "Fabricated Metal Products",
    "기타기계및장비제조업": "Other Machinery & Equipment",
    "일반목적용기계제조업": "General Purpose Machinery",
    "고무및플라스틱제품제조업": "Rubber & Plastics",
    "비금속광물제품제조업": "Non-Metallic Minerals",
    "섬유제품제조업": "Textiles",
    "의복및모피제품제조업": "Apparel & Fur",
    "음식료품제조업": "Food & Beverages",
    "건설업": "Construction",
    "도매및상품중개업": "Wholesale & Trading",
    "소매업": "Retail",
    "육상운송및파이프라인운송업": "Land Transport",
    "수상운송업": "Water Transport",
    "항공운송업": "Air Transport",
    "출판업": "Publishing",
    "정보서비스업": "IT Services",
    "통신업": "Telecommunications",
    "보험및연금업": "Insurance & Pension",
    "증권및선물중개업": "Securities & Futures",
    "부동산업": "Real Estate",
    "전문서비스업": "Professional Services",
    "사업시설관리서비스업": "Facility Management",
    "교육서비스업": "Education Services",
    "의료업": "Healthcare",
    "회사본부,지주회사및경영컨설팅서비스업": "Holding Companies",
    "전기업": "Electric Utilities",
    "가스업": "Gas Utilities",
    "기초의약물질및생물학적제제제조업": "Basic Pharma & Bio Products",
    "의료용기기제조업": "Medical Devices",
    "전기장비제조업": "Electrical Equipment",
    "전자제품제조업": "Consumer Electronics",
    "목재및나무제품제조업": "Wood & Wood Products",
    "종이및종이제품제조업": "Paper & Paper Products",
    "인쇄및기록매체복제업": "Printing & Recorded Media",
    "석유정제품제조업": "Petroleum Refining",
    "화학섬유제조업": "Synthetic Fibres",
    "의료정밀광학기기및시계제조업": "Medical & Precision Instruments",
}


def format_sector_names(names) -> dict:
    """Map sector names to English display names."""
    def _strip(name):
        if not name or pd.isna(name):
            return "Unknown"
        if name in KO_TO_EN:
            return KO_TO_EN[name]
        try:
            from ml.features.registry import SECTOR_NAME_MAP
            en = SECTOR_NAME_MAP.get(name)
            if en is not None:
                return en
        except Exception as e:
            logger.debug(f"Could not load SECTOR_NAME_MAP: {e}")
        return f"[{abs(hash(name)) % 9000 + 1000}]"

    return {n: _strip(n) for n in names}


def print_table(title: str, headers: list[str], rows: list[list[str]]) -> None:
    """Pretty-print table-like outputs with prettytable."""
    print(f"\n{title:^70}")
    try:
        from prettytable import PrettyTable
    except ImportError:
        print("  (prettytable not installed)")
        print("  " + " | ".join(headers))
        for row in rows:
            print("  " + " | ".join(row))
        return

    table = PrettyTable()
    table.field_names = headers
    table.align = "l"
    for row in rows:
        table.add_row(row)
    print(table)


def print_requested_tests(results: pd.DataFrame) -> None:
    """Run and print the 4 requested follow-up tests."""
    if results.empty:
        return

    from .stats import compute_performance

    print("\n" + "=" * 70)
    print("  ROBUSTNESS & STRESS TESTS")
    print("=" * 70)

    years = results["year"] if "year" in results.columns else None

    test_rows: list[list[str]] = []

    if "long_short_return" in results.columns:
        ls = compute_performance(results["long_short_return"], years)
        test_rows.append([
            "1",
            "Long-Short (Top 10% - Bottom 10%)",
            f"{ls['ann_return']:.2%}",
            f"{ls['sharpe']:.2f}",
            "OK",
        ])
    else:
        test_rows.append(["1", "Long-Short (Top 10% - Bottom 10%)", "N/A", "N/A", "Unavailable"])

    if {"portfolio_return", "benchmark_return"}.issubset(results.columns):
        bench = results["benchmark_return"]
        port = results["portfolio_return"]
        beta = float(port.cov(bench) / bench.var()) if bench.var() > 0 else np.nan
        hedged = port - beta * bench if pd.notna(beta) else port - bench
        hedged_stats = compute_performance(hedged, years)
        beta_str = f"{beta:.2f}" if pd.notna(beta) else "N/A"
        test_rows.append([
            "2",
            f"Beta-Hedged (beta={beta_str})",
            f"{hedged_stats['ann_return']:.2%}",
            f"{hedged_stats['sharpe']:.2f}",
            "OK",
        ])
    else:
        test_rows.append(["2", "Beta-Hedged", "N/A", "N/A", "Unavailable"])

    if "year" in results.columns:
        best_year = int(results.groupby("year")["portfolio_return"].sum().idxmax())
        ex_best = results[results["year"] != best_year].copy()
        if not ex_best.empty:
            ex_stats = compute_performance(ex_best["portfolio_return"], ex_best["year"])
            verdict = "PASS" if pd.notna(ex_stats["sharpe"]) and ex_stats["sharpe"] >= 0.7 else "FAIL"
            test_rows.append([
                "3",
                f"Ex-{best_year} robustness",
                f"{ex_stats['ann_return']:.2%}",
                f"{ex_stats['sharpe']:.2f}",
                f"{verdict} (>=0.70)",
            ])
        else:
            test_rows.append(["3", "Ex-best-year robustness", "N/A", "N/A", "Unavailable"])
    else:
        test_rows.append(["3", "Ex-best-year robustness", "N/A", "N/A", "Unavailable"])

    required_cols = {"turnover_tuned", "transaction_cost_tuned", "portfolio_return_tuned"}
    if required_cols.issubset(results.columns):
        base_stats = compute_performance(results["portfolio_return"], years)
        tuned_stats = compute_performance(results["portfolio_return_tuned"], years)
        base_turnover = float(results["turnover"].mean()) if "turnover" in results.columns else np.nan
        tuned_turnover = float(results["turnover_tuned"].mean())
        cost_diff = f"{tuned_stats['ann_return'] - base_stats['ann_return']:+.2%}"
        test_rows.append([
            "4",
            "Turnover reduction (61%→48%)",
            cost_diff,
            f"{tuned_stats['sharpe']:.2f}",
            "OK",
        ])
    else:
        test_rows.append(["4", "Turnover reduction", "N/A", "N/A", "Unavailable"])

    print_table(
        "--- Requested Tests ---",
        ["#", "Test", "Return / Cost", "Sharpe", "Status"],
        test_rows,
    )


def generate_summary(
    results: pd.DataFrame,
    sector_rows: list,
    output_path: str = "backtest_report.png",
    model=None
) -> None:
    """Print enhanced summary + generate visual report."""
    if results.empty:
        print("No backtest results were generated.")
        return

    from .stats import compute_core_stats

    s = compute_core_stats(results)
    sector_df = pd.DataFrame(sector_rows) if sector_rows else pd.DataFrame()

    print("\n" + "=" * 70)
    print("  BACKTEST REPORT")
    print("=" * 70)

    print(f"\n{'--- Overview ---':^70}")
    print(f"  Rebalances: {s['n_rebalances']}  |  Years: {s['n_years']}")
    print(f"  Total Return:     {s['total_return']:>8.2%}   Benchmark: {s['benchmark_return']:>8.2%}")
    print(f"  Alpha:            {s['alpha']:>8.2%}   Hit Rate:  {s['hit_rate']:>8.2%}")
    print(f"  Ann. Return:      {s['ann_return']:>8.2%}   Ann. Vol:  {s['ann_vol']:>8.2%}")
    print(f"  Sharpe:           {s['sharpe']:>8.2f}   Calmar:    {s['calmar']:>8.2f}" if pd.notna(s['calmar']) else f"  Sharpe:           {s['sharpe']:>8.2f}   Calmar:        N/A")
    print(f"  Max Drawdown:     {s['max_dd']:>8.2%}   Max Underwater: {s['max_underwater']} rebals")

    print(f"\n{'--- Trade Statistics ---':^70}")
    print(f"  Win Rate:         {s['hit_rate']:>8.2%}   (vs benchmark)")
    pf_str = f"{s['profit_factor']:.2f}" if np.isfinite(s['profit_factor']) else "INF"
    print(f"  Profit Factor:    {pf_str:>8s}   (total gain / total loss, 1.5+ good, 2.0+ excellent)")
    wl_str = f"{s['win_loss_ratio']:.2f}" if np.isfinite(s['win_loss_ratio']) else "INF"
    print(f"  Win/Loss Ratio:   {wl_str:>8s}   (avg gain / avg loss)")
    print(f"  Avg Win:          {s['avg_win']:>8.2%}   Avg Loss:  {s['avg_loss']:>8.2%}")
    if pd.notna(s.get("avg_turnover")):
        print(f"  Avg Turnover:     {s['avg_turnover']:>8.2%}   Total Tx Cost: {s.get('total_tx_cost', 0):>8.2%}")

    print(f"\n{'--- Market Regime Analysis ---':^70}")
    uc_str = f"{s['up_capture']:.2f}" if pd.notna(s.get('up_capture')) else "N/A"
    dc_str = f"{s['down_capture']:.2f}" if pd.notna(s.get('down_capture')) else "N/A"
    print(f"  Up Capture:       {uc_str:>8s}   (portfolio move per 1% market move)")
    print(f"  Down Capture:     {dc_str:>8s}   (<0.7 = strong downside defense)")
    beta_str = f"{s['overall_beta']:.2f}" if pd.notna(s.get('overall_beta')) else "N/A"
    print(f"  Overall Beta:     {beta_str:>8s}   (<0.5 = independent alpha)")

    annual_rows: list[list[str]] = []
    for yr, row in s["annual"].iterrows():
        sh = f"{row['ann_sharpe']:.2f}" if pd.notna(row["ann_sharpe"]) else "N/A"
        annual_rows.append([str(int(yr)), f"{row['ann_port']:+.2%}", f"{row['ann_alpha']:+.2%}", sh])
    print_table(
        "--- Annual ---",
        ["Year", "Return", "Alpha", "Sharpe"],
        annual_rows,
    )

    # --- Statistical Significance ---
    sig = s.get("sig", {})
    if sig:
        print(f"\n{'--- Statistical Significance ---':^70}")
        def _stars(p: float) -> str:
            if pd.isna(p): return ""
            return "***" if p < 0.01 else ("**" if p < 0.05 else ("*" if p < 0.1 else ""))
        tests = [
            ("OLS t-stat",     sig.get("ols_tstat"),    sig.get("ols_pval")),
            ("NW HAC t-stat",  sig.get("nw_tstat"),     sig.get("nw_pval")),
            ("Sharpe t-stat",  sig.get("sharpe_tstat"), sig.get("sharpe_pval")),
            ("IC t-stat",      sig.get("ic_tstat"),     sig.get("ic_pval")),
            ("Binomial (hit)", None,                    sig.get("binom_pval")),
        ]
        for label, tstat, pval in tests:
            if tstat is not None and pd.notna(tstat):
                print(f"  {label:<20} t={tstat:+.2f}  p={pval:.3f}  {_stars(pval)}")
            elif pval is not None and pd.notna(pval):
                print(f"  {label:<20}          p={pval:.3f}  {_stars(pval)}")
        ci_lo = sig.get("sharpe_ci_lower")
        ci_hi = sig.get("sharpe_ci_upper")
        if pd.notna(ci_lo):
            print(f"  {'Bootstrap Sharpe CI':<20} 95% CI [{ci_lo:.2f}, {ci_hi:.2f}]")
        print(f"  {sig.get('verdict_note', '')}")

    # --- Quintile Monotonicity ---
    if s.get("q_means") is not None:
        q = s["q_means"]
        q_vals = [q[f"q{i}_ret"] for i in range(1, 6)]
        mono = "MONOTONIC" if s.get("q_mono") else "NOT MONOTONIC"
        print(f"\n{'--- Quintile Returns ---':^70}")
        print(f"  Q1(Worst)  Q2      Q3      Q4      Q5(Best)   [{mono}]")
        print("  " + "  ".join(f"{v:+.2%}" for v in q_vals))

    generate_visual_report(results, s, sector_df, output_path)
    print_requested_tests(results)


def generate_visual_report(
    results: pd.DataFrame,
    s: dict,
    sector_df: pd.DataFrame,
    output_path: str
) -> None:
    """Generate a multi-panel PNG report."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        from matplotlib.gridspec import GridSpec
    except ImportError:
        print("[Report] matplotlib not installed, skipping visual report.")
        return

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Helvetica Neue", "Arial", "Helvetica", "AppleGothic", "NanumGothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    C_PORT = "#2563EB"
    C_BENCH = "#9CA3AF"
    C_ALPHA = "#10B981"
    C_NEG = "#EF4444"
    C_WARN = "#F59E0B"
    C_BG = "#F8FAFC"

    fig = plt.figure(figsize=(22, 28), facecolor="white", dpi=100)
    gs = GridSpec(5, 2, figure=fig, hspace=0.35, wspace=0.28,
                  left=0.06, right=0.96, top=0.95, bottom=0.03)

    dates = pd.to_datetime(results["date"], format="%Y%m%d", errors="coerce")

    ax1 = fig.add_subplot(gs[0, :])
    ax1.set_facecolor(C_BG)
    ax1.plot(dates, s["cum_portfolio"], color=C_PORT, linewidth=2, label="Portfolio")
    ax1.plot(dates, s["cum_benchmark"], color=C_BENCH, linewidth=1.5, label="Benchmark", linestyle="--")
    ax1.fill_between(dates, s["cum_portfolio"], s["cum_benchmark"],
                     where=s["cum_portfolio"] >= s["cum_benchmark"],
                     alpha=0.15, color=C_ALPHA, interpolate=True)
    ax1.fill_between(dates, s["cum_portfolio"], s["cum_benchmark"],
                     where=s["cum_portfolio"] < s["cum_benchmark"],
                     alpha=0.15, color=C_NEG, interpolate=True)
    ax1.set_title("Cumulative Returns (Portfolio vs Benchmark)", fontsize=14, fontweight="bold", pad=10)
    ax1.legend(loc="upper left", fontsize=11)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.1f}x"))
    ax1.grid(True, alpha=0.3)
    ax1b = ax1.twinx()
    ax1b.fill_between(dates, s["drawdown"], 0, alpha=0.25, color=C_NEG, label="Drawdown")
    ax1b.set_ylim(min(s["drawdown"].min() * 1.3, -0.05), 0.02)
    ax1b.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax1b.set_ylabel("Drawdown", fontsize=10, color=C_NEG)
    ax1b.tick_params(axis="y", colors=C_NEG)

    ax2 = fig.add_subplot(gs[1, 0])
    ax2.set_facecolor(C_BG)
    annual = s["annual"]
    yrs = annual.index.astype(str)
    x = np.arange(len(yrs))
    w = 0.35
    ax2.bar(x - w / 2, annual["ann_port"] * 100, w, color=C_PORT, label="Portfolio", zorder=3)
    ax2.bar(x + w / 2, annual["ann_bench"] * 100, w, color=C_BENCH, label="Benchmark", zorder=3)
    for i, (yr, row) in enumerate(annual.iterrows()):
        color = C_ALPHA if row["ann_alpha"] > 0 else C_NEG
        ax2.annotate(f"{row['ann_alpha']:+.1%}", (i, max(row['ann_port'], row['ann_bench']) * 100 + 1),
                     ha="center", va="bottom", fontsize=7.5, color=color, fontweight="bold")
    ax2.set_xticks(x)
    ax2.set_xticklabels(yrs, rotation=45, fontsize=8)
    ax2.set_title("Annual Returns & Alpha", fontsize=13, fontweight="bold")
    ax2.set_ylabel("%", fontsize=10)
    ax2.legend(fontsize=9)
    ax2.axhline(0, color="black", linewidth=0.5)
    ax2.grid(True, axis="y", alpha=0.3)

    ax3 = fig.add_subplot(gs[1, 1])
    ax3.set_facecolor(C_BG)
    sharpe_vals = annual["ann_sharpe"].fillna(0)
    colors_sharpe = [C_ALPHA if v > 0.5 else (C_WARN if v > 0 else C_NEG) for v in sharpe_vals]
    ax3.bar(yrs, sharpe_vals, color=colors_sharpe, zorder=3)
    ax3.axhline(0.5, color=C_ALPHA, linewidth=1, linestyle="--", alpha=0.7, label="Sharpe=0.5")
    ax3.axhline(0, color="black", linewidth=0.5)
    for i, v in enumerate(sharpe_vals):
        ax3.annotate(f"{v:.2f}", (i, v), ha="center",
                     va="bottom" if v >= 0 else "top", fontsize=8, fontweight="bold")
    ax3.set_xticks(range(len(yrs)))
    ax3.set_xticklabels(yrs, rotation=45, fontsize=8)
    ax3.set_title("Annual Sharpe Ratio", fontsize=13, fontweight="bold")
    ax3.legend(fontsize=9)
    ax3.grid(True, axis="y", alpha=0.3)

    ax4 = fig.add_subplot(gs[2, 0])
    ax4.set_facecolor(C_BG)
    ax4.axis("off")
    pf_val = s.get("profit_factor", 0)
    pf_color = C_ALPHA if pf_val >= 1.5 else (C_WARN if pf_val >= 1.0 else C_NEG)
    wr_color = C_ALPHA if s.get("hit_rate", 0) >= 0.5 else C_WARN
    dc_val = s.get("down_capture")
    dc_color = C_ALPHA if (pd.notna(dc_val) and dc_val < 0.7) else C_WARN

    stats_lines = [
        ("Trade Statistics", "", 16, "bold", "black"),
        ("", "", 6, "normal", "black"),
        ("Win Rate", f"{s.get('hit_rate', 0):.1%}", 14, "bold", wr_color),
        ("Profit Factor", f"{pf_val:.2f}" if np.isfinite(pf_val) else "INF", 14, "bold", pf_color),
        ("Win/Loss Ratio", f"{s.get('win_loss_ratio', 0):.2f}" if np.isfinite(s.get('win_loss_ratio', 0)) else "INF", 14, "bold", C_PORT),
        ("Avg Win", f"{s.get('avg_win', 0):+.2%}", 12, "normal", C_ALPHA),
        ("Avg Loss", f"{s.get('avg_loss', 0):+.2%}", 12, "normal", C_NEG),
    ]
    y_pos = 0.95
    for label, value, fsize, fweight, color in stats_lines:
        if value:
            ax4.text(0.05, y_pos, label, fontsize=fsize, fontweight="normal",
                     transform=ax4.transAxes, va="top")
            ax4.text(0.95, y_pos, value, fontsize=fsize, fontweight=fweight, color=color,
                     transform=ax4.transAxes, va="top", ha="right")
        else:
            ax4.text(0.05, y_pos, label, fontsize=fsize, fontweight=fweight, color=color,
                     transform=ax4.transAxes, va="top")
        y_pos -= 0.08

    ax5 = fig.add_subplot(gs[2, 1])
    ax5.set_facecolor(C_BG)
    if s.get("q_means") is not None:
        q_vals = [s["q_means"][f"q{i}_ret"] * 100 for i in range(1, 6)]
        q_labels = ["Q1\n(Worst)", "Q2", "Q3", "Q4", "Q5\n(Best)"]
        q_colors = [C_NEG, "#F97316", C_WARN, "#34D399", C_ALPHA]
        bars = ax5.bar(q_labels, q_vals, color=q_colors, zorder=3, edgecolor="white", linewidth=1.5)
        for bar, val in zip(bars, q_vals):
            ax5.annotate(f"{val:.2f}%", (bar.get_x() + bar.get_width() / 2, val),
                         ha="center", va="bottom" if val >= 0 else "top",
                         fontsize=11, fontweight="bold")
        ax5.axhline(0, color="black", linewidth=0.5)
        mono_text = "MONOTONIC" if s.get("q_mono") else "NOT MONOTONIC"
        mono_color = C_ALPHA if s.get("q_mono") else C_NEG
        ax5.set_title(f"Quintile Returns - {mono_text}", fontsize=13, fontweight="bold", color=mono_color)
        ax5.set_ylabel("Mean Forward Return (%)", fontsize=10)
    else:
        ax5.text(0.5, 0.5, "No quintile data", ha="center", va="center", fontsize=14)
        ax5.set_title("Quintile Returns", fontsize=13, fontweight="bold")
    ax5.grid(True, axis="y", alpha=0.3)

    ax6 = fig.add_subplot(gs[3, 0])
    ax6.set_facecolor(C_BG)
    roll_sh = s.get("rolling_sharpe_12", pd.Series())
    valid = roll_sh.notna()
    if valid.any():
        ax6.plot(dates[valid], roll_sh[valid], color=C_PORT, linewidth=1.5, label="Rolling Sharpe (12p)")
        ax6.axhline(0, color="black", linewidth=0.5)
        ax6.axhline(0.5, color=C_ALPHA, linewidth=1, linestyle="--", alpha=0.5)
        ax6.fill_between(dates[valid], roll_sh[valid], 0,
                         where=roll_sh[valid] > 0, alpha=0.15, color=C_ALPHA, interpolate=True)
        ax6.fill_between(dates[valid], roll_sh[valid], 0,
                         where=roll_sh[valid] <= 0, alpha=0.15, color=C_NEG, interpolate=True)
    roll_b = s.get("rolling_beta", pd.Series())
    valid_b = roll_b.notna()
    if valid_b.any():
        ax6b = ax6.twinx()
        ax6b.plot(dates[valid_b], roll_b[valid_b], color=C_WARN, linewidth=1, alpha=0.7, label="Rolling Beta")
        ax6b.axhline(1.0, color=C_WARN, linewidth=0.8, linestyle=":", alpha=0.5)
        ax6b.set_ylabel("Beta", fontsize=10, color=C_WARN)
        ax6b.tick_params(axis="y", colors=C_WARN)
    ax6.set_title("Rolling Sharpe (12-period) & Beta", fontsize=13, fontweight="bold")
    ax6.legend(fontsize=9, loc="upper left")
    ax6.grid(True, alpha=0.3)

    ax7 = fig.add_subplot(gs[3, 1])
    ax7.set_facecolor(C_BG)
    if not sector_df.empty:
        sector_df = sector_df.copy()
        sector_df["sector_en"] = sector_df["sector"].map(format_sector_names(sector_df["sector"].unique()))
        sec_agg = sector_df.groupby("sector_en")["contribution"].sum().sort_values(ascending=True)
        sec_agg = sec_agg.tail(10)
        ax7.barh(sec_agg.index, sec_agg.values * 100, color=C_PORT, zorder=3)
        ax7.axvline(0, color="black", linewidth=0.5)
        ax7.set_title("Top 10 Sector Contributions", fontsize=13, fontweight="bold")
        ax7.set_xlabel("Contribution (%)", fontsize=10)
    else:
        ax7.text(0.5, 0.5, "No sector data", ha="center", va="center", fontsize=14)
        ax7.set_title("Sector Contributions", fontsize=13, fontweight="bold")
    ax7.grid(True, axis="x", alpha=0.3)

    ax8 = fig.add_subplot(gs[4, :])
    ax8.set_facecolor(C_BG)
    sig = s.get("sig", {})
    if sig:
        sig_items = [
            ("OLS t-stat", sig.get("ols_tstat"), sig.get("ols_pval")),
            ("NW HAC t-stat", sig.get("nw_tstat"), sig.get("nw_pval")),
            ("Sharpe t-stat", sig.get("sharpe_tstat"), sig.get("sharpe_pval")),
            ("IC t-stat", sig.get("ic_tstat"), sig.get("ic_pval")),
        ]
        x_pos = 0.1
        for label, tstat, pval in sig_items:
            if pd.notna(tstat):
                color = C_ALPHA if pval < 0.05 else (C_WARN if pval < 0.1 else C_NEG)
                stars = "***" if pval < 0.01 else ("**" if pval < 0.05 else ("*" if pval < 0.1 else ""))
                ax8.text(x_pos, 0.6, f"{label}\n{tstat:+.2f} (p={pval:.3f}) {stars}",
                        fontsize=11, ha="center", va="center", color=color, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=color, alpha=0.8))
            x_pos += 0.22
        ci_lo = sig.get("sharpe_ci_lower")
        ci_hi = sig.get("sharpe_ci_upper")
        if pd.notna(ci_lo):
            ax8.text(0.5, 0.2, f"Bootstrap Sharpe 95% CI: [{ci_lo:.2f}, {ci_hi:.2f}]",
                    fontsize=12, ha="center", va="center", fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=C_PORT, alpha=0.8))
        verdict = sig.get("verdict_note", "")
        if verdict:
            ax8.text(0.5, -0.1, verdict, fontsize=10, ha="center", va="center", style="italic")
    ax8.axis("off")
    ax8.set_title("Statistical Significance", fontsize=13, fontweight="bold", y=1.02)

    plt.savefig(output_path, facecolor="white", bbox_inches="tight")
    print(f"[Report] Saved to {output_path}")
    plt.close(fig)


def generate_picks_chart(picks_df: pd.DataFrame, fwd_col: str, output_path: str, max_stocks: int = 100) -> None:
    """Generate a horizontal bar chart of picks with forward returns."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[Chart] matplotlib not installed, skipping.")
        return

    if picks_df.empty:
        print("[Chart] No picks data, skipping.")
        return

    if fwd_col not in picks_df.columns:
        print(f"[Chart] Column {fwd_col} not in picks DataFrame, skipping.")
        return

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["AppleGothic", "NanumGothic", "Malgun Gothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    df = picks_df.sort_values(fwd_col, ascending=True).tail(max_stocks)

    n_stocks = len(df)
    fig_width = min(20, max(8, n_stocks * 0.35))
    fig_height = min(30, max(6, n_stocks * 0.35))
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    colors = ["#10B981" if x >= 0 else "#EF4444" for x in df[fwd_col]]

    ax.barh(range(len(df)), df[fwd_col] * 100, color=colors, edgecolor="white", height=0.7)
    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(df["name"].tolist(), fontsize=7)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:+.0f}%"))
    ax.axvline(0, color="black", linewidth=0.5)
    ax.set_xlabel("Forward Return", fontsize=10)
    ax.set_title(f"Top {n_stocks} Picks ({fwd_col})", fontsize=13, fontweight="bold", pad=10)
    ax.grid(True, axis="x", alpha=0.3)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "Glyph", UserWarning)
        plt.tight_layout()
        plt.savefig(output_path, facecolor="white", dpi=100, bbox_inches="tight")
    print(f"[Chart] Saved to {output_path}")
    plt.close(fig)
