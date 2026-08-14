"""2026-08-14: tests for scripts/simulate_daily_path_volatility_stop.py's
replay_exit() -- the core priority-ordered daily-path exit replay used to
validate volatility_adjusted_stop_enabled against full trade history
(trailing_stop -> breakeven_stop -> stop_loss -> time_based, matching
SimpleExitV2Strategy.generate()'s exact evaluation order).

These tests use synthetic price paths (no network calls) to exercise each
branch of the priority order deterministically.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "simulate_daily_path_volatility_stop.py"
_spec = importlib.util.spec_from_file_location("simulate_daily_path_volatility_stop", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["simulate_daily_path_volatility_stop"] = _module
_spec.loader.exec_module(_module)

replay_exit = _module.replay_exit
PROD_CONFIG = _module.PROD_CONFIG

from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy


def _strategy(**overrides):
    cfg = dict(PROD_CONFIG)
    cfg.update(overrides)
    return SimpleExitV2Strategy(**cfg)


class TestReplayExitStopLoss:
    def test_stop_loss_fires_after_min_hold_when_deeply_breached(self):
        """A very deep, immediate loss (-15%, more than 5pp past the -7%
        standard threshold) should fire stop_loss quickly (base
        min_hold_days=1), not be suppressed by the tiered min_hold windows."""
        strat = _strategy(min_hold_days_enabled=True)
        entry_price = 100.0
        # Flat-ish path, immediately -15% and staying there (no bounce, no trailing/breakeven trigger).
        daily_path = [(f"2026-01-{i:02d}", 85.0) for i in range(2, 10)]
        result = replay_exit(strat, entry_price, entry_signal_strength=0.75, daily_closes=daily_path, volatility_multiplier=1.0)
        assert result["exit_reason"] == "stop_loss"
        assert result["hold_days"] == 1

    def test_stop_loss_suppressed_within_tiered_min_hold_noise_zone(self):
        """A shallow breach just past the standard -7% threshold (noise
        zone, offset_pct > -2pp) should be suppressed by tiered min_hold for
        several days, not fire on day 1."""
        strat = _strategy(min_hold_days_enabled=True, tiered_min_hold_enabled=True)
        entry_price = 100.0
        # -7.5% breach (offset -0.5pp from -7% threshold -> noise zone -> 7d min_hold)
        daily_path = [(f"2026-01-{i:02d}", 92.5) for i in range(2, 10)]
        result = replay_exit(strat, entry_price, entry_signal_strength=0.75, daily_closes=daily_path, volatility_multiplier=1.0)
        # Should not fire until day 7 (tiered min_hold), and by day 7 it does fire
        # (return still -7.5% <= -7% threshold).
        assert result["exit_reason"] == "stop_loss"
        assert result["hold_days"] == 7

    def test_widened_threshold_avoids_stop_loss_that_baseline_would_hit(self):
        """A -8% breach: baseline (-7% threshold, multiplier has no effect
        while volatility_adjusted_stop_enabled=False) fires stop_loss; the
        same multiplier=1.5 WITH volatility_adjusted_stop_enabled=True
        widens the threshold to -10.5% and should NOT fire on the same
        path."""
        strat_baseline = _strategy(min_hold_days_enabled=False, volatility_adjusted_stop_enabled=False)
        strat_adjusted = _strategy(min_hold_days_enabled=False, volatility_adjusted_stop_enabled=True)
        entry_price = 100.0
        daily_path = [(f"2026-01-{i:02d}", 92.0) for i in range(2, 10)]  # flat -8%

        baseline = replay_exit(strat_baseline, entry_price, 0.75, daily_path, volatility_multiplier=1.5)
        widened = replay_exit(strat_adjusted, entry_price, 0.75, daily_path, volatility_multiplier=1.5)

        assert baseline["exit_reason"] == "stop_loss"  # multiplier ignored (feature disabled)
        assert widened["exit_reason"] == "still_open"  # multiplier applied (feature enabled)

    def test_tightened_threshold_fires_earlier_than_baseline(self):
        """A gradual decline: a tightened threshold (with the feature
        enabled) should trigger stop_loss sooner (at a shallower loss) than
        the baseline (feature disabled, multiplier ignored)."""
        strat_baseline = _strategy(min_hold_days_enabled=False, volatility_adjusted_stop_enabled=False)
        strat_adjusted = _strategy(min_hold_days_enabled=False, volatility_adjusted_stop_enabled=True)
        entry_price = 100.0
        # Gradual decline: day1=-2%, day2=-4%, day3=-6%, day4=-8%
        daily_path = [
            ("2026-01-02", 98.0), ("2026-01-03", 96.0),
            ("2026-01-04", 94.0), ("2026-01-05", 92.0),
        ]
        baseline = replay_exit(strat_baseline, entry_price, 0.75, daily_path, volatility_multiplier=0.5)
        tightened = replay_exit(strat_adjusted, entry_price, 0.75, daily_path, volatility_multiplier=0.5)  # -3.5% eff threshold

        # baseline (-7%, multiplier ignored) fires on day4 (-8%);
        # tightened (enabled, -3.5% eff threshold) fires earlier on day2 (-4%)
        assert baseline["hold_days"] > tightened["hold_days"]
        assert tightened["exit_reason"] == "stop_loss"


class TestReplayExitTrailingStopPriority:
    def test_trailing_stop_takes_priority_over_stop_loss(self):
        """Once trailing_stop is active (peak return exceeded activation),
        it must be evaluated BEFORE stop_loss, even if the current return
        would also breach the stop_loss threshold."""
        strat = _strategy(min_hold_days_enabled=False)
        entry_price = 100.0
        # Day1: rally to +10% (activates trailing, peak=110). Day2: crash to 91
        # (-9% from entry, breaches stop_loss AND pulls back >3.5% from peak=110
        # -> both trailing_stop and stop_loss conditions are technically met;
        # trailing_stop must win since it's checked first).
        daily_path = [("2026-01-02", 110.0), ("2026-01-03", 91.0)]
        result = replay_exit(strat, entry_price, 0.75, daily_path, volatility_multiplier=1.0)
        assert result["exit_reason"] == "trailing_stop"

    def test_no_trailing_activation_falls_through_to_stop_loss(self):
        """Without reaching trailing activation, a stop_loss breach fires
        stop_loss as normal."""
        strat = _strategy(min_hold_days_enabled=False)
        entry_price = 100.0
        daily_path = [("2026-01-02", 92.0)]  # -8%, never rallied
        result = replay_exit(strat, entry_price, 0.75, daily_path, volatility_multiplier=1.0)
        assert result["exit_reason"] == "stop_loss"


class TestReplayExitBreakevenPriority:
    def test_breakeven_stop_takes_priority_over_stop_loss(self):
        """Once breakeven is activated (peak >= breakeven_activation_pct)
        but trailing not yet active, breakeven_stop must be checked before
        stop_loss.

        staged_trailing_enabled is turned off for this test: PROD_CONFIG's
        first staged_trailing level activates at the same 5% peak return as
        breakeven_activation_pct, which would make trailing_stop activate
        simultaneously with breakeven and take priority (as tested
        separately in TestReplayExitTrailingStopPriority) -- not useful for
        isolating breakeven's own priority-ordering behavior. With staged
        trailing disabled, the flat trailing_activation_pct=0.08 (8%)
        applies instead, giving a clean gap between breakeven (5%) and
        trailing (8%) activation.
        """
        strat = _strategy(min_hold_days_enabled=False, staged_trailing_enabled=False)
        entry_price = 100.0
        # Day1: peak +6% (activates breakeven at 5%, but below flat trailing
        # activation 8% since staged_trailing is disabled here). Day2: drops
        # to 91 (-9%, breaches both breakeven floor 0% and stop_loss -7%) --
        # breakeven_stop must win.
        daily_path = [("2026-01-02", 106.0), ("2026-01-03", 91.0)]
        result = replay_exit(strat, entry_price, 0.75, daily_path, volatility_multiplier=1.0)
        assert result["exit_reason"] == "breakeven_stop"


class TestReplayExitTimeBased:
    def test_time_based_exit_after_max_hold_days_with_no_other_trigger(self):
        strat = _strategy(min_hold_days_enabled=False, max_hold_days=5)
        entry_price = 100.0
        # Flat +2% the whole time -- never triggers trailing/breakeven/stop_loss.
        daily_path = [(f"2026-01-{i:02d}", 102.0) for i in range(2, 10)]
        result = replay_exit(strat, entry_price, 0.75, daily_path, volatility_multiplier=1.0)
        assert result["exit_reason"] == "time_based"
        assert result["hold_days"] == 5

    def test_still_open_when_data_runs_out_before_any_exit(self):
        strat = _strategy(min_hold_days_enabled=False, max_hold_days=20)
        entry_price = 100.0
        daily_path = [("2026-01-02", 101.0), ("2026-01-03", 102.0)]  # short path, no trigger
        result = replay_exit(strat, entry_price, 0.75, daily_path, volatility_multiplier=1.0)
        assert result["exit_reason"] == "still_open"
        assert result["exit_date"] is None


class TestReplayExitEntrySignalStrengthTiers:
    def test_high_conviction_uses_wider_base_stop(self):
        """High conviction (strength>=0.85) uses -9% base stop, not -7%."""
        strat = _strategy(min_hold_days_enabled=False)
        entry_price = 100.0
        daily_path = [("2026-01-02", 92.0)]  # -8%: breaches standard -7% but not high-conviction -9%
        result_high = replay_exit(strat, entry_price, 0.90, daily_path, volatility_multiplier=1.0)
        result_standard = replay_exit(strat, entry_price, 0.75, daily_path, volatility_multiplier=1.0)
        assert result_high["exit_reason"] == "still_open"
        assert result_standard["exit_reason"] == "stop_loss"

    def test_low_conviction_uses_tighter_base_stop(self):
        """Low conviction (strength<0.65) uses -5% base stop, tighter than standard -7%."""
        strat = _strategy(min_hold_days_enabled=False)
        entry_price = 100.0
        daily_path = [("2026-01-02", 94.0)]  # -6%: breaches low-conviction -5% but not standard -7%
        result_low = replay_exit(strat, entry_price, 0.50, daily_path, volatility_multiplier=1.0)
        result_standard = replay_exit(strat, entry_price, 0.75, daily_path, volatility_multiplier=1.0)
        assert result_low["exit_reason"] == "stop_loss"
        assert result_standard["exit_reason"] == "still_open"

    def test_missing_strength_graduates_to_standard_tier(self):
        """replay_exit() resolves thresholds once at hold_days=999 (see its
        docstring: "assume graduated; simplification for path replay"), so
        a missing entry_signal_strength graduates straight to the standard
        -7% tier (broker_recon_graduation_days=5 <= 999), not the -5%
        low-conviction tier a freshly-opened broker-reconstructed position
        would actually get in production. A -6% breach is therefore NOT
        expected to fire here (it would fire under the live code's
        pre-graduation -5% tier, but not under this replay's post-graduation
        approximation) -- this test documents that known simplification."""
        strat = _strategy(min_hold_days_enabled=False)
        entry_price = 100.0
        daily_path = [("2026-01-02", 94.0)]  # -6%: breaches -5% low tier, not -7% standard tier
        result = replay_exit(strat, entry_price, None, daily_path, volatility_multiplier=1.0)
        assert result["exit_reason"] == "still_open"


class TestComputeAtrPctAtEntry:
    def test_returns_none_on_fetch_failure(self, monkeypatch):
        """A symbol/date combo with no fetchable data must return None, not
        raise."""
        def _boom(*a, **kw):
            raise RuntimeError("network unavailable")

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", _boom)
        result = _module.compute_atr_pct_at_entry("NOSUCHSYMBOL", "2026-01-05")
        assert result is None
