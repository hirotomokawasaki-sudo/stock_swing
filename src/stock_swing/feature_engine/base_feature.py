"""Base feature interface and result structure.

All features must inherit from BaseFeature and return FeatureResult instances.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from stock_swing.core.types import CanonicalRecord


@dataclass
class FeatureResult:
    """Result of feature computation.
    
    Attributes:
        feature_name: Name of the feature (e.g., "macro_regime").
        symbol: Symbol if applicable (None for macro-only features).
        computed_at: Timestamp when feature was computed.
        values: Feature values as dict (e.g., {"regime": "expansion", "confidence": 0.8}).
        metadata: Optional metadata (e.g., input record IDs, computation notes).
        quality_flags: Quality warnings or notes.
    """
    
    feature_name: str
    symbol: str | None
    computed_at: datetime
    values: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)


class BaseFeature(ABC):
    """Abstract base class for all features.
    
    All feature implementations must inherit from this class and implement compute().
    """
    
    @abstractmethod
    def compute(self, records: list[CanonicalRecord]) -> list[FeatureResult]:
        """Compute feature from canonical records.
        
        Args:
            records: List of CanonicalRecord instances (relevant to this feature).
            
        Returns:
            List of FeatureResult instances.
            
        Note:
            Features should be deterministic and stateless where possible.
            Features should not contain strategy-specific logic.
        """
        raise NotImplementedError
