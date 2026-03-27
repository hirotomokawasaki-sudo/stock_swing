"""Base strategy interface and candidate signal structure.

All strategies must inherit from BaseStrategy and return CandidateSignal instances.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from stock_swing.feature_engine.base_feature import FeatureResult


@dataclass
class CandidateSignal:
    """Candidate signal from strategy (NOT an actionable decision).
    
    This is output from strategy layer. It becomes an actionable decision
    only after risk validation and decision engine processing.
    
    Attributes:
        strategy_id: Strategy identifier (e.g., "event_swing_v1").
        symbol: Stock symbol.
        action: Suggested action (buy, sell, hold).
        signal_strength: Signal strength [0.0, 1.0].
        generated_at: Timestamp when signal was generated.
        time_horizon: Expected hold period (e.g., "3d", "1w").
        confidence: Strategy confidence [0.0, 1.0].
        reasoning: Human-readable reasoning.
        feature_refs: Features used in signal generation.
        metadata: Additional context.
    """
    
    strategy_id: str
    symbol: str
    action: str  # buy, sell, hold
    signal_strength: float  # 0.0 to 1.0
    generated_at: datetime
    time_horizon: str  # e.g., "3d", "1w"
    confidence: float  # 0.0 to 1.0
    reasoning: str
    feature_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base class for all strategies.
    
    All strategy implementations must inherit from this class and implement generate().
    """
    
    strategy_id: str  # Must be defined by subclass
    
    @abstractmethod
    def generate(
        self,
        features: list[FeatureResult],
    ) -> list[CandidateSignal]:
        """Generate candidate signals from features.
        
        Args:
            features: List of computed features.
            
        Returns:
            List of CandidateSignal instances.
            
        Note:
            Signals are CANDIDATES only. They are not actionable until
            processed by decision engine with risk validation.
        """
        raise NotImplementedError
