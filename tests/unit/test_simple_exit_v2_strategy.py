"""Unit tests for SimpleExitV2Strategy."""

from datetime import datetime, timedelta, timezone

import pytest

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy


@pytest.fixture
def strategy():
    """Create SimpleExitV2Strategy with default parameters."""
    return SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        trailing_activation_pct=0.05,
        trailing_stop_pct=0.03,
        max_hold_days=10,
    )


@pytest.fixture
def price_features():
    """Create price features for testing."""
    return [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=datetime.now(timezone.utc),
            values={"latest_close": 150.0},
        ),
        FeatureResult(
            feature_name="price_momentum",
            symbol="MSFT",
            computed_at=datetime.now(timezone.utc),
            values={"latest_close": 300.0},
        ),
    ]


def test_no_exit_when_within_range(strategy, price_features):
    """Test that no exit signal is generated when position is within normal range."""
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 145.0,  # +3.4% profit
            "current_price": 150.0,
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        }
    }
    
    signals = strategy.generate(price_features, current_positions)
    
    assert len(signals) == 0, "Should not generate exit signal for +3.4% profit (below trailing activation)"


def test_stop_loss_trigger(strategy, price_features):
    """Test that stop loss triggers correctly."""
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 200.0,  # -25% loss
            "current_price": 150.0,
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        }
    }
    
    signals = strategy.generate(price_features, current_positions)
    
    assert len(signals) == 1
    assert signals[0].symbol == "AAPL"
    assert signals[0].action == "sell"
    assert signals[0].signal_strength == 1.0
    assert "Stop loss triggered" in signals[0].reasoning


def test_trailing_stop_activation(strategy, price_features):
    """Test that trailing stop is active but not triggered with small pullback."""
    # Position has peaked at +6% and pulled back slightly to +5.1%
    # Pullback is only 0.9%, below 3% threshold
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 141.5,  # Current 150 = +6.0% from entry
            "current_price": 150.0,
            "peak_price": 151.0,  # Peak was +6.7%, pullback only 0.66%
            "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        }
    }
    
    signals = strategy.generate(price_features, current_positions)
    
    # trailing_stop_price = 151.0 * 0.97 = 146.47
    # current_price (150.0) > trailing_stop_price (146.47)
    # So should NOT trigger
    assert len(signals) == 0, "Should not trigger trailing stop with only 0.66% pullback from peak"


def test_trailing_stop_trigger(strategy, price_features):
    """Test that trailing stop triggers on sufficient pullback."""
    # Position peaked at +10%, now pulled back >3% from peak
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 140.0,  # +7.1% from entry
            "current_price": 150.0,
            "peak_price": 155.0,  # Peak was +10.7%, pullback is 3.2%
            "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        }
    }
    
    signals = strategy.generate(price_features, current_positions)
    
    assert len(signals) == 1
    assert signals[0].symbol == "AAPL"
    assert signals[0].action == "sell"
    assert "Trailing stop triggered" in signals[0].reasoning
    assert signals[0].metadata["trailing_active"] is True


def test_peak_price_update(strategy, price_features):
    """Test that peak price is updated when current price exceeds it."""
    # Current price is higher than recorded peak
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 140.0,
            "current_price": 150.0,
            "peak_price": 145.0,  # Old peak, should be updated
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        }
    }
    
    signals = strategy.generate(price_features, current_positions)
    
    # Peak should be updated to 150.0, so no exit
    assert len(signals) == 0


def test_time_based_exit(strategy, price_features):
    """Test that time-based exit triggers after max hold days."""
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 145.0,
            "current_price": 150.0,
            "created_at": (datetime.now(timezone.utc) - timedelta(days=11)).isoformat(),
        }
    }
    
    signals = strategy.generate(price_features, current_positions)
    
    assert len(signals) == 1
    assert signals[0].symbol == "AAPL"
    assert signals[0].action == "sell"
    assert "Max hold period reached" in signals[0].reasoning


def test_multiple_positions(strategy, price_features):
    """Test handling multiple positions with different exit criteria."""
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 200.0,  # -25% loss, should trigger stop loss
            "current_price": 150.0,
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        },
        "MSFT": {
            "qty": 50,
            "avg_entry_price": 280.0,  # +7.1% profit, trailing active
            "current_price": 300.0,
            "peak_price": 310.0,  # Pullback >3%, should trigger trailing stop
            "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        },
    }
    
    signals = strategy.generate(price_features, current_positions)
    
    assert len(signals) == 2
    symbols = {s.symbol for s in signals}
    assert symbols == {"AAPL", "MSFT"}


def test_no_positions(strategy, price_features):
    """Test that strategy handles no positions gracefully."""
    signals = strategy.generate(price_features, {})
    assert len(signals) == 0


def test_missing_price_data(strategy):
    """Test that strategy skips positions with missing price data."""
    current_positions = {
        "UNKNOWN": {
            "qty": 100,
            "avg_entry_price": 100.0,
            "current_price": 0,  # Missing price
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        }
    }
    
    signals = strategy.generate([], current_positions)
    assert len(signals) == 0
