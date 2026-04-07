"""Quarterly YoY earnings growth feature."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .registry import FeatureGroup, register


@register
class EarningsMomentumFeatures(FeatureGroup):
    name = "earnings_momentum"
    columns = ["earnings_growth_yoy"]
    dependencies = []  # Merged externally via pipeline before compute

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        # earnings_growth_yoy is loaded and merged by the pipeline
        # via _load_quarterly_earnings / _merge_quarterly_earnings.
        # This group handles missing-value fill.
        if "earnings_growth_yoy" not in df.columns:
            df["earnings_growth_yoy"] = 0.0
            return df

        df["earnings_growth_yoy"] = pd.to_numeric(df["earnings_growth_yoy"], errors="coerce")

        # Fill missing with sector-date median → market-date median → 0.0
        # Missing = no quarterly filing yet (early folds 2016-) or new listing.
        # Zero means "inline with the average company", which is neutral and correct.
        sector_med = df.groupby(["date", "sector"])["earnings_growth_yoy"].transform("median")
        market_med = df.groupby("date")["earnings_growth_yoy"].transform("median")
        df["earnings_growth_yoy"] = (
            df["earnings_growth_yoy"]
            .fillna(sector_med)
            .fillna(market_med)
            .fillna(0.0)
        )
        return df
