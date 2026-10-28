"""Tests for SystemAdapter._check_guardrail_freshness's circuit_breaker
staleness clock.

Regression (2026-08-07): the console self-check reported
critical_missing=['guardrail_metric_freshness'] (and health_status=blocked)
purely because circuit_breaker.json's timestamp was cleared_at/triggered_at,
which only updates on a *state transition*. A circuit breaker that has
correctly stayed 'ok' for days (no halts, nothing to clear) looked
identical to a dead/stale guardrail loop. The fix stamps a
last_evaluated_at heartbeat on every guardrail evaluation
(CircuitBreakerStore.apply_decision), and this check now prefers that field
for the staleness clock, falling back to cleared_at/triggered_at for older
files written before the field existed.

See docs/daily_logs/2026-08-07.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from console.adapters.system_adapter import SystemAdapter


def _write_day_start(tmp_path: Path, market_date: str, captured_at: str) -> None:
    guardrails_dir = tmp_path / "data" / "guardrails"
    guardrails_dir.mkdir(parents=True, exist_ok=True)
    (guardrails_dir / "day_start_snapshot.json").write_text(
        json.dumps(
            {
                "market_date": market_date,
                "captured_at": captured_at,
                "source": "broker_api",
                "day_start_equity": 100000.0,
                "day_start_unrealized": 0.0,
                "missing_fields": [],
            }
        ),
        encoding="utf-8",
    )


def _write_circuit_breaker(tmp_path: Path, payload: dict) -> None:
    guardrails_dir = tmp_path / "data" / "guardrails"
    guardrails_dir.mkdir(parents=True, exist_ok=True)
    (guardrails_dir / "circuit_breaker.json").write_text(json.dumps(payload), encoding="utf-8")


def _fresh_day_start(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    _write_day_start(tmp_path, now.strftime("%Y-%m-%d"), now.isoformat())


def test_fresh_last_evaluated_at_not_stale_despite_old_cleared_at(tmp_path):
    """A circuit breaker that has been 'ok' for days (old cleared_at) but is
    actively evaluated every run (fresh last_evaluated_at) must not be
    reported stale."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=5)
    _write_circuit_breaker(
        tmp_path,
        {
            "status": "ok",
            "action": "allow",
            "cleared_at": old.isoformat(),
            "reason": "metrics_normalized",
            "last_evaluated_at": now.isoformat(),
        },
    )
    _fresh_day_start(tmp_path)

    adapter = SystemAdapter(tmp_path)
    result = adapter._check_guardrail_freshness()

    assert "stale_circuit_breaker" not in result["problems"]
    assert result["ok"] is True, result


def test_stale_last_evaluated_at_reported_stale(tmp_path):
    """If last_evaluated_at itself is old (heartbeat loop actually dead),
    it must still be reported stale."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=24)
    _write_circuit_breaker(
        tmp_path,
        {
            "status": "ok",
            "action": "allow",
            "cleared_at": old.isoformat(),
            "reason": "metrics_normalized",
            "last_evaluated_at": old.isoformat(),
        },
    )
    _fresh_day_start(tmp_path)

    adapter = SystemAdapter(tmp_path)
    result = adapter._check_guardrail_freshness()

    assert "stale_circuit_breaker" in result["problems"]
    assert result["ok"] is False


def test_missing_last_evaluated_at_falls_back_to_cleared_at(tmp_path):
    """Legacy circuit_breaker.json files (written before last_evaluated_at
    existed) must fall back to cleared_at, not crash or always report
    stale/missing."""
    now = datetime.now(timezone.utc)
    _write_circuit_breaker(
        tmp_path,
        {
            "status": "ok",
            "action": "allow",
            "cleared_at": now.isoformat(),
            "reason": "metrics_normalized",
        },
    )
    _fresh_day_start(tmp_path)

    adapter = SystemAdapter(tmp_path)
    result = adapter._check_guardrail_freshness()

    assert result["cb_as_of"] == now.isoformat()
    assert "stale_circuit_breaker" not in result["problems"]


def test_missing_last_evaluated_at_and_cleared_at_falls_back_to_triggered_at(tmp_path):
    now = datetime.now(timezone.utc)
    _write_circuit_breaker(
        tmp_path,
        {
            "status": "halted",
            "action": "halt",
            "triggered_at": now.isoformat(),
            "reason": "guardrail_halt",
        },
    )
    _fresh_day_start(tmp_path)

    adapter = SystemAdapter(tmp_path)
    result = adapter._check_guardrail_freshness()

    assert result["cb_as_of"] == now.isoformat()
