"""Macro regime feature for classifying economic environment.

This feature uses FRED macro data to classify the current macro regime
(e.g., expansion, recession, high volatility).
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import BaseFeature, FeatureResult


class MacroRegimeFeature(BaseFeature):
    """Macro regime classification feature.
    
    Uses macro indicators (CPI, GDP, unemployment, etc.) to classify regime.
    
    Regime categories:
    - expansion: Growing economy, low volatility
    - recession: Contracting economy
    - high_volatility: Uncertain environment
    - unknown: Insufficient data
    """
    
    def compute(self, records: list[CanonicalRecord]) -> list[FeatureResult]:
        """Compute macro regime from macro data records.
        
        Args:
            records: Canonical records from FRED (macro data).
            
        Returns:
            List with one FeatureResult (macro regime is global).
            
        Note:
            This is a simplified implementation. Production would use
            more sophisticated regime detection algorithms.
        """
        # Filter to macro records
        macro_records = [r for r in records if r.source_type == "macro"]
        
        if not macro_records:
            # No macro data available
            return [self._unknown_regime()]
        
        # Simple heuristic: check if we have recent CPI data
        # Production would use multiple indicators
        cpi_records = [
            r for r in macro_records 
            if r.payload.get("series_id") == "CPIAUCSL"
        ]
        
        if cpi_records:
            latest_cpi = cpi_records[-1]  # Assume sorted by date
            cpi_value = latest_cpi.payload.get("value")
            
            # Simple regime classification (placeholder logic)
            if cpi_value and cpi_value < 320:
                regime = "expansion"
                confidence = 0.7
            else:
                regime = "high_volatility"
                confidence = 0.6
        else:
            regime = "unknown"
            confidence = 0.0
        
        result = FeatureResult(
            feature_name="macro_regime",
            symbol=None,  # Global feature
            computed_at=datetime.now(timezone.utc),
            values={
                "regime": regime,
                "confidence": confidence,
            },
            metadata={
                "input_records": len(macro_records),
                "indicators_used": ["CPIAUCSL"] if cpi_records else [],
            },
            quality_flags=[] if macro_records else ["insufficient_data"],
        )
        
        return [result]
    
    def _unknown_regime(self) -> FeatureResult:
        """Return unknown regime when no data available."""
        return FeatureResult(
            feature_name="macro_regime",
            symbol=None,
            computed_at=datetime.now(timezone.utc),
            values={
                "regime": "unknown",
                "confidence": 0.0,
            },
            metadata={},
            quality_flags=["no_macro_data"],
        )
