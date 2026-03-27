"""Earnings/event feature for detecting upcoming corporate events.

This feature identifies upcoming earnings releases and other material events
that may drive price action.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import BaseFeature, FeatureResult


class EarningsEventFeature(BaseFeature):
    """Earnings and event detection feature.
    
    Identifies upcoming earnings releases within a configurable window.
    """
    
    def __init__(self, lookahead_days: int = 7):
        """Initialize earnings event feature.
        
        Args:
            lookahead_days: How many days ahead to look for events.
        """
        self.lookahead_days = lookahead_days
    
    def compute(self, records: list[CanonicalRecord]) -> list[FeatureResult]:
        """Compute earnings event proximity for symbols.
        
        Args:
            records: Canonical records (earnings calendar, filings, etc.).
            
        Returns:
            List of FeatureResult (one per symbol with upcoming events).
        """
        # Filter to event-related records
        event_records = [
            r for r in records 
            if r.event_type in {"earnings_calendar", "filing"}
        ]
        
        if not event_records:
            return []
        
        # Group by symbol
        symbols = {}
        for record in event_records:
            if record.symbol:
                if record.symbol not in symbols:
                    symbols[record.symbol] = []
                symbols[record.symbol].append(record)
        
        # Compute features per symbol
        results = []
        now = datetime.now(timezone.utc)
        lookahead = now + timedelta(days=self.lookahead_days)
        
        for symbol, symbol_records in symbols.items():
            # Find events in lookahead window
            upcoming_events = [
                r for r in symbol_records
                if now <= r.event_time <= lookahead
            ]
            
            if upcoming_events:
                # Event is upcoming
                nearest_event = min(upcoming_events, key=lambda r: r.event_time)
                days_until = (nearest_event.event_time - now).days
                
                result = FeatureResult(
                    feature_name="earnings_event",
                    symbol=symbol,
                    computed_at=now,
                    values={
                        "has_upcoming_event": True,
                        "days_until_event": days_until,
                        "event_type": nearest_event.event_type,
                    },
                    metadata={
                        "event_time": nearest_event.event_time.isoformat(),
                        "total_upcoming": len(upcoming_events),
                    },
                    quality_flags=[],
                )
                results.append(result)
            else:
                # No upcoming events
                result = FeatureResult(
                    feature_name="earnings_event",
                    symbol=symbol,
                    computed_at=now,
                    values={
                        "has_upcoming_event": False,
                        "days_until_event": None,
                        "event_type": None,
                    },
                    metadata={},
                    quality_flags=[],
                )
                results.append(result)
        
        return results
