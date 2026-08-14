"""2026-08-14: Volatility-adjusted stop loss tests (Stop Loss role-purification
redesign).

Covers SimpleExitV2Strategy.compute_volatility_multiplier() (pure function)
and its wiring into _resolve_thresholds() / generate(). The conviction-tier
stop thresholds (-5/-7/-9%) are fixed percentages that don't account for a
symbol's actual volatility; this widens/tightens them per-symbol relative to
the cross-sectional universe average ATR% for the current run.

Disabled by default (volatility_adjusted_stop_enabled=False); all tests
confirm both the opt-in behavior and that default (disabled) behavior is
unchanged from before this feature existed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy


# ---------------------------------------------------------------------------
# compute_volatility_multiplier (pure function)
# ---------------------------------------------------------------------------

class TestComputeVolatilityMultiplier:
    def test_symbol_at_universe_average_returns_one(self):
        m = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=0.03, universe_avg_atr_pct=0.03,
        )
        assert m == 1.0

    def test_higher_than_average_widens_multiplier(self):
        m = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=0.045, universe_avg_atr_pct=0.03,
        )
        assert m == 1.5

    def test_lower_than_average_tightens_multiplier(self):
        m = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=0.015, universe_avg_atr_pct=0.03,
        )
        assert m == 0.5

    def test_extreme_high_volatility_clamped_to_max(self):
        m = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=0.30, universe_avg_atr_pct=0.03,  # ratio=10.0
            max_multiplier=1.75,
        )
        assert m == 1.75

    def test_extreme_low_volatility_clamped_to_min(self):
        m = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=0.001, universe_avg_atr_pct=0.03,  # ratio~0.03
            min_multiplier=0.5,
        )
        assert m == 0.5

    def test_none_symbol_atr_returns_neutral_one(self):
        m = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=None, universe_avg_atr_pct=0.03,
        )
        assert m == 1.0

    def test_none_universe_avg_returns_neutral_one(self):
        m = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=0.03, universe_avg_atr_pct=None,
        )
        assert m == 1.0

    def test_zero_universe_avg_returns_neutral_one(self):
        """Fail-safe: division by zero must never occur."""
        m = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=0.03, universe_avg_atr_pct=0.0,
        )
        assert m == 1.0

    def test_negative_atr_returns_neutral_one(self):
        """Degenerate/corrupt ATR data must not produce a nonsensical multiplier."""
        m = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=-0.02, universe_avg_atr_pct=0.03,
        )
        assert m == 1.0

    def test_custom_clamp_bounds_respected(self):
        m = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=0.09, universe_avg_atr_pct=0.03,  # ratio=3.0
            min_multiplier=0.8, max_multiplier=1.2,
        )
        assert m == 1.2


# ---------------------------------------------------------------------------
# _resolve_thresholds integration with volatility_multiplier
# ---------------------------------------------------------------------------

class TestResolveThresholdsVolatilityIntegration:
    def test_disabled_ignores_multiplier(self):
        """When volatility_adjusted_stop_enabled=False (default), passing a
        non-1.0 multiplier must have zero effect -- existing behavior
        preserved exactly."""
        strat = SimpleExitV2Strategy(stop_loss_pct=-0.07, volatility_adjusted_stop_enabled=False)
        stop, trailing = strat._resolve_thresholds(
            entry_signal_strength=0.75, volatility_multiplier=1.5,
        )
        assert stop == -0.07  # standard tier, unaffected by multiplier

    def test_enabled_widens_standard_tier_stop(self):
        strat = SimpleExitV2Strategy(stop_loss_pct=-0.07, volatility_adjusted_stop_enabled=True)
        stop, trailing = strat._resolve_thresholds(
            entry_signal_strength=0.75, volatility_multiplier=1.3,
        )
        assert stop == pytest.approx(-0.091)  # -0.07 * 1.3

    def test_enabled_tightens_standard_tier_stop(self):
        strat = SimpleExitV2Strategy(stop_loss_pct=-0.07, volatility_adjusted_stop_enabled=True)
        stop, trailing = strat._resolve_thresholds(
            entry_signal_strength=0.75, volatility_multiplier=0.7,
        )
        assert stop == pytest.approx(-0.049)  # -0.07 * 0.7

    def test_enabled_applies_to_high_conviction_tier_too(self):
        strat = SimpleExitV2Strategy(volatility_adjusted_stop_enabled=True)
        stop, trailing = strat._resolve_thresholds(
            entry_signal_strength=0.90, volatility_multiplier=1.2,  # high conviction
        )
        assert stop == pytest.approx(-0.108)  # -0.09 * 1.2
        assert trailing == 0.06  # trailing_activation unaffected by volatility

    def test_enabled_applies_to_low_conviction_tier_too(self):
        strat = SimpleExitV2Strategy(volatility_adjusted_stop_enabled=True)
        stop, trailing = strat._resolve_thresholds(
            entry_signal_strength=0.50, volatility_multiplier=1.5,  # low conviction
        )
        assert stop == pytest.approx(-0.075)  # -0.05 * 1.5

    def test_enabled_applies_to_missing_strength_tier(self):
        strat = SimpleExitV2Strategy(volatility_adjusted_stop_enabled=True)
        stop, trailing = strat._resolve_thresholds(
            entry_signal_strength=None, hold_days=1, volatility_multiplier=1.4,
        )
        assert stop == pytest.approx(-0.07)  # -0.05 * 1.4

    def test_multiplier_of_one_is_a_no_op_even_when_enabled(self):
        strat = SimpleExitV2Strategy(stop_loss_pct=-0.07, volatility_adjusted_stop_enabled=True)
        stop, _ = strat._resolve_thresholds(entry_signal_strength=0.75, volatility_multiplier=1.0)
        assert stop == -0.07

    def test_trailing_activation_never_volatility_adjusted(self):
        """trailing_activation_pct must remain fixed regardless of enabled
        state or multiplier -- volatility adjustment is scoped only to the
        stop_loss branch."""
        strat = SimpleExitV2Strategy(volatility_adjusted_stop_enabled=True)
        _, trailing_disabled = strat._resolve_thresholds(0.75, volatility_multiplier=1.0)
        _, trailing_enabled = strat._resolve_thresholds(0.75, volatility_multiplier=2.0)
        assert trailing_disabled == trailing_enabled == 0.08


# ---------------------------------------------------------------------------
# End-to-end generate() integration
# ---------------------------------------------------------------------------

def _feature(symbol: str, latest_close: float, atr: float | None) -> FeatureResult:
    values = {"latest_close": latest_close}
    if atr is not None:
        values["atr"] = atr
    return FeatureResult(
        feature_name="price_momentum",
        symbol=symbol,
        computed_at=datetime.now(timezone.utc),
        values=values,
    )


class TestGenerateEndToEndVolatilityAdjustment:
    def test_disabled_default_stop_loss_unaffected_by_atr(self):
        """With the feature disabled (default), a high-ATR symbol must fire
        stop_loss at exactly the standard -7% threshold, same as before this
        feature existed."""
        strat = SimpleExitV2Strategy(
            stop_loss_pct=-0.07, trailing_activation_pct=0.08, max_hold_days=20,
            min_hold_days_enabled=False,  # isolate stop_loss firing from min_hold suppression
        )
        features = [
            _feature("HIVOL", 93.0, atr=10.0),  # huge ATR% (10.75%)
            _feature("LOVOL", 98.0, atr=0.5),    # tiny ATR%
        ]
        positions = {
            "HIVOL": {
                "qty": 100, "avg_entry_price": 100.0, "current_price": 93.0,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
            },
        }
        signals = strat.generate(features, positions)
        assert len(signals) == 1
        assert signals[0].metadata["eff_stop_loss_pct"] == -0.07

    def test_enabled_high_atr_symbol_gets_wider_threshold_and_does_not_fire(self):
        """With the feature enabled, a symbol with ATR% far above the
        universe average should get a widened stop threshold, so a -7%
        return that would have fired the standard stop no longer does."""
        strat = SimpleExitV2Strategy(
            stop_loss_pct=-0.07, trailing_activation_pct=0.08, max_hold_days=20,
            min_hold_days_enabled=False,
            volatility_adjusted_stop_enabled=True,
            volatility_multiplier_max=1.75,
        )
        # HIVOL: atr=10 on close=100 -> atr_pct=0.10 (10%)
        # LOVOL: atr=1 on close=100 -> atr_pct=0.01 (1%)
        # universe_avg_atr_pct = (0.10 + 0.01) / 2 = 0.055
        # HIVOL multiplier = 0.10 / 0.055 = 1.818 -> clamped to 1.75
        # effective stop = -0.07 * 1.75 = -0.1225 (-12.25%)
        features = [
            _feature("HIVOL", 100.0, atr=10.0),
            _feature("LOVOL", 100.0, atr=1.0),
        ]
        positions = {
            "HIVOL": {
                "qty": 100, "avg_entry_price": 100.0, "current_price": 93.0,  # -7%
                "created_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
            },
        }
        signals = strat.generate(features, positions)
        # -7% return is now above the widened -12.25% threshold -> no exit
        assert len(signals) == 0

    def test_enabled_low_atr_symbol_gets_tighter_threshold_and_fires_earlier(self):
        """A below-average-volatility symbol should get its stop threshold
        tightened, firing at a smaller loss than the standard -7%."""
        strat = SimpleExitV2Strategy(
            stop_loss_pct=-0.07, trailing_activation_pct=0.08, max_hold_days=20,
            min_hold_days_enabled=False,
            volatility_adjusted_stop_enabled=True,
            volatility_multiplier_min=0.5,
        )
        # LOVOL: atr=1 on close=100 -> atr_pct=0.01
        # HIVOL: atr=10 on close=100 -> atr_pct=0.10
        # universe_avg = 0.055
        # LOVOL multiplier = 0.01/0.055 = 0.1818 -> clamped to 0.5
        # effective stop = -0.07 * 0.5 = -0.035 (-3.5%)
        features = [
            _feature("HIVOL", 100.0, atr=10.0),
            _feature("LOVOL", 100.0, atr=1.0),
        ]
        positions = {
            "LOVOL": {
                "qty": 100, "avg_entry_price": 100.0, "current_price": 96.0,  # -4%
                "created_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
            },
        }
        signals = strat.generate(features, positions)
        # -4% breaches the tightened -3.5% threshold -> exit fires
        assert len(signals) == 1
        assert signals[0].metadata["eff_stop_loss_pct"] == pytest.approx(-0.035)
        assert signals[0].metadata["volatility_adjusted_stop_enabled"] is True
        assert signals[0].metadata["volatility_multiplier"] == pytest.approx(0.5)

    def test_missing_atr_falls_back_to_neutral_multiplier(self):
        """A symbol with no ATR data (e.g. insufficient bar history) must
        fall back to multiplier=1.0 (unchanged threshold), not crash or be
        skipped."""
        strat = SimpleExitV2Strategy(
            stop_loss_pct=-0.07, trailing_activation_pct=0.08, max_hold_days=20,
            min_hold_days_enabled=False,
            volatility_adjusted_stop_enabled=True,
        )
        features = [
            _feature("NOATR", 100.0, atr=None),
            _feature("HIVOL", 100.0, atr=10.0),
        ]
        positions = {
            "NOATR": {
                "qty": 100, "avg_entry_price": 100.0, "current_price": 93.0,  # -7%
                "created_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
            },
        }
        signals = strat.generate(features, positions)
        assert len(signals) == 1
        assert signals[0].metadata["eff_stop_loss_pct"] == -0.07  # neutral, unchanged
        assert signals[0].metadata["volatility_multiplier"] == 1.0

    def test_no_atr_data_anywhere_no_op(self):
        """When no symbol in the run has ATR data, universe_avg_atr_pct stays
        None and every position gets the neutral multiplier (no crash)."""
        strat = SimpleExitV2Strategy(
            stop_loss_pct=-0.07, max_hold_days=20, min_hold_days_enabled=False,
            volatility_adjusted_stop_enabled=True,
        )
        features = [_feature("AAPL", 100.0, atr=None)]
        positions = {
            "AAPL": {
                "qty": 100, "avg_entry_price": 100.0, "current_price": 93.0,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
            },
        }
        signals = strat.generate(features, positions)
        assert len(signals) == 1
        assert signals[0].metadata["eff_stop_loss_pct"] == -0.07
