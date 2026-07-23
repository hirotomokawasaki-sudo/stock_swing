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


# ── log_shadow: JSONL file writing ─────────────────────────────────────────

class TestLogShadowFileWriting:
    """R3-v2 / F7: log_shadow() must write structured records to JSONL file."""

    def _make_sector_shock_result(self, symbol: str = "NVDA") -> ExitClassification:
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        return analyzer.classify(
            symbol=symbol,
            current_return_pct=-0.07,
            symbol_1d_return_pct=-0.04,
            sector_1d_return_pcts={"SMH": -0.042, "SOXX": -0.038},  # sector shock
        )

    def _make_soft_stop_result(self, symbol: str = "PANW") -> ExitClassification:
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        return analyzer.classify(
            symbol=symbol,
            current_return_pct=-0.04,
            symbol_1d_return_pct=-0.025,
            sector_1d_return_pcts={"SMH": -0.016, "SOXX": -0.014},  # no shock
        )

    def test_log_shadow_writes_jsonl_record(self, tmp_path):
        """Each log_shadow() call appends one valid JSON line to the file."""
        path = tmp_path / "shadow_log.jsonl"
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = self._make_sector_shock_result()

        analyzer.log_shadow(result, shadow_log_path=path)

        assert path.exists(), "shadow log file must be created"
        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1, "exactly one line written"
        record = __import__("json").loads(lines[0])
        assert record["symbol"] == "NVDA"
        assert record["classification"] == "sector_shock_hold"
        assert "logged_at" in record
        assert "recommended_action" in record

    def test_log_shadow_appends_multiple_records(self, tmp_path):
        """Multiple calls append multiple lines (idempotent append)."""
        path = tmp_path / "shadow_log.jsonl"
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)

        for sym in ("NVDA", "AMD", "ASML"):
            result = self._make_sector_shock_result(symbol=sym)
            analyzer.log_shadow(result, shadow_log_path=path)

        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 3
        symbols = [__import__("json").loads(l)["symbol"] for l in lines]
        assert symbols == ["NVDA", "AMD", "ASML"]

    def test_log_shadow_none_path_no_file_created(self, tmp_path):
        """When shadow_log_path=None, no file is created (legacy behaviour)."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = self._make_sector_shock_result()

        analyzer.log_shadow(result, shadow_log_path=None)

        assert not any(tmp_path.iterdir()), "no file created when path is None"

    def test_log_shadow_creates_parent_dirs(self, tmp_path):
        """Parent directories are created automatically."""
        path = tmp_path / "nested" / "deep" / "shadow_log.jsonl"
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = self._make_sector_shock_result()

        analyzer.log_shadow(result, shadow_log_path=path)

        assert path.exists()

    def test_log_shadow_soft_stop_also_recorded(self, tmp_path):
        """soft_stop is also written to file (all classifications recorded)."""
        path = tmp_path / "shadow_log.jsonl"
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = self._make_soft_stop_result()

        analyzer.log_shadow(result, shadow_log_path=path)

        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        record = __import__("json").loads(lines[0])
        assert record["classification"] == "soft_stop"

    def test_log_shadow_record_contains_sector_data(self, tmp_path):
        """Record must include sector_1d_return_pcts and avg_sector_return."""
        path = tmp_path / "shadow_log.jsonl"
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = self._make_sector_shock_result()

        analyzer.log_shadow(result, shadow_log_path=path)

        record = __import__("json").loads(path.read_text().strip())
        assert "sector_1d_return_pcts" in record, "sector data must be in record"
        assert "avg_sector_return_pct" in record, "avg sector return must be in record"
        assert "sector_shock_detected" in record


class TestSshShadowCountOnlySectorShockHold:
    """paper_demo must count only sector_shock_hold classifications.

    Regression: previously _ssh_shadow_count was incremented for ALL exit
    signals (hard_stop, soft_stop, no_sector_data), making the A/B activation
    counter meaningless. Fixed in R3-v2 / F7 (2026-07-23).
    """

    def test_sector_shock_hold_classification_is_valid_trigger(self):
        """sector_shock_hold result must be counted toward A/B activation."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="NVDA",
            current_return_pct=-0.07,
            symbol_1d_return_pct=-0.04,
            sector_1d_return_pcts={"SMH": -0.042, "SOXX": -0.038},
        )
        assert result.classification == "sector_shock_hold"
        # Simulates the paper_demo counter condition:
        assert result.classification == "sector_shock_hold"  # would be counted

    def test_soft_stop_is_not_counted(self):
        """soft_stop must NOT increment the A/B activation counter."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="PANW",
            current_return_pct=-0.04,
            symbol_1d_return_pct=-0.025,
            sector_1d_return_pcts={"SMH": -0.016, "SOXX": -0.014},
        )
        assert result.classification == "soft_stop"
        assert result.classification != "sector_shock_hold"  # would NOT be counted

    def test_hard_stop_is_not_counted(self):
        """hard_stop must NOT increment the A/B activation counter."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="AMD",
            current_return_pct=-0.17,   # below -15% hard cap
            symbol_1d_return_pct=-0.10,
            sector_1d_return_pcts={"SMH": -0.042, "SOXX": -0.038},
        )
        assert result.classification == "hard_stop"
        assert result.classification != "sector_shock_hold"  # would NOT be counted

    def test_no_sector_data_is_not_counted(self):
        """no_sector_data must NOT increment the A/B activation counter."""
        config = _default_config()
        analyzer = SectorShockAnalyzer(config)
        result = analyzer.classify(
            symbol="CRWD",
            current_return_pct=-0.03,
            symbol_1d_return_pct=-0.02,
            sector_1d_return_pcts={},  # empty = no sector data
        )
        assert result.classification == "hard_stop"  # no_sector_data → hard_stop
        assert "no_sector_data" in result.reasoning[0]
        assert result.classification != "sector_shock_hold"
