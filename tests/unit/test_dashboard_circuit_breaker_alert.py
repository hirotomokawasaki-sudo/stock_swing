"""Tests for DashboardService._check_circuit_breaker_alert().

Regression: 2026-08-03 19:55 JST SNOW false HALT sat undetected in
data/guardrails/circuit_breaker.json for ~13 hours (until manually
discovered by an ad-hoc audit at 2026-08-04 08:xx JST). Nothing on the main
console (/api/dashboard alerts, which drives both console/ui/app.js and is
the closest thing to an "at a glance" operator view) surfaced the HALT.
Only the mobile read-only monitor (console/ui/mobile_readonly.html, a
separate app requiring a token) and ConsoleRenderer's text banner (only
visible if an operator manually runs paper_demo and reads stdout) showed
circuit_breaker status, and both require an operator to actively go look.

Fix: DashboardService.get_alerts() now includes a HALTED / RECOVERY_PENDING
alert sourced directly from data/guardrails/circuit_breaker.json, so it
shows up in the main dashboard's top-level alerts list regardless of
whether latest_console_summary.json is fresh.

See docs/daily_logs/2026-08-04.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from console.services.dashboard_service import DashboardService


# ── helpers ──────────────────────────────────────────────────────────────────

class _StubService(DashboardService):
    """Minimal DashboardService stub that avoids real broker/tracker I/O."""
    def __init__(self, project_root: Path) -> None:  # type: ignore[override]
        self.project_root = project_root
        self._broker = None
        self._tracker = None


def _write_cb(tmp_path: Path, payload: dict) -> Path:
    cb_path = tmp_path / "data" / "guardrails" / "circuit_breaker.json"
    cb_path.parent.mkdir(parents=True, exist_ok=True)
    cb_path.write_text(json.dumps(payload), encoding="utf-8")
    return cb_path


_SNOW_TRIGGERED_RULES = [
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


# ── normal cases ─────────────────────────────────────────────────────────────

class TestCircuitBreakerAlertHalted:
    def test_halted_returns_critical_alert(self, tmp_path):
        """AC: HALTED status produces a critical severity alert."""
        _write_cb(tmp_path, {
            "status": "halted",
            "triggered_at": "2026-08-03T19:55:27.054477+00:00",
            "triggered_rules": _SNOW_TRIGGERED_RULES,
        })
        svc = _StubService(tmp_path)
        alert = svc._check_circuit_breaker_alert()

        assert alert is not None
        assert alert["severity"] == "critical"
        assert alert["code"] == "guardrail_halted"

    def test_regression_snow_halt_08_04_message_includes_triggered_at_and_rule(self, tmp_path):
        """
        Regression: 2026-08-03 19:55 JST SNOW false HALT was invisible on the
        main console for ~13 hours. Message must include triggered_at and the
        triggered rule name so an operator scanning alerts immediately sees
        *when* and *why* without needing to open a separate file/monitor.
        """
        _write_cb(tmp_path, {
            "status": "halted",
            "triggered_at": "2026-08-03T19:55:27.054477+00:00",
            "triggered_rules": _SNOW_TRIGGERED_RULES,
        })
        svc = _StubService(tmp_path)
        alert = svc._check_circuit_breaker_alert()

        assert "2026-08-03T19:55:27" in alert["message"]
        assert "broker_tracker_mismatch" in alert["message"]

    def test_halted_action_hint_references_clear_script(self, tmp_path):
        """AC: action_hint tells the operator how to resolve (clear script)."""
        _write_cb(tmp_path, {
            "status": "halted",
            "triggered_at": "2026-08-03T19:55:27.054477+00:00",
            "triggered_rules": _SNOW_TRIGGERED_RULES,
        })
        svc = _StubService(tmp_path)
        alert = svc._check_circuit_breaker_alert()

        assert "clear_circuit_breaker.py" in alert["action_hint"]


class TestCircuitBreakerAlertRecoveryPending:
    def test_recovery_pending_returns_warning_alert(self, tmp_path):
        """AC: RECOVERY_PENDING status produces a warning (not critical) alert."""
        _write_cb(tmp_path, {
            "status": "recovery_pending",
            "triggered_at": "2026-08-03T19:55:27.054477+00:00",
            "triggered_rules": _SNOW_TRIGGERED_RULES,
            "cleared_at": "2026-08-04T00:00:00+00:00",
            "cleared_by": "HirotomoO",
        })
        svc = _StubService(tmp_path)
        alert = svc._check_circuit_breaker_alert()

        assert alert is not None
        assert alert["severity"] == "warning"
        assert alert["code"] == "guardrail_recovery_pending"


class TestCircuitBreakerAlertOk:
    def test_ok_status_returns_none(self, tmp_path):
        """AC: status=ok produces no alert (the common case)."""
        _write_cb(tmp_path, {"status": "ok"})
        svc = _StubService(tmp_path)
        assert svc._check_circuit_breaker_alert() is None

    def test_unknown_status_returns_none(self, tmp_path):
        """Any status other than halted/recovery_pending must not alert."""
        _write_cb(tmp_path, {"status": "degraded"})
        svc = _StubService(tmp_path)
        assert svc._check_circuit_breaker_alert() is None


# ── file missing / corrupt (testing_standards.md 1-A) ────────────────────────

class TestCircuitBreakerAlertFileHandling:
    def test_missing_file_returns_none_not_crash(self, tmp_path):
        """境界値: circuit_breaker.json が存在しない場合はクラッシュせず None。"""
        svc = _StubService(tmp_path)
        assert svc._check_circuit_breaker_alert() is None

    def test_corrupt_json_returns_none_not_crash(self, tmp_path):
        """破損入力: 不正な JSON はクラッシュせず None を返す。"""
        cb_path = tmp_path / "data" / "guardrails" / "circuit_breaker.json"
        cb_path.parent.mkdir(parents=True, exist_ok=True)
        cb_path.write_text("{not valid json", encoding="utf-8")
        svc = _StubService(tmp_path)
        assert svc._check_circuit_breaker_alert() is None

    def test_empty_triggered_rules_does_not_crash(self, tmp_path):
        """境界値: triggered_rules が空リストでもクラッシュしない。"""
        _write_cb(tmp_path, {
            "status": "halted",
            "triggered_at": "2026-08-03T19:55:27+00:00",
            "triggered_rules": [],
        })
        svc = _StubService(tmp_path)
        alert = svc._check_circuit_breaker_alert()
        assert alert is not None
        assert alert["severity"] == "critical"

    def test_missing_triggered_at_does_not_crash(self, tmp_path):
        """境界値: triggered_at が None/欠損でもクラッシュしない。"""
        _write_cb(tmp_path, {
            "status": "halted",
            "triggered_rules": _SNOW_TRIGGERED_RULES,
        })
        svc = _StubService(tmp_path)
        alert = svc._check_circuit_breaker_alert()
        assert alert is not None
        assert "unknown time" in alert["message"]


# ── layer propagation: DashboardService.get_alerts() includes the alert ─────

class TestCircuitBreakerAlertPropagatesToGetAlerts:
    """testing_standards.md 1-C: config/state file -> service -> get_alerts()
    output must be tested directly, not just indirectly via the renderer."""

    def _minimal_get_alerts_kwargs(self):
        return dict(
            overview={},
            trading={"summary": {}},
            positions={"summary": {}, "positions": []},
            cron_jobs={"jobs": []},
            data_status={"counts": {}, "freshness": {}, "integrity": {}},
            news={},
        )

    def test_halted_circuit_breaker_appears_in_get_alerts_output(self, tmp_path, monkeypatch):
        """AC: an active HALT must appear in the top-level alerts list
        returned by get_alerts(), which backs /api/dashboard."""
        _write_cb(tmp_path, {
            "status": "halted",
            "triggered_at": "2026-08-03T19:55:27.054477+00:00",
            "triggered_rules": _SNOW_TRIGGERED_RULES,
        })
        svc = _StubService(tmp_path)
        # Avoid unrelated I/O paths inside get_alerts() that need real broker/tracker.
        monkeypatch.setattr(svc, "check_broker_tracker_consistency", lambda: {"available": False})
        monkeypatch.setattr(svc, "get_pipeline_summary", lambda trading=None: {"symbol_overview": []})
        monkeypatch.setattr(svc, "get_news_ingestion_status", lambda news, tracked_symbols=None: {})
        monkeypatch.setattr(svc, "_get_tracked_symbols", lambda trading=None, cron_jobs=None: [])

        alerts = svc.get_alerts(**self._minimal_get_alerts_kwargs())

        codes = [a["code"] for a in alerts]
        assert "guardrail_halted" in codes, (
            f"guardrail_halted alert must be present in get_alerts() output, got codes={codes}"
        )

    def test_ok_circuit_breaker_absent_from_get_alerts_output(self, tmp_path, monkeypatch):
        """no-op ケース: status=ok の場合、guardrail_halted/recovery_pending
        アラートは get_alerts() の出力に一切現れない。"""
        _write_cb(tmp_path, {"status": "ok"})
        svc = _StubService(tmp_path)
        monkeypatch.setattr(svc, "check_broker_tracker_consistency", lambda: {"available": False})
        monkeypatch.setattr(svc, "get_pipeline_summary", lambda trading=None: {"symbol_overview": []})
        monkeypatch.setattr(svc, "get_news_ingestion_status", lambda news, tracked_symbols=None: {})
        monkeypatch.setattr(svc, "_get_tracked_symbols", lambda trading=None, cron_jobs=None: [])

        alerts = svc.get_alerts(**self._minimal_get_alerts_kwargs())

        codes = [a["code"] for a in alerts]
        assert "guardrail_halted" not in codes
        assert "guardrail_recovery_pending" not in codes
