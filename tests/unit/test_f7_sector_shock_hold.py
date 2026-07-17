"""F7 tests: sector_shock_hold shadow classifier."""
from __future__ import annotations

import pytest

from stock_swing.strategy_engine.sector_shock_hold import (
    ExitClassification,
    SectorShockAnalyzer,
    SectorShockHoldConfig,
)


def _default_config(**kwargs) -> SectorShockHoldConfig:
    defaults = dict(
        mode="shadow",
        benchmark_symbols=["SMH", "SOXX"],
        sector_shock_threshold_pct=-3.0,
        relative_weakness_max=2.0,
        max_hold_days_3=3,
        max_hold_days_5=5,
        max_hold_days_10=10,
        hard_loss_cap_pct=-15.0,
    )
    defaults.update(kwargs)
    return SectorShockHoldConfig(**defaults)


# ── hard_stop cases ───────────────────────────────────────────────────────────

def test_hard_loss_cap_triggers_hard_stop():
    """Return below emergency cap → always hard_stop regardless of sector."""
    config = _default_config()
    analyzer = SectorShockAnalyzer(config)
    result = analyzer.classify(
        symbol="NVDA",
        current_return_pct=-0.16,   # -16% < hard_loss_cap -15%
        symbol_1d_return_pct=-0.05,
        sector_1d_return_pcts={"SMH": -0.05, "SOXX": -0.05},
    )
    assert result.classification == "hard_stop"
    assert "hard_loss_cap" in result.reasoning[0]


def test_thesis_broken_always_hard_stop():
    config = _default_config()
    analyzer = SectorShockAnalyzer(config)
    result = analyzer.classify(
        symbol="DELL",
        current_return_pct=-0.06,
        symbol_1d_return_pct=-0.04,
        sector_1d_return_pcts={"SMH": -0.04, "SOXX": -0.04},
        is_thesis_broken=True,
    )
    assert result.classification == "hard_stop"


def test_portfolio_risk_limit_triggers_hard_stop():
    config = _default_config()
    analyzer = SectorShockAnalyzer(config)
    result = analyzer.classify(
        symbol="HPE",
        current_return_pct=-0.05,
        symbol_1d_return_pct=-0.03,
        sector_1d_return_pcts={"SMH": -0.04},
        exceeds_portfolio_risk_limit=True,
    )
    assert result.classification == "hard_stop"


# ── sector_shock_hold cases ───────────────────────────────────────────────────

def test_sector_shock_hold_when_broad_selloff():
    """Broad sector decline, symbol in line → sector_shock_hold."""
    config = _default_config()
    analyzer = SectorShockAnalyzer(config)
    result = analyzer.classify(
        symbol="AMAT",
        current_return_pct=-0.08,
        symbol_1d_return_pct=-0.045,    # roughly same as sector
        sector_1d_return_pcts={"SMH": -0.05, "SOXX": -0.048},  # avg = -4.9% → shock
    )
    assert result.classification == "sector_shock_hold"
    assert result.recommended_action == "hold"


def test_sector_shock_hold_partial_deRisk_at_5d():
    """After 5 trading days still in shock → partial exit recommended."""
    config = _default_config()
    analyzer = SectorShockAnalyzer(config)
    result = analyzer.classify(
        symbol="AMAT",
        current_return_pct=-0.07,
        symbol_1d_return_pct=-0.04,
        sector_1d_return_pcts={"SMH": -0.05, "SOXX": -0.05},
        days_held=5,
    )
    assert result.classification == "sector_shock_hold"
    assert result.recommended_action == "partial_exit"


# ── relative_weakness_exit cases ──────────────────────────────────────────────

def test_relative_weakness_exit_when_symbol_much_worse():
    """Symbol 3x worse than sector → relative_weakness_exit even in shock."""
    config = _default_config(relative_weakness_max=2.0)
    analyzer = SectorShockAnalyzer(config)
    result = analyzer.classify(
        symbol="DELL",
        current_return_pct=-0.12,
        symbol_1d_return_pct=-0.15,   # 3x worse than sector avg -0.05
        sector_1d_return_pcts={"SMH": -0.05, "SOXX": -0.05},
    )
    assert result.classification == "relative_weakness_exit"
    assert result.recommended_action == "exit"


# ── timeout cases ─────────────────────────────────────────────────────────────

def test_timeout_at_10_trading_days():
    config = _default_config()
    analyzer = SectorShockAnalyzer(config)
    result = analyzer.classify(
        symbol="NVDA",
        current_return_pct=-0.08,
        symbol_1d_return_pct=-0.03,
        sector_1d_return_pcts={"SMH": -0.04, "SOXX": -0.04},
        days_held=10,
    )
    assert result.classification == "recovery_hold_timeout"
    assert result.recommended_action == "exit"


# ── soft_stop cases ───────────────────────────────────────────────────────────

def test_soft_stop_when_no_sector_shock():
    """Sector is only down -1% → no shock; return soft_stop."""
    config = _default_config(sector_shock_threshold_pct=-3.0)
    analyzer = SectorShockAnalyzer(config)
    result = analyzer.classify(
        symbol="NVDA",
        current_return_pct=-0.07,
        symbol_1d_return_pct=-0.03,
        sector_1d_return_pcts={"SMH": -0.01, "SOXX": -0.01},  # only -1%
    )
    assert result.classification == "soft_stop"
    assert result.recommended_action == "monitor"


# ── shadow mode is_enabled ────────────────────────────────────────────────────

def test_shadow_mode_enabled():
    config = SectorShockHoldConfig(mode="shadow")
    assert SectorShockAnalyzer(config).is_enabled()


def test_disabled_mode():
    config = SectorShockHoldConfig(mode="disabled")
    assert not SectorShockAnalyzer(config).is_enabled()


# ── 2026-07-17 fix: sector_1d fallback · symbol_1d 修正の検証 ─────────────────────────────────

def test_no_sector_data_returns_hard_stop():
    """Empty sector_1d_return_pcts still returns hard_stop (no-data fallback)."""
    config = _default_config()
    analyzer = SectorShockAnalyzer(config)
    result = analyzer.classify(
        symbol="MDB",
        current_return_pct=-0.04,
        symbol_1d_return_pct=0.0,
        sector_1d_return_pcts={},  # データなし
    )
    assert result.classification == "hard_stop"
    assert any("no_sector_data" in r for r in result.reasoning)


def test_soft_stop_07_10_us_scenario():
    """07-11 JST (= 07-10 US): SMH +0.54%, SOXX -0.06% -- no sector shock.

    Before fix these were hard_stop due to no_sector_data.
    After fix (benchmark_returns.csv fallback) they become soft_stop.
    """
    config = _default_config()
    analyzer = SectorShockAnalyzer(config)
    # SMH/SOXX on 07-10 US: basically flat
    sector_1d = {"SMH": 0.0054, "SOXX": -0.0006}
    for sym, ret in [("CRWD", 0.035), ("MDB", -0.040), ("SNOW", -0.003)]:
        result = analyzer.classify(
            symbol=sym,
            current_return_pct=ret,
            symbol_1d_return_pct=0.0,
            sector_1d_return_pcts=sector_1d,
        )
        assert result.classification == "soft_stop", (
            f"{sym}: expected soft_stop, got {result.classification}"
        )
        assert result.recommended_action == "monitor"


def test_sector_shock_hold_07_16_us_scenario():
    """07-16 US: SMH -3.70%, SOXX -4.46% -- broad sector shock.

    NOW / DELL stop_loss classified as sector_shock_hold when benchmark data available.
    Previously hard_stop due to no_sector_data.
    """
    config = _default_config()
    analyzer = SectorShockAnalyzer(config)
    sector_1d = {"SMH": -0.0370, "SOXX": -0.0446}  # 07-16 actual values
    test_cases = [
        ("NOW",  -0.022, -0.018),
        ("DELL", -0.015, -0.040),
    ]
    for sym, ret, s1d in test_cases:
        result = analyzer.classify(
            symbol=sym,
            current_return_pct=ret,
            symbol_1d_return_pct=s1d,
            sector_1d_return_pcts=sector_1d,
        )
        assert result.classification == "sector_shock_hold", (
            f"{sym}: expected sector_shock_hold, got {result.classification}"
        )
        assert result.recommended_action == "hold"
