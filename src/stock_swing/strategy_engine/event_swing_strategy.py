"""Event-driven swing strategy (event_swing_v1).

This strategy generates buy signals around upcoming earnings/events
when combined with favorable momentum and macro conditions.

Strategy logic:
1. Identify symbols with upcoming events (earnings)
2. Check macro regime (prefer expansion/neutral)
3. Check price momentum (prefer bullish)
4. Generate buy signal if conditions align
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.base_strategy import BaseStrategy, CandidateSignal


class EventSwingStrategy(BaseStrategy):
    """Event-driven swing trading strategy.
    
    Approved strategy: event_swing_v1
    See STRATEGY_SCOPE.md for details.
    """
    
    strategy_id = "event_swing_v1"
    
    def __init__(
        self,
        min_signal_strength: float = 0.6,
        min_momentum: float = 0.02,
    ):
        """Initialize event swing strategy.
        
        Args:
            min_signal_strength: Minimum signal strength threshold.
            min_momentum: Minimum momentum threshold for signal.
        """
        self.min_signal_strength = min_signal_strength
        self.min_momentum = min_momentum
    
    def generate(
        self,
        features: list[FeatureResult],
    ) -> list[CandidateSignal]:
        """Generate candidate signals from features.
        
        Args:
            features: List of computed features.
            
        Returns:
            List of candidate signals (one per qualifying symbol).
        """
        # Organize features by type
        earnings_features = {
            f.symbol: f for f in features 
            if f.feature_name == "earnings_event" and f.symbol
        }
        momentum_features = {
            f.symbol: f for f in features 
            if f.feature_name == "price_momentum" and f.symbol
        }
        macro_features = [
            f for f in features 
            if f.feature_name == "macro_regime"
        ]
        
        # Get macro regime (global)
        macro_regime = None
        if macro_features:
            macro_regime = macro_features[0].values.get("regime")
        
        # Generate signals per symbol
        signals = []
        now = datetime.now(timezone.utc)
        
        for symbol, earnings_feature in earnings_features.items():
            # Check if event is upcoming
            has_event = earnings_feature.values.get("has_upcoming_event", False)
            days_until = earnings_feature.values.get("days_until_event")
            
            if not has_event or days_until is None:
                continue
            
            # Check momentum
            momentum_feature = momentum_features.get(symbol)
            if not momentum_feature:
                continue
            
            momentum = momentum_feature.values.get("momentum", 0.0)
            trend = momentum_feature.values.get("trend", "unknown")
            
            # Strategy logic: buy if upcoming event + bullish momentum + favorable macro
            if momentum >= self.min_momentum and trend == "bullish":
                # Calculate signal strength
                signal_strength = self._calculate_signal_strength(
                    momentum=momentum,
                    days_until_event=days_until,
                    macro_regime=macro_regime,
                )
                
                if signal_strength >= self.min_signal_strength:
                    # Generate candidate signal
                    signal = CandidateSignal(
                        strategy_id=self.strategy_id,
                        symbol=symbol,
                        action="buy",
                        signal_strength=signal_strength,
                        generated_at=now,
                        time_horizon="3d",
                        confidence=signal_strength * 0.9,  # Slightly conservative
                        reasoning=f"Upcoming event in {days_until}d with bullish momentum ({momentum:.2%})",
                        feature_refs=[
                            earnings_feature.feature_name,
                            momentum_feature.feature_name,
                        ],
                        metadata={
                            "days_until_event": days_until,
                            "momentum": momentum,
                            "trend": trend,
                            "macro_regime": macro_regime,
                        },
                    )
                    signals.append(signal)
        
        return signals
    
    def _calculate_signal_strength(
        self,
        momentum: float,
        days_until_event: int,
        macro_regime: str | None,
    ) -> float:
        """Calculate signal strength from inputs.
        
        Args:
            momentum: Price momentum value.
            days_until_event: Days until event.
            macro_regime: Current macro regime.
            
        Returns:
            Signal strength [0.0, 1.0].
        """
        # Base strength from momentum
        strength = min(momentum * 5.0, 1.0)  # Scale momentum to [0, 1]
        
        # Adjust for event timing (prefer 2-5 days out)
        if 2 <= days_until_event <= 5:
            strength *= 1.1
        elif days_until_event < 2:
            strength *= 0.9  # Too close
        
        # Adjust for macro regime
        if macro_regime == "expansion":
            strength *= 1.05
        elif macro_regime == "high_volatility":
            strength *= 0.95
        elif macro_regime == "recession":
            strength *= 0.8
        
        return min(strength, 1.0)
