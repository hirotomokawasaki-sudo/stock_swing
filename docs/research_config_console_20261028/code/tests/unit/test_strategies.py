"""Tests for strategy engine."""

from datetime import datetime, timedelta, timezone

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine import (
    BreakoutMomentumStrategy,
    EventSwingStrategy,
)


def test_event_swing_strategy_buy_signal() -> None:
    """Test event swing strategy generates buy signal."""
    now = datetime.now(timezone.utc)
    
    features = [
        # Upcoming earnings
        FeatureResult(
            feature_name="earnings_event",
            symbol="AAPL",
            computed_at=now,
            values={
                "has_upcoming_event": True,
                "days_until_event": 3,
                "event_type": "earnings_calendar",
            },
            metadata={},
            quality_flags=[],
        ),
        # Bullish momentum
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={
                "momentum": 0.12,  # 12%
                "trend": "bullish",
            },
            metadata={},
            quality_flags=[],
        ),
        # Expansion regime
        FeatureResult(
            feature_name="macro_regime",
            symbol=None,
            computed_at=now,
            values={
                "regime": "expansion",
                "confidence": 0.7,
            },
            metadata={},
            quality_flags=[],
        ),
    ]
    
    strategy = EventSwingStrategy(min_signal_strength=0.6)
    signals = strategy.generate(features)
    
    assert len(signals) == 1
    signal = signals[0]
    assert signal.strategy_id == "event_swing_v1"
    assert signal.symbol == "AAPL"
    assert signal.action == "buy"
    assert signal.signal_strength >= 0.6
    assert signal.time_horizon == "3d"


def test_event_swing_strategy_raw_and_normalized_score_in_metadata() -> None:
    """R4-v2 residual (2026-08-17): raw_signal_score / normalized_signal_score
    are recorded in metadata alongside the final signal_strength, for future
    calibration-curve analysis. This must not change filtering behavior.
    """
    now = datetime.now(timezone.utc)

    features = [
        FeatureResult(
            feature_name="earnings_event",
            symbol="AAPL",
            computed_at=now,
            values={"has_upcoming_event": True, "days_until_event": 3},
            metadata={},
            quality_flags=[],
        ),
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={"momentum": 0.12, "trend": "bullish"},
            metadata={},
            quality_flags=[],
        ),
        FeatureResult(
            feature_name="macro_regime",
            symbol=None,
            computed_at=now,
            values={"regime": "expansion"},
            metadata={},
            quality_flags=[],
        ),
    ]

    strategy = EventSwingStrategy(min_signal_strength=0.6)
    signals = strategy.generate(features)

    assert len(signals) == 1
    signal = signals[0]
    assert "raw_signal_score" in signal.metadata
    assert "normalized_signal_score" in signal.metadata
    assert signal.metadata["normalized_signal_score"] == signal.signal_strength
    # raw score = momentum * 5.0 = 0.12 * 5.0 = 0.60, unclamped/unadjusted
    assert signal.metadata["raw_signal_score"] == 0.12 * 5.0
    # normalized (clamped + event-timing + regime adjusted) differs from raw
    # here because of the >=1.1x event-timing/regime multipliers.
    assert signal.metadata["normalized_signal_score"] != signal.metadata["raw_signal_score"]


def test_event_swing_strategy_raw_score_uncapped_above_one() -> None:
    """Raw score is intentionally NOT clamped to 1.0, unlike signal_strength."""
    now = datetime.now(timezone.utc)

    features = [
        FeatureResult(
            feature_name="earnings_event",
            symbol="AAPL",
            computed_at=now,
            values={"has_upcoming_event": True, "days_until_event": 3},
            metadata={},
            quality_flags=[],
        ),
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={"momentum": 0.50, "trend": "bullish"},  # 50% -> raw = 2.5
            metadata={},
            quality_flags=[],
        ),
    ]

    strategy = EventSwingStrategy(min_signal_strength=0.6)
    signals = strategy.generate(features)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.metadata["raw_signal_score"] == 0.50 * 5.0
    assert signal.metadata["raw_signal_score"] > 1.0
    assert signal.signal_strength == 1.0  # normalized value stays clamped


def test_event_swing_strategy_no_signal_weak_momentum() -> None:
    """Test event swing strategy no signal with weak momentum."""
    now = datetime.now(timezone.utc)
    
    features = [
        FeatureResult(
            feature_name="earnings_event",
            symbol="AAPL",
            computed_at=now,
            values={
                "has_upcoming_event": True,
                "days_until_event": 3,
            },
            metadata={},
            quality_flags=[],
        ),
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={
                "momentum": 0.01,  # Only 1%
                "trend": "neutral",
            },
            metadata={},
            quality_flags=[],
        ),
    ]
    
    strategy = EventSwingStrategy(min_momentum=0.02)
    signals = strategy.generate(features)
    
    assert len(signals) == 0


def test_event_swing_strategy_no_signal_no_event() -> None:
    """Test event swing strategy no signal without upcoming event."""
    now = datetime.now(timezone.utc)
    
    features = [
        FeatureResult(
            feature_name="earnings_event",
            symbol="AAPL",
            computed_at=now,
            values={
                "has_upcoming_event": False,
            },
            metadata={},
            quality_flags=[],
        ),
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={
                "momentum": 0.08,
                "trend": "bullish",
            },
            metadata={},
            quality_flags=[],
        ),
    ]
    
    strategy = EventSwingStrategy()
    signals = strategy.generate(features)
    
    assert len(signals) == 0


def test_breakout_momentum_strategy_buy_signal() -> None:
    """Test breakout momentum strategy generates buy signal.

    R4-B 2026-07-02: saturation threshold raised 0.10 -> 0.20 and min_signal_strength
    recalibrated from 0.65 -> 0.40. Test momentum updated to 0.10 (was 0.07) so the
    signal still passes the new default threshold.
      new strength = min(0.10/0.20, 1.0) * 1.1 (expansion) = 0.55  >= 0.40  OK
    """
    now = datetime.now(timezone.utc)
    
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={
                "momentum": 0.10,  # 10% — passes new 0.40 threshold in expansion
                "trend": "bullish",
                "bars_used": 10,
            },
            metadata={},
            quality_flags=[],
        ),
        FeatureResult(
            feature_name="macro_regime",
            symbol=None,
            computed_at=now,
            values={
                "regime": "expansion",
            },
            metadata={},
            quality_flags=[],
        ),
    ]
    
    strategy = BreakoutMomentumStrategy(min_momentum=0.05)
    signals = strategy.generate(features)
    
    assert len(signals) == 1
    signal = signals[0]
    assert signal.strategy_id == "breakout_momentum_v1"
    assert signal.symbol == "AAPL"
    assert signal.action == "buy"
    assert signal.signal_strength >= 0.40  # recalibrated from 0.65 (R4-B)
    assert signal.time_horizon == "2d"


def test_breakout_momentum_strategy_raw_and_normalized_score_in_metadata() -> None:
    """R4-v2 residual (2026-08-17): raw_signal_score / normalized_signal_score
    are recorded in metadata alongside the final signal_strength, for future
    calibration-curve analysis. This must not change filtering behavior.
    """
    now = datetime.now(timezone.utc)

    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={"momentum": 0.10, "trend": "bullish", "bars_used": 10},
            metadata={},
            quality_flags=[],
        ),
        FeatureResult(
            feature_name="macro_regime",
            symbol=None,
            computed_at=now,
            values={"regime": "expansion"},
            metadata={},
            quality_flags=[],
        ),
    ]

    strategy = BreakoutMomentumStrategy(min_momentum=0.05)
    signals = strategy.generate(features)

    assert len(signals) == 1
    signal = signals[0]
    assert "raw_signal_score" in signal.metadata
    assert "normalized_signal_score" in signal.metadata
    assert signal.metadata["normalized_signal_score"] == signal.signal_strength
    # raw score = momentum / 0.20 = 0.10 / 0.20 = 0.50, unclamped/unadjusted
    assert signal.metadata["raw_signal_score"] == 0.10 / 0.20
    # normalized differs due to the 1.1x expansion regime multiplier
    assert signal.metadata["normalized_signal_score"] != signal.metadata["raw_signal_score"]


def test_breakout_momentum_strategy_raw_score_uncapped_above_one() -> None:
    """Raw score is intentionally NOT clamped to 1.0, unlike signal_strength."""
    now = datetime.now(timezone.utc)

    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={"momentum": 0.50, "trend": "bullish", "bars_used": 10},  # raw = 2.5
            metadata={},
            quality_flags=[],
        ),
    ]

    strategy = BreakoutMomentumStrategy(min_momentum=0.05)
    signals = strategy.generate(features)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.metadata["raw_signal_score"] == 0.50 / 0.20
    assert signal.metadata["raw_signal_score"] > 1.0
    assert signal.signal_strength == 1.0  # normalized value stays clamped


def test_breakout_momentum_strategy_no_signal_weak_momentum() -> None:
    """Test breakout momentum strategy no signal with weak momentum."""
    now = datetime.now(timezone.utc)
    
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={
                "momentum": 0.03,  # Only 3%
                "trend": "bullish",
            },
            metadata={},
            quality_flags=[],
        ),
    ]
    
    strategy = BreakoutMomentumStrategy(min_momentum=0.05)
    signals = strategy.generate(features)
    
    assert len(signals) == 0


def test_breakout_momentum_strategy_no_signal_bearish() -> None:
    """Test breakout momentum strategy no signal with bearish trend."""
    now = datetime.now(timezone.utc)
    
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={
                "momentum": -0.05,  # Negative
                "trend": "bearish",
            },
            metadata={},
            quality_flags=[],
        ),
    ]
    
    strategy = BreakoutMomentumStrategy()
    signals = strategy.generate(features)
    
    assert len(signals) == 0


def test_multiple_symbols_event_swing() -> None:
    """Test event swing strategy with multiple symbols."""
    now = datetime.now(timezone.utc)
    
    features = [
        # AAPL - qualifying
        FeatureResult(
            feature_name="earnings_event",
            symbol="AAPL",
            computed_at=now,
            values={"has_upcoming_event": True, "days_until_event": 3},
            metadata={},
            quality_flags=[],
        ),
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={"momentum": 0.12, "trend": "bullish"},
            metadata={},
            quality_flags=[],
        ),
        # MSFT - not qualifying (no event)
        FeatureResult(
            feature_name="price_momentum",
            symbol="MSFT",
            computed_at=now,
            values={"momentum": 0.08, "trend": "bullish"},
            metadata={},
            quality_flags=[],
        ),
    ]
    
    strategy = EventSwingStrategy()
    signals = strategy.generate(features)
    
    assert len(signals) == 1
    assert signals[0].symbol == "AAPL"
