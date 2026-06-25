"""Tests for console_summary (C0/C1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_swing.reporting.console_summary import ConsoleAlert, ConsoleSummary


def _make_empty() -> ConsoleSummary:
    return ConsoleSummary.build(run_id="r1", equity=0.0, open_position_count=0)


def test_empty_summary_builds_without_crash() -> None:
    s = _make_empty()
    assert s.run_id == "r1"
    assert s.run_status in ("OK", "DEGRADED", "HALTED")


def test_stale_symbols_create_warning_alert() -> None:
    s = ConsoleSummary.build(
        run_id="r2",
        equity=1000.0,
        open_position_count=0,
        stale_symbols=["KLAC", "MRVL"],
    )
    assert any(a.code == "stale_price_detected" for a in s.alerts)
    assert s.run_status == "DEGRADED"


def test_guardrail_halted_creates_critical_and_halted_status() -> None:
    s = ConsoleSummary.build(
        run_id="r3",
        equity=1000.0,
        open_position_count=0,
        guardrail_status="halted",
    )
    assert any(a.severity == "critical" for a in s.alerts)
    assert s.run_status == "HALTED"


def test_alerts_sorted_critical_before_warning() -> None:
    s = ConsoleSummary.build(
        run_id="r4",
        equity=1000.0,
        open_position_count=0,
        stale_symbols=["X"],
        guardrail_status="halted",
    )
    sevs = [a.severity for a in s.alerts]
    # critical should come before warning
    if "critical" in sevs and "warning" in sevs:
        assert sevs.index("critical") < sevs.index("warning")


def test_to_dict_contains_run_health_portfolio() -> None:
    s = ConsoleSummary.build(run_id="r5", equity=100_000.0, open_position_count=5)
    d = s.to_dict()
    assert "run" in d
    assert "health" in d
    assert "portfolio" in d
    assert d["portfolio"]["equity"] == pytest.approx(100_000.0)


def test_save_json_writes_file(tmp_path: Path) -> None:
    s = ConsoleSummary.build(run_id="r6", equity=50_000.0, open_position_count=2)
    p = tmp_path / "console" / "latest.json"
    s.save_json(p)
    loaded = json.loads(p.read_text())
    assert loaded["portfolio"]["equity"] == pytest.approx(50_000.0)


def test_experiment_id_propagated() -> None:
    s = ConsoleSummary.build(
        run_id="r7",
        equity=1000.0,
        open_position_count=0,
        experiment_id="exp-test-123",
    )
    assert s.experiment_id == "exp-test-123"
    assert s.to_dict()["run"]["experiment_id"] == "exp-test-123"


def test_missing_metrics_tracked() -> None:
    s = ConsoleSummary.build(run_id="r8", equity=0.0, open_position_count=0)
    assert "equity" in s.missing_metrics


def test_price_integrity_section_populated() -> None:
    s = ConsoleSummary.build(
        run_id="r9",
        equity=1000.0,
        open_position_count=0,
        price_integrity={
            "fresh_price_count": 40,
            "stale_price_count": 2,
            "fallback_price_count": 1,
            "top_stale_symbols": ["KLAC"],
            "price_source_breakdown": {"massive": 40, "broker_bar": 1},
        },
    )
    d = s.to_dict()
    assert d["price_integrity"]["stale_price_count"] == 2


def test_api_metrics_propagated() -> None:
    s = ConsoleSummary.build(
        run_id="r10",
        equity=1000.0,
        open_position_count=0,
        api_metrics={"call_count": 100, "error_count": 2, "p50_latency_ms": 210.0},
    )
    d = s.to_dict()
    assert d["api"]["error_count"] == 2
    # Warning should be generated for api errors
    assert any(a.code == "api_errors" for a in s.alerts)
