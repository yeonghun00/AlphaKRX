"""Regime-aware earnings quality (accruals) feature.

Accrual ratio = (net_income - operating_cf) / |net_income|
  - Positive: earnings exceed cash flow → low quality (accruals-driven)
  - Negative: cash flow exceeds earnings → high quality

Regime flip: multiply by sign(market_regime_120d).
  - Bull (regime > 0): high accruals = bad → model learns negative weight → correct
  - Bear (regime < 0): feature flips sign, same negative weight → long high-accrual
    cash-burners recovering — matches the COVID-bounce empirical pattern

Previous attempts (v1, v2) failed because the 2020 val set (COVID bounce) had
opposite signal direction, triggering best_iter=1. The regime flip bakes the
sign inversion into the feature itself so the model sees a consistent relationship.

Depends on: net_income, operating_cf (merged by pipeline), market_regime_120d
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .registry import FeatureGroup, register


@register
class EarningsQualityFeatures(FeatureGroup):
    name = "earnings_quality"
    columns = ["accrual_regime_aware"]
    dependencies = []  # net_income, operating_cf, market_regime_120d merged by pipeline

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        required = {"net_income", "operating_cf", "market_regime_120d"}
        if not required.issubset(df.columns):
            df["accrual_regime_aware"] = 0.0
            return df

        ni = pd.to_numeric(df["net_income"], errors="coerce")
        cf = pd.to_numeric(df["operating_cf"], errors="coerce")

        # Dimensionless accrual ratio: normalise by |net_income|.
        # Floor at 1B KRW to prevent near-zero earnings from exploding the ratio.
        # Assets would be cleaner but are dropped from the pipeline output after ROE/GPA.
        accrual_raw = ni - cf
        ni_abs = ni.abs().clip(lower=1e9)
        accrual_ratio = (accrual_raw / ni_abs).clip(-3.0, 3.0)

        # Regime flip: sign(market_regime_120d) inverts the signal in contraction.
        # Treat regime == 0 (missing index data) as neutral bull to avoid killing signal.
        regime = pd.to_numeric(df["market_regime_120d"], errors="coerce").fillna(0.0)
        regime_sign = np.sign(regime).replace(0.0, 1.0)
        flipped = accrual_ratio * regime_sign

        # Sector z-score: removes sector-level accrual norms
        # (e.g. Industrials naturally carry higher accruals than Financials).
        # Fall back to market-wide z-score for sectors with < 3 stocks.
        df["_accrual_tmp"] = flipped
        grp_sec = df.groupby(["date", "sector"])
        grp_mkt = df.groupby("date")
        sec_n = grp_sec["_accrual_tmp"].transform("count")
        sec_mu = grp_sec["_accrual_tmp"].transform("mean")
        sec_std = grp_sec["_accrual_tmp"].transform("std")
        mkt_mu = grp_mkt["_accrual_tmp"].transform("mean")
        mkt_std = grp_mkt["_accrual_tmp"].transform("std")

        use_market = (sec_n < 3) | sec_std.isna() | (sec_std <= 1e-12)
        mu = sec_mu.where(~use_market, mkt_mu)
        sigma = sec_std.where(~use_market, mkt_std).replace(0, np.nan)

        df["accrual_regime_aware"] = (
            (flipped - mu) / sigma
        ).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-3.0, 3.0)

        df.drop(columns=["_accrual_tmp"], inplace=True)
        return df
