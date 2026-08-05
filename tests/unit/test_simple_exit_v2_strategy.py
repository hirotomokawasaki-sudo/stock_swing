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


# ── Staged Breakeven Floor tests (2026-08-05) ────────────────────────────
# Post-exit drift simulation (scripts/analyze_breakeven_staged_floor.py,
# 43 breakeven_stop trades) showed the fixed 0% floor exits too early when a
# position keeps climbing past activation. Staged floor ratchets up floor as
# peak_return climbs further, mirroring staged_trailing's design.

STAGED_BREAKEVEN_LEVELS = [
    {"activation_pct": 0.05, "floor_pct": 0.0},
    {"activation_pct": 0.08, "floor_pct": 0.03},
    {"activation_pct": 0.12, "floor_pct": 0.06},
]


def _make_strat_staged_breakeven(**kwargs) -> SimpleExitV2Strategy:
    defaults = dict(
        stop_loss_pct=-0.07,
        breakeven_activation_pct=0.05,
        trailing_activation_pct=0.20,  # kept high so trailing never preempts breakeven in these tests
        trailing_stop_pct=0.04,
        max_hold_days=20,
        staged_breakeven_enabled=True,
        staged_breakeven_levels=STAGED_BREAKEVEN_LEVELS,
    )
    defaults.update(kwargs)
    return SimpleExitV2Strategy(**defaults)


def test_staged_breakeven_disabled_behaves_like_legacy():
    """staged_breakeven_enabled=False: legacy fixed-0%-floor behavior unchanged."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        breakeven_activation_pct=0.05,
        trailing_activation_pct=0.20,
        staged_breakeven_enabled=False,
        staged_breakeven_levels=STAGED_BREAKEVEN_LEVELS,
    )
    activated, floor_pct, level = strat._resolve_breakeven_floor(0.10, 0.05)
    assert activated is True
    assert floor_pct == 0.0
    assert level is None


def test_staged_breakeven_first_level_matches_legacy_activation():
    """First staged level (peak>=5% -> floor 0%) matches the legacy rule exactly."""
    strat = _make_strat_staged_breakeven()
    activated, floor_pct, level = strat._resolve_breakeven_floor(0.06, 0.05)
    assert activated is True
    assert floor_pct == 0.0
    assert level is not None


def test_staged_breakeven_second_level_raises_floor():
    """peak_return >= +8% -> floor ratchets up to +3%."""
    strat = _make_strat_staged_breakeven()
    activated, floor_pct, level = strat._resolve_breakeven_floor(0.09, 0.05)
    assert activated is True
    assert floor_pct == 0.03


def test_staged_breakeven_third_level_raises_floor_further():
    """peak_return >= +12% -> floor ratchets up to +6%."""
    strat = _make_strat_staged_breakeven()
    activated, floor_pct, level = strat._resolve_breakeven_floor(0.13, 0.05)
    assert activated is True
    assert floor_pct == 0.06


def test_staged_breakeven_not_activated_below_first_level():
    """peak_return below the first activation level -> not activated at all."""
    strat = _make_strat_staged_breakeven()
    activated, floor_pct, level = strat._resolve_breakeven_floor(0.02, 0.05)
    assert activated is False


def test_staged_breakeven_holds_when_above_ratcheted_floor():
    """Position peaked at +9% (floor=+3%), currently at +4% (still above floor) -> hold."""
    strat = _make_strat_staged_breakeven()
    current_price = 104.0  # +4%
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=48.0, peak_price=109.0)  # peak +9%
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 0, (
        f"Peak +9% ratchets floor to +3%; current +4% is still above floor -> should hold, got: {signals}"
    )


def test_staged_breakeven_fires_when_below_ratcheted_floor():
    """Position peaked at +9% (floor=+3%), currently at +2% (below floor) -> staged breakeven fires."""
    strat = _make_strat_staged_breakeven()
    current_price = 102.0  # +2%, below the +3% ratcheted floor
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=48.0, peak_price=109.0)  # peak +9%
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 1, (
        f"Peak +9% ratchets floor to +3%; current +2% is below floor -> should fire, got: {signals}"
    )
    assert signals[0].action == "sell"
    assert "Staged breakeven stop" in signals[0].reasoning


def test_staged_breakeven_captures_more_gain_than_legacy():
    """Regression for the core improvement: legacy (floor=0%) exits at return=0%,
    but staged (floor=+3% after peak>=8%) should never fire at return=0% once
    peak has passed +8% -- it should have already exited earlier at the higher
    floor, capturing more gain than the legacy rule would have on the same path.
    """
    staged = _make_strat_staged_breakeven()
    legacy = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        breakeven_activation_pct=0.05,
        trailing_activation_pct=0.20,
        staged_breakeven_enabled=False,
    )
    # Position peaked at +9%, now back down to return=0% (legacy fires here)
    current_price = 100.0  # 0% return
    pos_legacy = _make_position("TEST", 100.0, current_price, entry_hours_ago=48.0, peak_price=109.0)
    pos_staged = _make_position("TEST", 100.0, current_price, entry_hours_ago=48.0, peak_price=109.0)
    features = [_make_feature("TEST", current_price)]

    legacy_signals = legacy.generate(features, {"TEST": pos_legacy})
    staged_signals = staged.generate(features, {"TEST": pos_staged})

    assert len(legacy_signals) == 1, "Legacy rule should fire at return=0% once peak>=5%"
    assert len(staged_signals) == 1, "Staged rule should also have fired by now (floor=+3% was breached earlier)"
    # The staged rule's exit reason should reference the higher, ratcheted floor,
    # not the legacy 0% floor -- demonstrating it would have triggered (and exited
    # at a better price) before the position fell all the way back to 0%.
    assert "stage floor=3%" in staged_signals[0].reasoning


# ── Entry signal strength dynamic threshold tests ────────────────────────

def test_high_strength_entry_gets_wider_stop():
    """High conviction entry (strength=0.90) should have -9% stop, not -7%."""
    strat = SimpleExitV2Strategy(stop_loss_pct=-0.07)
    # -8% loss: fires with standard stop (-7%) but should NOT fire with high-strength stop (-9%)
    pos = {
        "qty": 100,
        "avg_entry_price": 100.0,
        "current_price": 92.0,   # -8%
        "peak_price": 100.5,
        "entry_signal_strength": 0.90,  # high conviction
        "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }
    features = [FeatureResult(
        feature_name="price_momentum", symbol="AAPL",
        computed_at=datetime.now(timezone.utc),
        values={"latest_close": 92.0},
    )]
    signals = strat.generate(features, {"AAPL": pos})
    # -8% is within -9% threshold → should NOT exit
    assert len(signals) == 0, "High-strength entry should survive -8% (stop is -9%)"


def test_high_strength_entry_fires_at_minus_9pct():
    """High conviction entry fires stop at -9%."""
    strat = SimpleExitV2Strategy(stop_loss_pct=-0.07)
    pos = {
        "qty": 100,
        "avg_entry_price": 100.0,
        "current_price": 90.5,   # -9.5%
        "peak_price": 100.5,
        "entry_signal_strength": 0.90,
        "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }
    features = [FeatureResult(
        feature_name="price_momentum", symbol="AAPL",
        computed_at=datetime.now(timezone.utc),
        values={"latest_close": 90.5},
    )]
    signals = strat.generate(features, {"AAPL": pos})
    assert len(signals) == 1
    assert "Stop loss triggered" in signals[0].reasoning
    assert signals[0].metadata["eff_stop_loss_pct"] == -0.09


def test_low_strength_entry_gets_tighter_stop():
    """Low conviction entry (strength=0.55) fires stop at -5%."""
    strat = SimpleExitV2Strategy(stop_loss_pct=-0.07)
    pos = {
        "qty": 100,
        "avg_entry_price": 100.0,
        "current_price": 94.5,   # -5.5%
        "peak_price": 100.5,
        "entry_signal_strength": 0.55,  # low conviction
        "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }
    features = [FeatureResult(
        feature_name="price_momentum", symbol="AAPL",
        computed_at=datetime.now(timezone.utc),
        values={"latest_close": 94.5},
    )]
    signals = strat.generate(features, {"AAPL": pos})
    # -5.5% exceeds -5% low-strength threshold → should exit
    assert len(signals) == 1
    assert "Stop loss triggered" in signals[0].reasoning
    assert signals[0].metadata["eff_stop_loss_pct"] == -0.05


def test_no_strength_uses_low_conviction_thresholds():
    """No entry_signal_strength → conservative LOW-conviction thresholds (-5% stop, +10% trailing).

    Broker-reconstructed positions have no signal provenance; treat as low conviction.
    P0 change: None was previously treated as standard (-7%). Now uses -5% to protect capital.
    """
    strat = SimpleExitV2Strategy(stop_loss_pct=-0.07)
    pos = {
        "qty": 100,
        "avg_entry_price": 100.0,
        "current_price": 94.0,   # -6%: within standard -7% but OUTSIDE low-conviction -5%
        "peak_price": 100.5,
        "entry_signal_strength": None,
        "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }
    features = [FeatureResult(
        feature_name="price_momentum", symbol="AAPL",
        computed_at=datetime.now(timezone.utc),
        values={"latest_close": 94.0},
    )]
    signals = strat.generate(features, {"AAPL": pos})
    # With low-conviction -5% stop: -6% should FIRE (position beyond stop)
    assert len(signals) == 1, "Low-conviction stop (-5%) should fire at -6%"
    assert signals[0].action == "sell"
    assert "stop loss" in signals[0].reasoning.lower()


def test_resolve_thresholds_missing_strength_is_conservative():
    """_resolve_thresholds returns low-conviction values for None and invalid inputs."""
    strat = SimpleExitV2Strategy(stop_loss_pct=-0.07, trailing_activation_pct=0.08)
    stop, trail = strat._resolve_thresholds(None)
    assert stop == -0.05, f"Expected -0.05, got {stop}"
    assert trail == 0.10, f"Expected 0.10, got {trail}"


def test_broker_recon_graduates_to_standard_after_hold_days():
    """改善点1 2026-07-16: broker_recon position held >= graduation_days → standard thresholds."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        trailing_activation_pct=0.08,
        broker_recon_graduation_days=5,
    )
    # Before graduation window: still conservative
    stop, trail = strat._resolve_thresholds(None, hold_days=4)
    assert stop == -0.05, f"Before graduation: expected -0.05, got {stop}"
    assert trail == 0.10, f"Before graduation: expected 0.10, got {trail}"

    # At exactly graduation boundary: graduates to standard
    stop, trail = strat._resolve_thresholds(None, hold_days=5)
    assert stop == -0.07, f"At graduation: expected -0.07, got {stop}"
    assert trail == 0.08, f"At graduation: expected 0.08, got {trail}"

    # Well past graduation: still standard
    stop, trail = strat._resolve_thresholds(None, hold_days=14)
    assert stop == -0.07, f"Post graduation: expected -0.07, got {stop}"
    assert trail == 0.08, f"Post graduation: expected 0.08, got {trail}"


def test_broker_recon_graduation_disabled_when_none():
    """graduation_days=None disables graduation entirely."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        trailing_activation_pct=0.08,
        broker_recon_graduation_days=None,
    )
    stop, trail = strat._resolve_thresholds(None, hold_days=30)
    assert stop == -0.05, f"Graduation disabled: expected -0.05, got {stop}"
    assert trail == 0.10, f"Graduation disabled: expected 0.10, got {trail}"


def test_broker_recon_graduation_without_hold_days_stays_conservative():
    """No hold_days info → cannot graduate, stays conservative."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        trailing_activation_pct=0.08,
        broker_recon_graduation_days=5,
    )
    stop, trail = strat._resolve_thresholds(None, hold_days=None)
    assert stop == -0.05, f"No hold_days: expected -0.05, got {stop}"
    assert trail == 0.10, f"No hold_days: expected 0.10, got {trail}"


def test_high_strength_trailing_activates_earlier():
    """High conviction entry activates trailing at +6% (vs standard +8%)."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        trailing_activation_pct=0.08,
        trailing_stop_pct=0.04,
    )
    # peak_return = +7%: below standard +8% threshold but above high-strength +6%
    pos = {
        "qty": 100,
        "avg_entry_price": 100.0,
        "current_price": 104.0,  # +4%
        "peak_price": 107.0,     # +7% peak → trailing active for high strength
        "entry_signal_strength": 0.90,
        "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
    }
    features = [FeatureResult(
        feature_name="price_momentum", symbol="AAPL",
        computed_at=datetime.now(timezone.utc),
        values={"latest_close": 104.0},
    )]
    # trailing_stop_price = 107 * 0.96 = 102.72, current=104 > 102.72 → NOT triggered
    signals = strat.generate(features, {"AAPL": pos})
    assert len(signals) == 0, "Trailing active (high strength) but not pulled back enough"


def test_resolve_thresholds_standard():
    """_resolve_thresholds returns base values for standard strength."""
    strat = SimpleExitV2Strategy(stop_loss_pct=-0.07, trailing_activation_pct=0.08)
    sl, ta = strat._resolve_thresholds(0.75)
    assert sl == -0.07
    assert ta == 0.08


def test_resolve_thresholds_high():
    strat = SimpleExitV2Strategy(stop_loss_pct=-0.07, trailing_activation_pct=0.08)
    sl, ta = strat._resolve_thresholds(0.90)
    assert sl == -0.09
    assert ta == 0.06


def test_resolve_thresholds_low():
    strat = SimpleExitV2Strategy(stop_loss_pct=-0.07, trailing_activation_pct=0.08)
    sl, ta = strat._resolve_thresholds(0.50)
    assert sl == -0.05
    assert ta == 0.10


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


def test_staged_trailing_uses_tighter_stage_before_baseline_stop():
    """R3-B staged trailing exits when the active stage stop is hit."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        breakeven_activation_pct=0.03,
        trailing_activation_pct=0.08,
        trailing_stop_pct=0.04,
        max_hold_days=20,
        staged_trailing_enabled=True,
        staged_trailing_levels=[
            {"activation_pct": 0.05, "trailing_stop_pct": 0.035},
            {"activation_pct": 0.08, "trailing_stop_pct": 0.03},
            {"activation_pct": 0.12, "trailing_stop_pct": 0.025},
        ],
    )
    current_positions = {
        "AAPL": {
            "qty": 100,
            "avg_entry_price": 100.0,
            "current_price": 102.20,
            "peak_price": 106.0,
            "created_at": (datetime.now(timezone.utc) - timedelta(days=4)).isoformat(),
        }
    }

    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=datetime.now(timezone.utc),
            values={"latest_close": 102.20},
        )
    ]
    signals = strat.generate(features, current_positions)

    assert len(signals) == 1
    assert "Staged trailing stop triggered" in signals[0].reasoning
    assert signals[0].metadata["staged_trailing_enabled"] is True
    assert signals[0].metadata["active_trailing_activation_pct"] == pytest.approx(0.05)
    assert signals[0].metadata["active_trailing_stop_pct"] == pytest.approx(0.035)


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


# ────────────────────────────────────────────────────────────────
# G9: min_hold guard tests
# ────────────────────────────────────────────────────────────────

def _make_position(symbol: str, entry_price: float, current_price: float,
                   entry_hours_ago: float = 2.0, peak_price: float | None = None) -> dict:
    """Helper: build a minimal position dict for SimpleExitV2 testing."""
    now = datetime.now(timezone.utc)
    return {
        "symbol": symbol,
        "qty": 100,
        "avg_entry_price": str(entry_price),
        "current_price": current_price,
        "peak_price": peak_price or entry_price,
        "created_at": (now - timedelta(hours=entry_hours_ago)).isoformat(),
        "entry_signal_strength": 0.75,
    }


def _make_feature(symbol: str, current_price: float) -> FeatureResult:
    return FeatureResult(
        feature_name="price_momentum",
        symbol=symbol,
        computed_at=datetime.now(timezone.utc),
        values={"latest_close": current_price},
    )


def test_min_hold_suppresses_stop_loss_within_1_day():
    """G9: stop_loss must NOT fire when hold < 1 day and loss < emergency cap."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        min_hold_days=1,
        min_hold_days_enabled=True,
        emergency_stop_bypass_pct=-0.12,
    )
    current_price = 92.0  # -8% from 100
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=2.0)
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 0, f"Expected no signal (min_hold guard), got: {signals}"


def test_min_hold_allows_stop_loss_after_1_day():
    """G9: stop_loss MUST fire normally once hold >= 1 day."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        min_hold_days=1,
        min_hold_days_enabled=True,
        emergency_stop_bypass_pct=-0.12,
    )
    current_price = 92.0  # -8% from 100
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=26.0)  # >1 day
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 1
    assert signals[0].action == "sell"
    assert "Stop loss" in signals[0].reasoning


def test_emergency_bypass_fires_even_within_min_hold():
    """G9: if loss > emergency_stop_bypass_pct, exit immediately regardless of hold."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        min_hold_days=1,
        min_hold_days_enabled=True,
        emergency_stop_bypass_pct=-0.12,
    )
    current_price = 85.0  # -15% from 100, exceeds -12% emergency cap
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=1.0)  # <1 day
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 1
    assert signals[0].action == "sell"
    assert "Emergency stop" in signals[0].reasoning


def test_min_hold_disabled_fires_immediately():
    """G9: when min_hold_days_enabled=False, stop_loss fires on day 0 (old behavior)."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        min_hold_days=1,
        min_hold_days_enabled=False,  # disabled
        emergency_stop_bypass_pct=-0.12,
    )
    current_price = 92.0  # -8%
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=2.0)
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 1, "With min_hold disabled, stop_loss should fire immediately"
    assert signals[0].action == "sell"


def test_min_hold_does_not_affect_trailing_stop():
    """G9: trailing_stop must fire normally even within min_hold window."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        trailing_activation_pct=0.05,
        trailing_stop_pct=0.03,
        min_hold_days=1,
        min_hold_days_enabled=True,
        emergency_stop_bypass_pct=-0.12,
    )
    # Peaked at +10%, now pulled back -4% from peak → trailing triggered
    entry = 100.0
    peak = 110.0
    current_price = 110.0 * (1 - 0.04)  # 4% pullback from peak
    pos = _make_position("TEST", entry, current_price, entry_hours_ago=2.0, peak_price=peak)
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 1
    assert signals[0].action == "sell"
    assert "Trailing stop" in signals[0].reasoning or "trailing" in signals[0].reasoning.lower()


# ────────────────────────────────────────────────────────────────
# Plan A v2: Tiered min_hold tests — offset-based redesign (2026-08-05)
#
# History: v1 (2026-07-27, commit 52736ca) used *absolute* return_pct
# thresholds ("return > -5% → 7d"). FIX-007 (2026-07-29, commit 687c5c5)
# disabled it because standard/high-conviction stops (-7%/-9%) can never
# satisfy "return > -5%" — the 7-day tier was dead code for those tiers.
#
# v2 (2026-08-05): tiers are now based on offset_pct = how many percentage
# points *past the effective stop threshold that fired* the position has
# fallen. This is reachable regardless of conviction tier. Same underlying
# post-exit drift knowledge (shallow breach → recovers 78% of the time →
# wait longer; deep breach → rarely recovers → exit fast) is preserved.
# ────────────────────────────────────────────────────────────────

TIERED_LEVELS = [
    {"offset_pct": -2.0, "min_hold_days": 7},
    {"offset_pct": -5.0, "min_hold_days": 3},
]


def _make_strat_tiered(**kwargs) -> SimpleExitV2Strategy:
    defaults = dict(
        stop_loss_pct=-0.07,
        min_hold_days=1,
        min_hold_days_enabled=True,
        emergency_stop_bypass_pct=-0.12,
        tiered_min_hold_enabled=True,
        tiered_min_hold_levels=TIERED_LEVELS,
    )
    defaults.update(kwargs)
    return SimpleExitV2Strategy(**defaults)


def test_tiered_min_hold_disabled_uses_base():
    """When tiered_min_hold_enabled=False, _effective_min_hold_days returns base value."""
    strat = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        min_hold_days=3,
        tiered_min_hold_enabled=False,
        tiered_min_hold_levels=TIERED_LEVELS,
    )
    assert strat._effective_min_hold_days(-0.03, eff_stop_loss_pct=-0.07) == 3
    assert strat._effective_min_hold_days(-0.10, eff_stop_loss_pct=-0.07) == 3


def test_tiered_min_hold_noise_zone():
    """Shallow breach (offset > -2pp past the stop threshold): min_hold = 7 days."""
    strat = _make_strat_tiered()
    # eff_stop=-7%: return=-7.5% → offset=-0.5pp (shallow) → 7d
    assert strat._effective_min_hold_days(-0.075, eff_stop_loss_pct=-0.07) == 7
    # return=-7.01% → offset≈-0.01pp (barely breached) → 7d
    assert strat._effective_min_hold_days(-0.0701, eff_stop_loss_pct=-0.07) == 7


def test_tiered_min_hold_mid_zone():
    """Moderate breach (-5pp < offset <= -2pp): min_hold = 3 days."""
    strat = _make_strat_tiered()
    # eff_stop=-7%: return=-9.5% → offset=-2.5pp (clearly inside mid zone) → mid (3d)
    assert strat._effective_min_hold_days(-0.095, eff_stop_loss_pct=-0.07) == 3
    # return=-11% → offset=-4.0pp → mid
    assert strat._effective_min_hold_days(-0.11, eff_stop_loss_pct=-0.07) == 3


def test_tiered_min_hold_severe_zone():
    """Deep breach (offset <= -5pp): falls back to base min_hold_days (fast exit)."""
    strat = _make_strat_tiered()
    # eff_stop=-7%: return=-12.5% → offset=-5.5pp (clearly inside severe zone) → base (1d)
    assert strat._effective_min_hold_days(-0.125, eff_stop_loss_pct=-0.07) == 1
    # return=-15% → offset=-8.0pp → severe
    assert strat._effective_min_hold_days(-0.15, eff_stop_loss_pct=-0.07) == 1


def test_tiered_min_hold_reachable_at_low_conviction_threshold():
    """FIX-007 v2 regression: unlike v1, the noise tier must be reachable even
    when the effective stop threshold is the low-conviction -5% (the only
    tier that could reach v1's absolute -5% cutoff at all).
    """
    strat = _make_strat_tiered()
    # eff_stop=-5% (low conviction): return=-5.5% → offset=-0.5pp → noise (7d)
    assert strat._effective_min_hold_days(-0.055, eff_stop_loss_pct=-0.05) == 7


def test_tiered_min_hold_reachable_at_high_conviction_threshold():
    """FIX-007 v2 regression: the noise tier must also be reachable for the
    high-conviction -9% stop threshold, which v1's absolute -5% cutoff could
    never satisfy (return would need to be > -5% while also <= -9%).
    """
    strat = _make_strat_tiered()
    # eff_stop=-9% (high conviction): return=-9.5% → offset=-0.5pp → noise (7d)
    assert strat._effective_min_hold_days(-0.095, eff_stop_loss_pct=-0.09) == 7


def test_tiered_stop_suppressed_in_noise_zone_within_7d():
    """Shallow breach (-7.5%, standard -7% stop) with hold=3d < 7d → suppressed."""
    strat = _make_strat_tiered()
    current_price = 92.5  # -7.5% from 100, offset=-0.5pp past the -7% stop
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=72.0)  # 3 days
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 0, (
        f"Plan A v2: -7.5% loss (shallow breach) at 3d hold should be suppressed "
        f"(min_hold=7d), got: {signals}"
    )


def test_tiered_stop_fires_in_noise_zone_after_7d():
    """Shallow breach (-7.5%) with hold >= 7d → stop_loss fires normally."""
    strat = _make_strat_tiered()
    current_price = 92.5  # -7.5% from 100 → triggers stop_loss_pct=-7%, offset=-0.5pp
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=24 * 8)  # 8 days
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 1, (
        f"Plan A v2: -7.5% loss at 8d hold (>= 7d min_hold for noise zone) should fire, got: {signals}"
    )
    assert signals[0].action == "sell"
    assert "tiered" in signals[0].reasoning


def test_tiered_stop_suppressed_in_mid_zone_within_3d():
    """Moderate breach (-9.5%, offset=-2.5pp) with hold<3d → stop_loss suppressed."""
    strat = _make_strat_tiered()
    current_price = 90.5  # -9.5% from 100 → mid zone (offset=-2.5pp past -7% stop)
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=20.0)  # < 1 day
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 0, (
        f"Plan A v2: -9.5% at <1d hold (min_hold=3d for mid zone) should be suppressed, got: {signals}"
    )


def test_tiered_stop_fires_in_mid_zone_after_3d():
    """Moderate breach (-9.5%) with hold >= 3d → stop_loss fires."""
    strat = _make_strat_tiered()
    current_price = 90.5  # -9.5% → mid zone, triggers stop_loss_pct=-7%
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=24 * 4)  # 4 days
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 1, (
        f"Plan A v2: -9.5% at 4d hold (>= 3d min_hold for mid zone) should fire, got: {signals}"
    )
    assert signals[0].action == "sell"


def test_tiered_stop_fires_immediately_in_severe_zone():
    """Deep breach (-12.5%, offset=-5.5pp) → severe zone min_hold=1 day, fires after 1 day."""
    strat = _make_strat_tiered()
    current_price = 87.5  # -12.5% from 100 → severe zone (offset=-5.5pp past -7% stop)
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=26.0)  # 1+ day
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 1, (
        f"Plan A v2: -12.5% loss at 1+ day (severe zone min_hold=1d) should fire, got: {signals}"
    )
    assert signals[0].action == "sell"


def test_tiered_emergency_bypass_overrides_all_tiers():
    """emergency_stop_bypass_pct (-12%) overrides even the 7-day noise tier."""
    strat = _make_strat_tiered()
    current_price = 85.0  # -15%: breaches emergency_stop_bypass_pct=-12%
    pos = _make_position("TEST", 100.0, current_price, entry_hours_ago=2.0)  # well within 7d
    features = [_make_feature("TEST", current_price)]
    signals = strat.generate(features, {"TEST": pos})
    assert len(signals) == 1, (
        f"Plan A v2: emergency bypass should fire regardless of tiered min_hold, got: {signals}"
    )
    assert "Emergency stop" in signals[0].reasoning


def test_tiered_levels_sorted_correctly():
    """Tiered levels must be stored least-negative-offset-first for correct matching."""
    strat = _make_strat_tiered()
    levels = strat.tiered_min_hold_levels
    assert len(levels) == 2
    # Least-negative offset (-2.0, shallowest breach) must come before -5.0
    assert levels[0][0] > levels[1][0], "Levels must be sorted descending by offset_pct"
    assert levels[0] == (-2.0, 7)
    assert levels[1] == (-5.0, 3)
