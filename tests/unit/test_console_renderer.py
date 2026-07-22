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


# ── R0-v2-A: Safety Gate ───────────────────────────────────────────────── #

def test_safety_gate_section_always_present() -> None:
    s = ConsoleSummary.build(run_id="sg1", equity=100_000.0, open_position_count=0)
    out = _renderer().render(s)
    assert "SAFETY GATE" in out


def test_invalid_ledger_shows_no_go() -> None:
    s = ConsoleSummary.build(
        run_id="sg2",
        equity=100_000.0,
        open_position_count=0,
        ledger_gate_status="INVALID",
    )
    out = _renderer().render(s)
    assert "NO-GO" in out
    assert "INVALID" in out
    assert "live_ready" in out


def test_valid_ledger_shows_no_go_gate_cleared() -> None:
    s = ConsoleSummary.build(
        run_id="sg3",
        equity=100_000.0,
        open_position_count=0,
        ledger_gate_status="VALID",
    )
    out = _renderer().render(s)
    assert "NO-GO" not in out
    assert "VALID" in out


def test_recovery_pending_shows_in_safety_gate() -> None:
    s = ConsoleSummary.build(
        run_id="sg4",
        equity=100_000.0,
        open_position_count=0,
        guardrail_status="recovery_pending",
        ledger_gate_status="INVALID",
    )
    out = _renderer().render(s)
    assert "RECOVERY_PENDING" in out


def test_invalid_ledger_pf_shown_as_not_valid_in_portfolio() -> None:
    """PF/WR in ETF vs STOCK breakdown should be suppressed when ledger=INVALID."""
    s = ConsoleSummary.build(
        run_id="sg5",
        equity=100_000.0,
        open_position_count=0,
        ledger_gate_status="INVALID",
        asset_class_breakdown={
            "etf": {"count": 10, "profit_factor": 2.5, "win_rate": 0.7, "net_pnl": 5000},
            "stock": {"count": 20, "profit_factor": 0.8, "win_rate": 0.4, "net_pnl": -3000},
        },
    )
    out = _renderer().render(s)
    assert "NOT_VALID" in out
    # Raw PF numbers should not appear in portfolio section
    assert "PF=2.500" not in out
    assert "PF=0.800" not in out


def test_invalid_ledger_exit_attribution_suppresses_pf() -> None:
    """PF/WR in EXIT ATTRIBUTION should be suppressed when ledger=INVALID."""
    s = ConsoleSummary.build(
        run_id="sg6",
        equity=100_000.0,
        open_position_count=0,
        ledger_gate_status="INVALID",
        exit_attribution_breakdown={
            "by_reason": {
                "trailing_stop": {"count": 68, "profit_factor": 25.87, "win_rate": 0.85, "net_pnl": 124669},
                "stop_loss": {"count": 88, "profit_factor": 0.069, "win_rate": 0.25, "net_pnl": -150837},
            },
            "unknown_count": 0,
        },
    )
    out = _renderer().render(s)
    assert "NOT_VALID" in out
    assert "PF=25.870" not in out
    assert "PF=0.069" not in out
