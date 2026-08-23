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
    # Separate strategy_id for ETF entries, enabling clean PF attribution per asset class.
    # ETF PF was 0.168 vs Stock PF 1.731 (2026-05-28 analysis).
    ETF_STRATEGY_ID = "breakout_momentum_v1_etf"

    def __init__(
        self,
        min_momentum: float = 0.05,
        min_signal_strength: float = 0.40,  # Recalibrated 2026-07-02 (R4-B): was 0.65 for 0.10 saturation; now 0.40 for 0.20 saturation (maintains ~same effective momentum floor ~7-8% in expansion)
        etf_symbols: set | None = None,
    ):
        """Initialize breakout momentum strategy.

        Args:
            min_momentum: Minimum momentum threshold for breakout.
            min_signal_strength: Minimum signal strength threshold.
            etf_symbols: Set of ETF symbols for strategy_id tagging.
                Signals for ETF symbols use ETF_STRATEGY_ID for clean PF attribution.
        """
        self.min_momentum = min_momentum
        self.min_signal_strength = min_signal_strength
        self.etf_symbols: set = etf_symbols or set()
    
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
        
        BLOCKING_QUALITY_FLAGS = {"stale_data", "insufficient_bars", "insufficient_price_data"}

        for momentum_feature in momentum_features:
            symbol = momentum_feature.symbol
            quality_flags = set(momentum_feature.quality_flags or [])

            # Skip features with blocking quality flags (stale / insufficient data)
            if quality_flags & BLOCKING_QUALITY_FLAGS:
                continue

            momentum = momentum_feature.values.get("momentum", 0.0)
            trend = momentum_feature.values.get("trend", "unknown")
            bars_used = momentum_feature.values.get("bars_used", 0)

            # Strategy logic: strong bullish momentum = breakout
            if momentum >= self.min_momentum and trend == "bullish":
                # Calculate signal strength
                # 2026-08-17 (R4-v2 residual): also capture the raw,
                # pre-clamp/pre-regime-adjustment score alongside the final
                # normalized [0,1] strength. Historically only the final
                # (already-clamped, regime-adjusted) value was persisted,
                # which makes it impossible to later re-derive what fraction
                # of saturation (strength==1.0) was caused by clamping vs.
                # by the macro regime multiplier. Both are stored in
                # metadata below (and therefore flow into FeatureSnapshotStore
                # via paper_demo.py's per-decision snapshot) purely for
                # future calibration analysis -- neither value changes any
                # filtering/sizing/exit behavior in this change.
                raw_score = self._calculate_raw_signal_score(momentum=momentum)
                signal_strength = self._calculate_signal_strength(
                    momentum=momentum,
                    macro_regime=macro_regime,
                )
                
                if signal_strength >= self.min_signal_strength:
                    # Generate candidate signal
                    signal = CandidateSignal(
                        strategy_id=(
                            self.ETF_STRATEGY_ID
                            if symbol in self.etf_symbols
                            else self.strategy_id
                        ),
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
                            "quality_flags": list(quality_flags),
                            # R4-v2 residual (2026-08-17): raw pre-clamp score
                            # vs. final normalized [0,1] strength, for future
                            # calibration-curve / saturation analysis only.
                            "raw_signal_score": raw_score,
                            "normalized_signal_score": signal_strength,
                        },
                    )
                    signals.append(signal)
        
        return signals
    
    def _calculate_raw_signal_score(self, momentum: float) -> float:
        """Calculate the raw, pre-clamp/pre-regime-adjustment momentum score.

        This is the same linear scaling used as the base of
        ``_calculate_signal_strength`` (10% momentum = 0.5, 20% momentum =
        1.0) but WITHOUT the final ``min(..., 1.0)`` clamp or the macro
        regime multiplier. It exists purely so raw/normalized scores can be
        compared later (R4-v2 residual, 2026-08-17) -- it has no effect on
        filtering, sizing, or execution.

        Args:
            momentum: Price momentum value.

        Returns:
            Raw score, unclamped (may exceed 1.0 for momentum > 20%).
        """
        return momentum / 0.20

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
        # Linear scaling: 10% momentum = 0.5, 20% momentum = 1.0
        # Changed 2026-07-02 (R4-B Option A): raised saturation threshold 0.10 -> 0.20
        # to reduce strength=1.0 saturation from ~73% to ~30% in current bull market.
        # See: docs/r4a_signal_strength_investigation.md
        strength = min(momentum / 0.20, 1.0)
        
        # Adjust for macro regime
        if macro_regime == "expansion":
            strength *= 1.1
        elif macro_regime == "high_volatility":
            strength *= 0.9
        elif macro_regime == "recession":
            strength *= 0.7
        
        return min(strength, 1.0)
