"""Tests for ConsoleRenderer (C1)."""
from __future__ import annotations

from stock_swing.reporting.console_renderer import ConsoleRenderer
from stock_swing.reporting.console_summary import ConsoleAlert, ConsoleSummary


def _renderer() -> ConsoleRenderer:
    return ConsoleRenderer()


def test_empty_summary_renders_without_crash() -> None:
    s = ConsoleSummary.build(run_id="r1", equity=0.0, open_position_count=0)
    out = _renderer().render(s)
    assert "RUN HEALTH" in out


def test_ok_status_shows_checkmark() -> None:
    s = ConsoleSummary.build(run_id="r1", equity=100_000.0, open_position_count=0)
    out = _renderer().render(s)
    assert "✅" in out or "OK" in out


def test_halted_status_shows_alarm() -> None:
    s = ConsoleSummary.build(
        run_id="r2",
        equity=100_000.0,
        open_position_count=0,
        guardrail_status="halted",
    )
    out = _renderer().render(s)
    assert "HALTED" in out or "🚨" in out


def test_alerts_section_appears() -> None:
    s = ConsoleSummary.build(
        run_id="r3",
        equity=100_000.0,
        open_position_count=0,
        stale_symbols=["KLAC"],
    )
    out = _renderer().render(s)
    assert "ALERTS" in out
    assert "stale_price_detected" in out


def test_price_integrity_shown_when_present() -> None:
    s = ConsoleSummary.build(
        run_id="r4",
        equity=100_000.0,
        open_position_count=0,
        price_integrity={
            "fresh_price_count": 40,
            "stale_price_count": 0,
            "fallback_price_count": 0,
            "top_stale_symbols": [],
            "price_source_breakdown": {"massive": 40},
        },
    )
    out = _renderer().render(s)
    assert "PRICE INTEGRITY" in out


def test_api_ai_section_shown() -> None:
    s = ConsoleSummary.build(
        run_id="r5",
        equity=100_000.0,
        open_position_count=0,
        api_metrics={"call_count": 50, "error_count": 0, "p50_latency_ms": 200.0, "p95_latency_ms": 800.0},
        ai_metrics={"calls": 10, "skipped": 5, "input_tokens": 20000, "output_tokens": 3000, "daily_token_budget": 300000},
    )
    out = _renderer().render(s)
    assert "API / AI COST" in out


def test_portfolio_shows_equity() -> None:
    s = ConsoleSummary.build(run_id="r6", equity=123_456.78, open_position_count=3)
    out = _renderer().render(s)
    assert "123,456.78" in out


def test_decision_funnel_shown() -> None:
    from unittest.mock import MagicMock

    d1 = MagicMock()
    d1.action = "buy"
    d2 = MagicMock()
    d2.action = "deny"
    s1 = MagicMock()
    s1.status = "submitted"
    s = ConsoleSummary.build(
        run_id="r7",
        equity=100_000.0,
        open_position_count=0,
        decisions=[d1, d2],
        submissions=[s1],
    )
    out = _renderer().render(s)
    assert "DECISION FUNNEL" in out


def test_missing_metrics_shown() -> None:
    s = ConsoleSummary.build(run_id="r8", equity=0.0, open_position_count=0)
    out = _renderer().render(s)
    assert "MISSING METRICS" in out or "equity" in out
