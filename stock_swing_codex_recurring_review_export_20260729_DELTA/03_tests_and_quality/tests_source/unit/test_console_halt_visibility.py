"""Tests for circuit-breaker HALT visibility improvements in ConsoleRenderer.

Regression: 07-24 HALT (SKYY phantom) was discovered only the following morning
because the console did not surface triggered_at / triggered_rules prominently.
Related: docs/daily_logs/2026-07-25.md
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from stock_swing.reporting.console_renderer import ConsoleRenderer
from stock_swing.reporting.console_summary import ConsoleAlert, ConsoleSummary


# ── helpers ──────────────────────────────────────────────────────────────────

_TRIGGERED_AT_UTC = "2026-07-24T13:35:20.729734+00:00"
_TRIGGERED_RULES = [
    {
        "action": 5,
        "metric": "broker_tracker_mismatch_count",
        "name": "broker_tracker_mismatch",
        "observed": 1.0,
        "operator": ">=",
        "severity": "critical",
        "threshold": 1.0,
    }
]


def _halted_summary(cb_detail: dict | None = None) -> ConsoleSummary:
    return ConsoleSummary.build(
        run_id="r-halt",
        equity=1_000_000.0,
        open_position_count=7,
        guardrail_status="halted",
        circuit_breaker_detail=cb_detail or {
            "status": "halted",
            "triggered_at": _TRIGGERED_AT_UTC,
            "triggered_rules": _TRIGGERED_RULES,
            "reason": "guardrail_halt",
            "clear_note": None,
        },
    )


def _ok_summary() -> ConsoleSummary:
    return ConsoleSummary.build(
        run_id="r-ok",
        equity=1_000_000.0,
        open_position_count=7,
        guardrail_status="ok",
    )


def _recovery_summary() -> ConsoleSummary:
    return ConsoleSummary.build(
        run_id="r-recovery",
        equity=1_000_000.0,
        open_position_count=7,
        guardrail_status="recovery_pending",
        circuit_breaker_detail={
            "status": "recovery_pending",
            "triggered_at": _TRIGGERED_AT_UTC,
            "triggered_rules": _TRIGGERED_RULES,
            "reason": "guardrail_halt",
            "clear_note": "manually cleared",
        },
    )


_renderer = ConsoleRenderer()


# ── banner visibility ─────────────────────────────────────────────────────────

def test_halt_banner_rendered_at_top_when_halted() -> None:
    """AC: HALTED 時は最上部に全幅バナーを表示する。"""
    out = _renderer.render(_halted_summary())
    # The halt banner must come BEFORE the RUN HEALTH section
    banner_pos = out.find("═")
    run_health_pos = out.find("RUN HEALTH")
    assert banner_pos != -1, "HALT banner separator (═) must appear"
    assert run_health_pos != -1, "RUN HEALTH section must appear"
    assert banner_pos < run_health_pos, (
        "HALT banner must appear before RUN HEALTH section"
    )


def test_halt_banner_not_rendered_when_ok() -> None:
    """AC: 正常時はバナーを表示しない。"""
    out = _renderer.render(_ok_summary())
    assert "═" not in out, "No halt banner when circuit_breaker is ok"


def test_halt_banner_shows_halted_label() -> None:
    """AC: バナー内に HALTED と BUYS BLOCKED が含まれる。"""
    out = _renderer.render(_halted_summary())
    assert "HALTED" in out
    assert "BUYS BLOCKED" in out or "ALL BUYS" in out


def test_recovery_banner_rendered_when_recovery_pending() -> None:
    """AC: recovery_pending 時もバナーを表示する（別ラベル）。"""
    out = _renderer.render(_recovery_summary())
    assert "═" in out, "Banner separator must appear for recovery_pending"
    assert "RECOVERY_PENDING" in out


# ── triggered_at ──────────────────────────────────────────────────────────────

def test_halt_banner_shows_triggered_at_jst() -> None:
    """AC: バナー内に triggered_at を JST 形式で表示する。"""
    out = _renderer.render(_halted_summary())
    # 2026-07-24 13:35 UTC = 2026-07-24 22:35 JST
    assert "2026-07-24 22:35 JST" in out, (
        f"Expected '2026-07-24 22:35 JST' in banner, got:\n{out[:600]}"
    )


def test_safety_gate_shows_triggered_at_when_halted() -> None:
    """AC: SAFETY GATE セクションにも triggered_at を表示する。"""
    out = _renderer.render(_halted_summary())
    # SAFETY GATE section contains triggered_at
    sg_start = out.find("SAFETY GATE")
    assert sg_start != -1
    sg_section = out[sg_start:sg_start + 400]
    assert "triggered_at" in sg_section, (
        f"SAFETY GATE section must show triggered_at:\n{sg_section}"
    )


def test_halt_banner_with_missing_triggered_at_does_not_crash() -> None:
    """境界値: triggered_at が None でもクラッシュしない。"""
    out = _renderer.render(_halted_summary(cb_detail={
        "status": "halted",
        "triggered_at": None,
        "triggered_rules": [],
        "reason": "guardrail_halt",
    }))
    assert "HALTED" in out


# ── triggered_rules ───────────────────────────────────────────────────────────

def test_halt_banner_shows_triggered_rule_metric() -> None:
    """AC: バナー内に metric 名を表示する。"""
    out = _renderer.render(_halted_summary())
    assert "broker_tracker_mismatch" in out, (
        "Triggered rule metric name must appear in halt banner"
    )


def test_halt_banner_shows_observed_and_threshold() -> None:
    """AC: バナー内に observed / threshold を表示する。"""
    out = _renderer.render(_halted_summary())
    assert "observed=1.0" in out, "observed value must appear in halt banner"
    assert "threshold=1.0" in out, "threshold value must appear in halt banner"


def test_safety_gate_shows_trigger_rule_when_halted() -> None:
    """AC: SAFETY GATE セクションにも triggered rule を表示する。"""
    out = _renderer.render(_halted_summary())
    sg_start = out.find("SAFETY GATE")
    sg_section = out[sg_start:sg_start + 600]
    assert "broker_tracker_mismatch" in sg_section, (
        f"SAFETY GATE must show trigger rule:\n{sg_section}"
    )


def test_halt_banner_with_empty_rules_does_not_crash() -> None:
    """境界値: triggered_rules が空でもクラッシュしない。"""
    out = _renderer.render(_halted_summary(cb_detail={
        "status": "halted",
        "triggered_at": _TRIGGERED_AT_UTC,
        "triggered_rules": [],
        "reason": "guardrail_halt",
    }))
    assert "HALTED" in out
    assert "CIRCUIT BREAKER" in out


# ── layer propagation ─────────────────────────────────────────────────────────

def test_circuit_breaker_detail_in_to_dict() -> None:
    """レイヤー伝播: circuit_breaker_detail が to_dict()['health'] に含まれる。"""
    s = _halted_summary()
    d = s.to_dict()
    detail = d.get("health", {}).get("circuit_breaker_detail", {})
    assert detail.get("triggered_at") == _TRIGGERED_AT_UTC, (
        "circuit_breaker_detail.triggered_at must propagate to to_dict()"
    )
    assert detail.get("triggered_rules") == _TRIGGERED_RULES, (
        "circuit_breaker_detail.triggered_rules must propagate to to_dict()"
    )


def test_circuit_breaker_detail_defaults_to_empty_when_not_provided() -> None:
    """境界値: circuit_breaker_detail 未指定時は {} になる（既存テストへの後方互換）。"""
    s = ConsoleSummary.build(
        run_id="r-compat",
        equity=100_000.0,
        open_position_count=0,
        guardrail_status="halted",
        # circuit_breaker_detail を省略
    )
    d = s.to_dict()
    detail = d.get("health", {}).get("circuit_breaker_detail", {})
    assert isinstance(detail, dict), "circuit_breaker_detail must be a dict even when omitted"


def test_summary_field_circuit_breaker_detail_stored() -> None:
    """レイヤー伝播: ConsoleSummary.circuit_breaker_detail フィールドに格納される。"""
    detail = {
        "status": "halted",
        "triggered_at": _TRIGGERED_AT_UTC,
        "triggered_rules": _TRIGGERED_RULES,
        "reason": "guardrail_halt",
        "clear_note": None,
    }
    s = ConsoleSummary.build(
        run_id="r-field",
        equity=100_000.0,
        open_position_count=0,
        guardrail_status="halted",
        circuit_breaker_detail=detail,
    )
    assert s.circuit_breaker_detail == detail, (
        "circuit_breaker_detail must be stored on the summary object"
    )


# ── regression ───────────────────────────────────────────────────────────────

def test_regression_skyy_phantom_halt_pattern_07_24() -> None:
    """
    Regression: 2026-07-24 22:35 JST circuit-breaker HALT due to SKYY phantom.
    Root cause: SKYY sell on 07-22T19:55 was not recorded in tracker.
    Detection: paper_demo_market_open (09:35 ET) detected SKYY as tracker-only.
    mismatch_count=1 triggered halt rule (threshold=1.0).
    Fix: rebuild from broker + clear_circuit_breaker.py (2026-07-25).
    Docs: docs/daily_logs/2026-07-25.md

    This test verifies that the exact rule / metric / observed value from this
    incident is rendered visibly in the console output.
    """
    s = _halted_summary()
    out = _renderer.render(s)

    # Banner must be present
    assert "═" in out, "Halt banner missing"
    # Triggered timestamp (JST)
    assert "2026-07-24 22:35 JST" in out, "Triggered timestamp missing from output"
    # Rule details
    assert "broker_tracker_mismatch" in out, "Rule name missing"
    assert "observed=1.0" in out, "Observed value missing"
