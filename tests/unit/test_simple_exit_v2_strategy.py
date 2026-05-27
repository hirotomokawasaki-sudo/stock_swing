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
        breakeven_activation_pct=0.03,
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


# ── Breakeven stop tests ────────────────────────────────────────────────────

def test_breakeven_stop_not_triggered_while_in_profit():
    """Breakeven mode active but price still above entry → no signal."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        breakeven_activation_pct=0.03,
        trailing_activation_pct=0.08,
        trailing_stop_pct=0.04,
        max_hold_days=20,
    )
    # Position reached +3% (activates breakeven), currently at +1% (still positive)
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 100.0,
            "current_price": 101.0,    # +1%
            "peak_price": 103.5,        # reached +3.5% → breakeven activated
            "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        }
    }
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=datetime.now(timezone.utc),
            values={"latest_close": 101.0},
        )
    ]
    signals = strat.generate(features, current_positions)
    assert len(signals) == 0, "Still in profit — breakeven stop should not fire"


def test_breakeven_stop_triggers_when_return_goes_negative():
    """Breakeven mode active and price falls to 0% return → sell signal."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        breakeven_activation_pct=0.03,
        trailing_activation_pct=0.08,
        trailing_stop_pct=0.04,
        max_hold_days=20,
    )
    # Position reached +3.5% (activates breakeven), now back to -0.5%
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 100.0,
            "current_price": 99.5,      # -0.5%
            "peak_price": 103.5,        # reached +3.5% → breakeven active
            "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        }
    }
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=datetime.now(timezone.utc),
            values={"latest_close": 99.5},
        )
    ]
    signals = strat.generate(features, current_positions)
    assert len(signals) == 1
    assert signals[0].symbol == "AAPL"
    assert signals[0].action == "sell"
    assert "Breakeven stop triggered" in signals[0].reasoning
    assert signals[0].metadata["breakeven_active"] is True


def test_breakeven_stop_not_active_when_below_activation():
    """Position never reached breakeven_activation → breakeven stop inactive, hard stop governs."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        breakeven_activation_pct=0.03,
        trailing_activation_pct=0.08,
        trailing_stop_pct=0.04,
        max_hold_days=20,
    )
    # Position peaked at +2% (below breakeven_activation_pct=3%), now at -1%
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 100.0,
            "current_price": 99.0,     # -1%
            "peak_price": 102.0,       # only +2% peak — breakeven NOT activated
            "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        }
    }
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=datetime.now(timezone.utc),
            values={"latest_close": 99.0},
        )
    ]
    signals = strat.generate(features, current_positions)
    # -1% is within hard stop (-7%), so no exit
    assert len(signals) == 0


def test_hard_stop_still_fires_when_below_breakeven_activation():
    """Position never reached breakeven zone → hard stop fires at -7%."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        breakeven_activation_pct=0.03,
        trailing_activation_pct=0.08,
        trailing_stop_pct=0.04,
        max_hold_days=20,
    )
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 100.0,
            "current_price": 92.0,     # -8%
            "peak_price": 100.5,       # peak only +0.5% — never in breakeven zone
            "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        }
    }
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=datetime.now(timezone.utc),
            values={"latest_close": 92.0},
        )
    ]
    signals = strat.generate(features, current_positions)
    assert len(signals) == 1
    assert "Stop loss triggered" in signals[0].reasoning
    assert signals[0].signal_strength == 1.0


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


def test_time_based_exit_uses_entry_time_fallback(strategy, price_features):
    """Test that time-based exit works when only entry_time is present."""
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 145.0,
            "current_price": 150.0,
            "entry_time": (datetime.now(timezone.utc) - timedelta(days=11)).isoformat(),
        }
    }

    signals = strategy.generate(price_features, current_positions)

    assert len(signals) == 1
    assert signals[0].symbol == "AAPL"
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
