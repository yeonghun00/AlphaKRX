"""Dual-market LightGBM ranker — trains separate models for KOSPI and KOSDAQ.

Same interface as LGBMRanker. Activated via --model dual_lgbm.

Why: A single model must find feature weights that work across both KOSPI
(large-cap, macro-driven, stable fundamentals) and KOSDAQ (growth, retail,
earnings acceleration). These markets have structurally different return
drivers, so a shared weight vector is a compromise. Separate models let each
market learn its own optimal weights.

The two-stage re-ranking (already active) fixes the comparison problem at
inference time. Dual training fixes the learning problem at train time.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .base import BaseRanker
from .lgbm import LGBMRanker

MARKET_TYPES = ["kospi", "kosdaq"]
MIN_TRAIN_ROWS = 5_000   # minimum rows to train a market-specific model


class DualMarketRanker(BaseRanker):
    """Trains one LGBMRanker per market type, falls back to unified model."""

    BEST_PARAMS = LGBMRanker.BEST_PARAMS

    def __init__(
        self,
        feature_cols: List[str],
        target_col: str = "target_residual_rank_42d",
        time_decay: float = 0.4,
        patience: int = 80,
    ):
        super().__init__(feature_cols, target_col, time_decay, patience)
        self._market_models: Dict[str, LGBMRanker] = {}
        self._fallback: Optional[LGBMRanker] = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def train(
        self,
        train_df: pd.DataFrame,
        val_df: Optional[pd.DataFrame] = None,
        params: Optional[Dict] = None,
        sample_weight: Optional[np.ndarray] = None,
    ) -> "DualMarketRanker":
        params = params or self.BEST_PARAMS.copy()

        # Train market-specific models
        for mtype in MARKET_TYPES:
            mt_train = train_df[train_df["market_type"] == mtype] if "market_type" in train_df.columns else pd.DataFrame()
            mt_val = val_df[val_df["market_type"] == mtype] if (val_df is not None and "market_type" in val_df.columns) else None

            if len(mt_train) < MIN_TRAIN_ROWS:
                self.logger.warning("Skipping %s model — only %d rows", mtype, len(mt_train))
                continue

            if mt_val is not None and len(mt_val) < 100:
                mt_val = None

            ranker = LGBMRanker(
                feature_cols=self.feature_cols,
                target_col=self.target_col,
                time_decay=self.time_decay,
                patience=self.patience,
            )
            ranker.train(mt_train, mt_val, params=params)
            self._market_models[mtype] = ranker
            self.logger.info("Trained %s model on %d rows", mtype, len(mt_train))

        # Unified fallback: covers kodex, unknown types, and edge cases
        self._fallback = LGBMRanker(
            feature_cols=self.feature_cols,
            target_col=self.target_col,
            time_decay=self.time_decay,
            patience=self.patience,
        )
        self._fallback.train(train_df, val_df, params=params)
        self.model = self._fallback.model  # satisfies BaseRanker interface
        return self

    def predict(self, df: pd.DataFrame, swa: bool = False) -> np.ndarray:
        scores = np.full(len(df), np.nan)

        if "market_type" in df.columns and self._market_models:
            for mtype, ranker in self._market_models.items():
                mask = (df["market_type"] == mtype).values
                if mask.any():
                    scores[mask] = ranker.predict(df[mask], swa=swa)

        # Fill any remaining NaNs with fallback (unified model)
        nan_mask = np.isnan(scores)
        if nan_mask.any() and self._fallback is not None:
            scores[nan_mask] = self._fallback.predict(df[nan_mask], swa=swa)

        return scores

    def feature_importance(self) -> pd.DataFrame:
        """Average feature importance across all market-specific models."""
        if not self._market_models:
            return self._fallback.feature_importance() if self._fallback else pd.DataFrame()

        dfs = [m.feature_importance().set_index("feature") for m in self._market_models.values()]
        avg = pd.concat(dfs, axis=1).mean(axis=1).reset_index()
        avg.columns = ["feature", "importance"]
        return avg.sort_values("importance", ascending=False).reset_index(drop=True)

    def save(self, path: str) -> None:
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model_class": self.__class__.__name__,
            "feature_cols": self.feature_cols,
            "target_col": self.target_col,
            "time_decay": self.time_decay,
            "metadata": self.metadata,
            "market_models": {k: v.model for k, v in self._market_models.items()},
            "fallback_model": self._fallback.model if self._fallback else None,
            "version": "dual_v1",
        }
        with out_path.open("wb") as f:
            pickle.dump(payload, f)

    @classmethod
    def load(cls, path: str) -> "DualMarketRanker":
        with Path(path).open("rb") as f:
            payload = pickle.load(f)

        ranker = cls(
            feature_cols=payload["feature_cols"],
            target_col=payload.get("target_col", "target_residual_rank_42d"),
            time_decay=payload.get("time_decay", 0.4),
        )
        ranker.metadata = payload.get("metadata", {})

        for mtype, lgbm_model in payload.get("market_models", {}).items():
            sub = LGBMRanker(
                feature_cols=payload["feature_cols"],
                target_col=payload.get("target_col", "target_residual_rank_42d"),
                time_decay=payload.get("time_decay", 0.4),
            )
            sub.model = lgbm_model
            ranker._market_models[mtype] = sub

        if payload.get("fallback_model") is not None:
            ranker._fallback = LGBMRanker(
                feature_cols=payload["feature_cols"],
                target_col=payload.get("target_col", "target_residual_rank_42d"),
                time_decay=payload.get("time_decay", 0.4),
            )
            ranker._fallback.model = payload["fallback_model"]
            ranker.model = ranker._fallback.model

        return ranker
