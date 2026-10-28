"""Feature engine for computing reusable features from canonical data.

This module provides feature computation for approved first-wave features.
Features are strategy-agnostic and reusable across multiple strategies.

See STRATEGY_SCOPE.md for approved feature families.
"""

from .base_feature import BaseFeature, FeatureResult
from .macro_regime_feature import MacroRegimeFeature
from .earnings_event_feature import EarningsEventFeature
from .price_momentum_feature import PriceMomentumFeature

__all__ = [
    "BaseFeature",
    "FeatureResult",
    "MacroRegimeFeature",
    "EarningsEventFeature",
    "PriceMomentumFeature",
]
