"""2026-08-14: sector_shock_hold rolling N-day shock detection tests.

Fixes the root cause of sector_shock_shadow_count staying at 0 for months:
a genuine sector-wide shock (e.g. 2026-06-05 SMH -9.2%) can partially bounce
back the next day (2026-06-08 SMH +5.0%) while remaining deeply negative on
a rolling multi-day basis, and stop_loss decisions typically fire a few days
after the initial shock day (not on the shock day itself), so a same-day-only
check systematically misses this pattern.

See docs/daily_logs/2026-08-14.md "Stop Loss 再設計" and
SectorShockHoldConfig.sector_shock_rolling_days docstring for full context.
"""
from __future__ import annotations

from stock_swing.strategy_engine.sector_shock_hold import (
    SectorShockAnalyzer,
    SectorShockHoldConfig,
)


def _default_config(**kwargs) -> SectorShockHoldConfig:
    defaults = dict(
        mode="shadow",
        benchmark_symbols=["SMH", "SOXX"],
        sector_shock_threshold_pct=-3.0,
        sector_shock_rolling_days=3,
        sector_shock_rolling_threshold_pct=-5.0,
        relative_weakness_max=2.0,
        max_hold_days_3=3,
        max_hold_days_5=5,
        max_hold_days_10=10,
        hard_loss_cap_pct=-15.0,
    )
    defaults.update(kwargs)
    return SectorShockHoldConfig(**defaults)


class TestBackwardCompatibility:
    """Omitting sector_rolling_return_pcts must preserve prior (pre-2026-08-14)
    behavior exactly -- only the single-day check applies."""

    def test_none_rolling_arg_preserves_single_day_only_behavior(self):
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="AMAT",
            current_return_pct=-0.08,
            symbol_1d_return_pct=-0.045,
            sector_1d_return_pcts={"SMH": -0.05, "SOXX": -0.048},
            sector_rolling_return_pcts=None,
        )
        assert result.classification == "sector_shock_hold"
        assert "sector_shock_detected_1d" in result.shadow_log
        assert result.shadow_log["sector_shock_detected_1d"] is True
        assert "sector_shock_detected_rolling" not in result.shadow_log

    def test_empty_dict_rolling_arg_no_effect(self):
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="AMAT",
            current_return_pct=-0.02,
            symbol_1d_return_pct=-0.01,
            sector_1d_return_pcts={"SMH": -0.01, "SOXX": -0.01},  # no single-day shock
            sector_rolling_return_pcts={},
        )
        assert result.classification == "soft_stop"

    def test_single_day_shock_still_works_without_rolling_data(self):
        """No rolling data provided, but single-day threshold breached ->
        still classified as sector_shock_hold as before."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="AMAT",
            current_return_pct=-0.06,
            symbol_1d_return_pct=-0.05,
            sector_1d_return_pcts={"SMH": -0.05, "SOXX": -0.05},
        )
        assert result.classification == "sector_shock_hold"


class TestRollingShockDetection:
    """The new capability: detect a shock via rolling cumulative return even
    when the single-day check does not trigger."""

    def test_rolling_shock_detected_when_single_day_misses(self):
        """Reproduces the 2026-06-08 scenario: single-day SMH/SOXX return is
        positive (post-shock bounce) but rolling 3d return is still deeply
        negative from the 06-05 shock."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="AMAT",
            current_return_pct=-0.07,
            symbol_1d_return_pct=-0.045,  # roughly in line with sector rolling avg
            sector_1d_return_pcts={"SMH": 0.05, "SOXX": 0.0587},  # positive single-day (bounce)
            sector_rolling_return_pcts={"SMH": -0.0623, "SOXX": -0.0718},  # deeply negative rolling
        )
        assert result.classification == "sector_shock_hold"
        assert result.shadow_log["sector_shock_detected_1d"] is False
        assert result.shadow_log["sector_shock_detected_rolling"] is True
        assert result.shadow_log["sector_shock_detected"] is True
        assert any("rolling" in r for r in result.reasoning)

    def test_rolling_shock_uses_rolling_avg_for_relative_weakness(self):
        """When only the rolling check triggers, the relative-weakness ratio
        (Rule 6) must use the rolling average, not the (positive) single-day
        average -- otherwise the ratio computation would be nonsensical
        (dividing by a positive number when the symbol itself is negative)."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="AMAT",
            current_return_pct=-0.14,  # below hard_loss_cap (-15%) so Rule 1 doesn't short-circuit
            symbol_1d_return_pct=-0.20,  # much worse than rolling sector avg
            sector_1d_return_pcts={"SMH": 0.05, "SOXX": 0.0587},
            sector_rolling_return_pcts={"SMH": -0.0623, "SOXX": -0.0718},
        )
        # symbol (-0.20) is more than 2x worse than rolling avg (~-0.067)
        # -> should be relative_weakness_exit, not sector_shock_hold
        assert result.classification == "relative_weakness_exit"

    def test_rolling_not_severe_enough_no_shock(self):
        """Rolling return breaches neither threshold -> soft_stop as usual."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="AMAT",
            current_return_pct=-0.04,
            symbol_1d_return_pct=-0.01,
            sector_1d_return_pcts={"SMH": 0.01, "SOXX": 0.01},
            sector_rolling_return_pcts={"SMH": -0.02, "SOXX": -0.015},  # not below -5%
        )
        assert result.classification == "soft_stop"

    def test_single_day_shock_takes_precedence_when_both_trigger(self):
        """When both single-day and rolling checks would trigger, single-day
        average is used as avg_sector_return (it was already detected first;
        the rolling branch only activates when single-day did NOT trigger)."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="AMAT",
            current_return_pct=-0.08,
            symbol_1d_return_pct=-0.05,
            sector_1d_return_pcts={"SMH": -0.05, "SOXX": -0.05},  # single-day shock
            sector_rolling_return_pcts={"SMH": -0.08, "SOXX": -0.09},  # also rolling shock
        )
        assert result.classification == "sector_shock_hold"
        assert result.shadow_log["sector_shock_detected_1d"] is True
        # avg_sector_return_pct should reflect the single-day average (-5.0),
        # not the rolling average, since Rule 5 (single-day) already set it.
        assert result.shadow_log["avg_sector_return_pct"] == -5.0

    def test_custom_rolling_threshold_respected(self):
        config = _default_config(sector_shock_rolling_threshold_pct=-10.0)
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="AMAT",
            current_return_pct=-0.07,
            symbol_1d_return_pct=-0.06,
            sector_1d_return_pcts={"SMH": 0.01, "SOXX": 0.01},
            sector_rolling_return_pcts={"SMH": -0.06, "SOXX": -0.07},  # -6.5% avg, above -10% threshold
        )
        assert result.classification == "soft_stop"  # -5% default would trigger, but -10% threshold doesn't

    def test_hard_loss_cap_still_takes_priority_over_rolling_shock(self):
        """Rule 1 (hard loss cap) must still short-circuit before rolling
        shock detection runs at all."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="AMAT",
            current_return_pct=-0.20,  # breaches -15% hard cap
            symbol_1d_return_pct=-0.05,
            sector_1d_return_pcts={"SMH": 0.05},
            sector_rolling_return_pcts={"SMH": -0.09},
        )
        assert result.classification == "hard_stop"


class TestSectorShockHoldConfigRollingDefaults:
    def test_default_rolling_days_is_3(self):
        config = SectorShockHoldConfig()
        assert config.sector_shock_rolling_days == 3

    def test_default_rolling_threshold_is_minus_5(self):
        config = SectorShockHoldConfig()
        assert config.sector_shock_rolling_threshold_pct == -5.0

    def test_from_env_reads_rolling_overrides(self, monkeypatch):
        monkeypatch.setenv("SECTOR_SHOCK_ROLLING_DAYS", "5")
        monkeypatch.setenv("SECTOR_SHOCK_ROLLING_THRESHOLD_PCT", "-7.5")
        config = SectorShockHoldConfig.from_env()
        assert config.sector_shock_rolling_days == 5
        assert config.sector_shock_rolling_threshold_pct == -7.5

    def test_from_env_defaults_when_unset(self, monkeypatch):
        monkeypatch.delenv("SECTOR_SHOCK_ROLLING_DAYS", raising=False)
        monkeypatch.delenv("SECTOR_SHOCK_ROLLING_THRESHOLD_PCT", raising=False)
        config = SectorShockHoldConfig.from_env()
        assert config.sector_shock_rolling_days == 3
        assert config.sector_shock_rolling_threshold_pct == -5.0
