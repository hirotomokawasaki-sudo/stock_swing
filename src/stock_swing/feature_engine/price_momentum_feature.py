"""Price momentum feature for measuring recent price strength.

This feature computes momentum indicators from price bar data.
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import BaseFeature, FeatureResult


class PriceMomentumFeature(BaseFeature):
    """Price momentum feature.
    
    Computes momentum indicators from price bars:
    - Simple returns over configurable periods
    - Trend direction
    """
    
    def __init__(self, period_days: int = 5):
        """Initialize price momentum feature.
        
        Args:
            period_days: Lookback period for momentum calculation.
        """
        self.period_days = period_days
    
    def compute(self, records: list[CanonicalRecord]) -> list[FeatureResult]:
        """Compute price momentum for symbols.
        
        Args:
            records: Canonical records (price bars).
            
        Returns:
            List of FeatureResult (one per symbol).
        """
        # Filter to price records
        price_records = [
            r for r in records 
            if r.source_type == "price" and "bar_" in r.event_type
        ]
        
        if not price_records:
            return []
        
        # Group by symbol
        symbols = {}
        for record in price_records:
            if record.symbol:
                if record.symbol not in symbols:
                    symbols[record.symbol] = []
                symbols[record.symbol].append(record)
        
        # Compute momentum per symbol
        results = []
        now = datetime.now(timezone.utc)
        
        for symbol, symbol_records in symbols.items():
            # Sort by time
            sorted_records = sorted(symbol_records, key=lambda r: r.event_time)
            
            if len(sorted_records) < 2:
                # Insufficient data
                result = FeatureResult(
                    feature_name="price_momentum",
                    symbol=symbol,
                    computed_at=now,
                    values={
                        "momentum": 0.0,
                        "trend": "unknown",
                    },
                    metadata={},
                    quality_flags=["insufficient_bars"],
                )
                results.append(result)
                continue
            
            # Simple momentum: (latest_close - earliest_close) / earliest_close
            earliest_close = sorted_records[0].payload.get("close")
            latest_close = sorted_records[-1].payload.get("close")
            
            if earliest_close and latest_close and earliest_close > 0:
                momentum = (latest_close - earliest_close) / earliest_close
                
                # Classify trend
                if momentum > 0.02:
                    trend = "bullish"
                elif momentum < -0.02:
                    trend = "bearish"
                else:
                    trend = "neutral"
            else:
                momentum = 0.0
                trend = "unknown"
            
            result = FeatureResult(
                feature_name="price_momentum",
                symbol=symbol,
                computed_at=now,
                values={
                    "momentum": momentum,
                    "trend": trend,
                    "bars_used": len(sorted_records),
                },
                metadata={
                    "earliest_time": sorted_records[0].event_time.isoformat(),
                    "latest_time": sorted_records[-1].event_time.isoformat(),
                },
                quality_flags=[],
            )
            results.append(result)
        
        return results
