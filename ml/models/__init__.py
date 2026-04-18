"""Model package — multi-model support for stock ranking.

Public API:
    BaseRanker       — abstract base class
    LGBMRanker       — LightGBM (default)
    XGBRanker        — XGBoost
    CatBoostRanker   — CatBoost
    get_model_class  — factory function
"""

from ml.models.base import BaseRanker
from ml.models.lgbm import LGBMRanker
from ml.models.xgboost import XGBRanker
from ml.models.catboost import CatBoostRanker
from ml.models.dual_lgbm import DualMarketRanker


def get_model_class(name: str) -> type[BaseRanker]:
    """Return model class by name."""
    models = {
        "lgbm": LGBMRanker,
        "xgboost": XGBRanker,
        "catboost": CatBoostRanker,
        "dual_lgbm": DualMarketRanker,
    }
    if name not in models:
        raise ValueError(f"Unknown model '{name}'. Choose from: {list(models.keys())}")
    return models[name]


__all__ = ["BaseRanker", "LGBMRanker", "XGBRanker", "CatBoostRanker", "DualMarketRanker", "get_model_class"]
