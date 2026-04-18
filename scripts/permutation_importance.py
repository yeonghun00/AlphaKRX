#!/usr/bin/env python3
"""Permutation feature importance across walk-forward folds.

Trains one model per fold (same params as run_backtest.py), then for each
feature shuffles it in the TEST set at prediction time and measures IC drop.
This is O(n_folds) training + O(n_folds * n_features) predictions — roughly
as fast as one backtest run.

Output: ranked table of features by mean IC drop across folds, with fold-by-
fold breakdown to surface regime-specific features (B2 bias investigation).

Usage:
    python3 scripts/permutation_importance.py
    python3 scripts/permutation_importance.py --train-years 3 --db data/krx.db
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.WARNING)


def _ic(scores: np.ndarray, returns: np.ndarray) -> float:
    mask = np.isfinite(scores) & np.isfinite(returns)
    if mask.sum() < 30:
        return float("nan")
    return float(spearmanr(scores[mask], returns[mask]).statistic)


def run(args: argparse.Namespace) -> None:
    from ml.features import FeatureEngineer
    from ml.model import walk_forward_split
    from ml.models import get_model_class

    print(f"[PermImportance] loading data {args.start}~{args.end} ...", flush=True)
    fe = FeatureEngineer(args.db)
    df = fe.prepare_ml_data(
        start_date=args.start,
        end_date=args.end,
        target_horizon=args.horizon,
        min_market_cap=args.min_market_cap,
        use_cache=not args.no_cache,
    )
    if df.empty:
        print("No data available.")
        return

    feature_cols = [c for c in FeatureEngineer.FEATURE_COLUMNS if c in df.columns]
    fwd_col = f"forward_return_{args.horizon}d"
    target_col = f"target_residual_rank_{args.horizon}d"
    if target_col not in df.columns:
        target_col = f"target_rank_{args.horizon}d"

    print(f"[PermImportance] {len(df):,} rows | {len(feature_cols)} features | target={target_col}", flush=True)

    splits = walk_forward_split(df, train_years=args.train_years)
    if not splits:
        print("No walk-forward splits.")
        return

    ModelClass = get_model_class("lgbm")
    params = ModelClass.BEST_PARAMS.copy()
    params["n_jobs"] = -1

    # fold_results[feature] = list of IC drops (one per fold)
    fold_results: dict[str, list[float]] = {f: [] for f in feature_cols}
    baseline_ics: list[float] = []
    fold_years: list[int] = []

    for train_df, test_df, info in splits:
        test_year = int(info["test_year"])
        fold_years.append(test_year)

        # Replicate backtest's val split + embargo
        train_years_list = sorted(train_df["date"].str[:4].unique())
        val_year = train_years_list[-1]
        sub_train = train_df[train_df["date"].str[:4] != val_year]
        val_df = train_df[train_df["date"].str[:4] == val_year]
        if sub_train.empty:
            sub_train, val_df = train_df, None

        # Embargo
        all_dates = sorted(pd.concat([train_df["date"], test_df["date"]]).unique())
        test_start = min(test_df["date"])
        embargo_days = args.horizon + 1
        if test_start in all_dates:
            idx = all_dates.index(test_start)
            if idx > embargo_days:
                cutoff = all_dates[idx - embargo_days]
                sub_train = sub_train[sub_train["date"] < cutoff].copy()
                if val_df is not None:
                    val_df = val_df[val_df["date"] < cutoff].copy()

        if sub_train.empty:
            print(f"[Fold {test_year}] skipped — empty after embargo", flush=True)
            for f in feature_cols:
                fold_results[f].append(float("nan"))
            baseline_ics.append(float("nan"))
            continue

        model = ModelClass(feature_cols=feature_cols, target_col=target_col, time_decay=0.4)
        model.patience = args.patience
        model.train(sub_train, val_df if (val_df is not None and len(val_df) > 100) else None, params=params)

        # Baseline IC on test set (rebalance dates only, same cadence as backtest)
        test_dates = sorted(test_df["date"].unique())[::args.horizon]
        test_rebal = test_df[test_df["date"].isin(test_dates)].copy()
        test_rebal["_score"] = model.predict(test_rebal)
        baseline_ic = _ic(test_rebal["_score"].values, test_rebal[fwd_col].values)
        baseline_ics.append(baseline_ic)
        print(
            f"[Fold {test_year}] trained  best_iter={model.model.best_iteration}  "
            f"baseline_IC={baseline_ic:.4f}  ({len(test_rebal):,} test rows)",
            flush=True,
        )

        rng = np.random.default_rng(seed=42)
        for feat in feature_cols:
            permuted = test_rebal.copy()
            permuted[feat] = rng.permutation(permuted[feat].values)
            permuted["_score_p"] = model.predict(permuted)
            perm_ic = _ic(permuted["_score_p"].values, permuted[fwd_col].values)
            ic_drop = baseline_ic - perm_ic  # positive = feature helped
            fold_results[feat].append(ic_drop)

    # Aggregate
    print("\n" + "=" * 70)
    print("  PERMUTATION FEATURE IMPORTANCE")
    print("=" * 70)
    print(f"  Folds: {fold_years}")
    print(f"  Baseline IC per fold: {[f'{v:.4f}' for v in baseline_ics]}")
    print(f"  Mean baseline IC: {np.nanmean(baseline_ics):.4f}")
    print()

    rows = []
    for feat in feature_cols:
        drops = fold_results[feat]
        valid = [d for d in drops if np.isfinite(d)]
        mean_drop = np.mean(valid) if valid else float("nan")
        std_drop = np.std(valid) if len(valid) > 1 else float("nan")
        # Stability: fraction of folds where feature helps (drop > 0)
        positive_folds = sum(1 for d in valid if d > 0)
        stability = positive_folds / len(valid) if valid else float("nan")
        rows.append({
            "feature": feat,
            "mean_ic_drop": mean_drop,
            "std_ic_drop": std_drop,
            "stability": stability,
            "fold_drops": drops,
        })

    result_df = pd.DataFrame(rows).sort_values("mean_ic_drop", ascending=False).reset_index(drop=True)

    # Print table
    header = f"{'Rank':<5} {'Feature':<40} {'IC Drop':>9} {'Std':>7} {'Stability':>10}  Fold drops"
    print(header)
    print("-" * len(header))
    for i, row in result_df.iterrows():
        fold_str = "  ".join(
            f"{y}:{d:+.4f}" for y, d in zip(fold_years, row["fold_drops"])
        )
        stability_flag = " ⚠ regime" if row["stability"] < 0.5 else ""
        print(
            f"{i+1:<5} {row['feature']:<40} {row['mean_ic_drop']:>+9.4f} "
            f"{row['std_ic_drop']:>7.4f} {row['stability']:>9.0%}  "
            f"{fold_str}{stability_flag}"
        )

    print()
    print("Legend:")
    print("  IC Drop  = baseline IC − permuted IC  (higher = feature contributes more)")
    print("  Stability = fraction of folds where feature helped (drop > 0)")
    print("  ⚠ regime  = feature helps in <50% of folds → regime-specific, may not generalize")

    # Save CSV
    out_path = Path("runs/permutation_importance.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result_df.drop(columns=["fold_drops"]).to_csv(out_path, index=False)
    print(f"\n[PermImportance] results saved → {out_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Permutation feature importance (prediction-level, walk-forward)")
    parser.add_argument("--db", default="data/krx_stock_data.db")
    parser.add_argument("--start", default="20100101")
    parser.add_argument("--end", default="20260101")
    parser.add_argument("--horizon", type=int, default=42)
    parser.add_argument("--train-years", type=int, default=3)
    parser.add_argument("--min-market-cap", type=int, default=200_000_000_000)
    parser.add_argument("--patience", type=int, default=80)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
