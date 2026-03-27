"""Reporting layer for parameter recommendations and system summaries.

This module provides structured reporting for:
- Parameter recommendations
- Recommendation summaries
- Audit trail outputs
- Decision documentation

All outputs are informational only and do not modify system state.
"""

from .recommendation_report import RecommendationReport, RecommendationReporter

__all__ = [
    "RecommendationReport",
    "RecommendationReporter",
]
