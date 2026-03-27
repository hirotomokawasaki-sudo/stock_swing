"""Strategy engine for generating candidate signals from features.

This module implements approved initial strategies:
- event_swing_v1: Event-driven swing trading
- breakout_momentum_v1: Breakout/momentum trading

CRITICAL: This layer generates CANDIDATE signals only.
Candidate signals are NOT actionable decisions.
Risk approval and final actionability are decision engine responsibility.

See STRATEGY_SCOPE.md for approved strategies.
See DECISION_SCHEMA.md for signal output schema.
"""

from .base_strategy import BaseStrategy, CandidateSignal
from .event_swing_strategy import EventSwingStrategy
from .breakout_momentum_strategy import BreakoutMomentumStrategy

__all__ = [
    "BaseStrategy",
    "CandidateSignal",
    "EventSwingStrategy",
    "BreakoutMomentumStrategy",
]
