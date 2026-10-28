"""Parameter recommendation engine for strategy and risk parameter tuning.

This module provides parameter recommendations based on historical performance
and market conditions. All recommendations are advisory only.

CRITICAL: This engine does NOT auto-apply parameters.
All parameter changes require explicit operator approval.

Recommendations are observational and informational only.
"""

from .parameter_recommender import (
    ParameterRecommender,
    ParameterRecommendation,
    RecommendationType,
)
from .performance_analyzer import PerformanceAnalyzer, PerformanceMetrics
from .safe_ranges import SafeRangeValidator, ParameterRange, APPROVED_PARAMETER_RANGES

__all__ = [
    "ParameterRecommender",
    "ParameterRecommendation",
    "RecommendationType",
    "PerformanceAnalyzer",
    "PerformanceMetrics",
    "SafeRangeValidator",
    "ParameterRange",
    "APPROVED_PARAMETER_RANGES",
]
