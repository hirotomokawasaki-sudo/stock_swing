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
                "momentum": 0.08,  # 8%
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
    """Test breakout momentum strategy generates buy signal."""
    now = datetime.now(timezone.utc)
    
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=now,
            values={
                "momentum": 0.07,  # 7%
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
    assert signal.signal_strength >= 0.65
    assert signal.time_horizon == "2d"


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
            values={"momentum": 0.06, "trend": "bullish"},
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
