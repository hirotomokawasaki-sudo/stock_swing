"""Breakout/momentum strategy (breakout_momentum_v1).

This strategy generates buy signals when price momentum exceeds thresholds,
indicating potential breakout conditions.

Strategy logic:
1. Check price momentum
2. If momentum exceeds threshold and trend is bullish → buy signal
3. Signal strength based on momentum magnitude
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.base_strategy import BaseStrategy, CandidateSignal


class BreakoutMomentumStrategy(BaseStrategy):
    """Breakout/momentum trading strategy.
    
    Approved strategy: breakout_momentum_v1
    See STRATEGY_SCOPE.md for details.
    """
    
    strategy_id = "breakout_momentum_v1"
    
    def __init__(
        self,
        min_momentum: float = 0.05,  # 5% minimum momentum
        min_signal_strength: float = 0.65,
    ):
        """Initialize breakout momentum strategy.
        
        Args:
            min_momentum: Minimum momentum threshold for breakout.
            min_signal_strength: Minimum signal strength threshold.
        """
        self.min_momentum = min_momentum
        self.min_signal_strength = min_signal_strength
    
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
        # Filter to momentum features
        momentum_features = [
            f for f in features 
            if f.feature_name == "price_momentum" and f.symbol
        ]
        
        # Get macro regime if available
        macro_features = [
            f for f in features 
            if f.feature_name == "macro_regime"
        ]
        macro_regime = None
        if macro_features:
            macro_regime = macro_features[0].values.get("regime")
        
        # Generate signals
        signals = []
        now = datetime.now(timezone.utc)
        
        for momentum_feature in momentum_features:
            symbol = momentum_feature.symbol
            momentum = momentum_feature.values.get("momentum", 0.0)
            trend = momentum_feature.values.get("trend", "unknown")
            bars_used = momentum_feature.values.get("bars_used", 0)
            
            # Strategy logic: strong bullish momentum = breakout
            if momentum >= self.min_momentum and trend == "bullish":
                # Calculate signal strength
                signal_strength = self._calculate_signal_strength(
                    momentum=momentum,
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
                        time_horizon="2d",
                        confidence=signal_strength * 0.85,  # Conservative
                        reasoning=f"Strong bullish momentum ({momentum:.2%}) indicates breakout",
                        feature_refs=[momentum_feature.feature_name],
                        metadata={
                            "momentum": momentum,
                            "trend": trend,
                            "bars_used": bars_used,
                            "macro_regime": macro_regime,
                            "risk_per_share": momentum_feature.values.get("risk_per_share"),
                            "stop_price": momentum_feature.values.get("stop_price"),
                            "latest_close": momentum_feature.values.get("latest_close"),
                            "atr": momentum_feature.values.get("atr"),
                        },
                    )
                    signals.append(signal)
        
        return signals
    
    def _calculate_signal_strength(
        self,
        momentum: float,
        macro_regime: str | None,
    ) -> float:
        """Calculate signal strength from inputs.
        
        Args:
            momentum: Price momentum value.
            macro_regime: Current macro regime.
            
        Returns:
            Signal strength [0.0, 1.0].
        """
        # Base strength from momentum magnitude
        # Linear scaling: 5% momentum = 0.5, 10% momentum = 1.0
        strength = min(momentum / 0.10, 1.0)
        
        # Adjust for macro regime
        if macro_regime == "expansion":
            strength *= 1.1
        elif macro_regime == "high_volatility":
            strength *= 0.9
        elif macro_regime == "recession":
            strength *= 0.7
        
        return min(strength, 1.0)
