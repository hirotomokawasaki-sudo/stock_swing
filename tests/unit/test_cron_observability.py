from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

massive_stub = types.ModuleType("massive")
massive_stub.RESTClient = object
sys.modules.setdefault("massive", massive_stub)

from console.adapters.cron_adapter import CronAdapter
from console.app import _apply_critical_evidence_gate
from console.services.console_self_check_service import run_self_check
from console.services.dashboard_service import DashboardService


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _minimal_project_root(tmp_path: Path) -> Path:
    runtime_path = tmp_path / "config" / "runtime" / "current_mode.yaml"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        "mode: paper\nledger_quality_gate:\n  current_status: VALID\n  last_checked: '2026-07-30'\n",
        encoding="utf-8",
    )
    sources_dir = tmp_path / "config" / "sources"
    sources_dir.mkdir(parents=True)
    (sources_dir / "finnhub.yaml").write_text("required: true\nenabled: true\n", encoding="utf-8")
    (tmp_path / ".env").write_text("FINNHUB_API_KEY=test-key\n", encoding="utf-8")
    (tmp_path / "venv").mkdir()
    _write_json(
        tmp_path / "data" / "audits" / "reconcile_status.json",
        {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "unexplained_mismatch_count": 0,
        },
    )
    _write_json(
        tmp_path / "data" / "guardrails" / "circuit_breaker.json",
        {"status": "ok", "cleared_at": datetime.now(timezone.utc).isoformat()},
    )
    _write_json(
        tmp_path / "data" / "guardrails" / "day_start_snapshot.json",
        {
            "market_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "source": "broker_api",
            "day_start_equity": 100_000.0,
            "day_start_unrealized": 250.0,
            "missing_fields": [],
        },
    )
    _write_json(
        tmp_path / "reports" / "console" / "latest_console_summary.json",
        {"run": {"status": "OK"}},
    )
    _write_json(
        tmp_path / "data" / "audits" / "news_collection_status.json",
        {
            "time": datetime.now(timezone.utc).isoformat(),
            "symbols": [
                {"symbol": "AAPL", "news_count": 2, "used_fallback": False, "reason": "ok"},
            ],
        },
    )
    (tmp_path / "data" / "tracking").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "tracking" / "pnl_state.json").write_text('{"trades":[]}', encoding="utf-8")
    return tmp_path


def test_cron_adapter_run_history_parse_error_returns_not_ok(monkeypatch, tmp_path: Path) -> None:
    adapter = CronAdapter(tmp_path)

    def _fake_run(args, capture_output, text, timeout):
        assert args[:4] == ["openclaw", "cron", "runs", "--id"]
        return SimpleNamespace(returncode=0, stdout='{"entries":[{"id":"r1"}', stderr="")

    monkeypatch.setattr("console.adapters.cron_adapter.subprocess.run", _fake_run)

    result = adapter.get_run_history("job-123")

    assert result["ok"] is False
    assert "balanced JSON" in result["error"]


def test_dashboard_system_status_blocks_when_cron_runs_unparseable(monkeypatch, tmp_path: Path) -> None:
    root = _minimal_project_root(tmp_path)

    # 2026-08-04: system_adapter now resolves an absolute path for the
    # openclaw binary (see _resolve_openclaw_bin) instead of the bare name
    # "openclaw", and passes an explicit env= kwarg (see _subprocess_env),
    # so subprocess.run is invoked as [<resolved-path>, ...] with env=...
    # rather than ["openclaw", ...] with no env kwarg. Match on the cron
    # subcommand only, and accept the env kwarg.
    def _fake_run(args, capture_output, text, check, timeout, env=None):
        if args[1:4] == ["cron", "list", "--json"]:
            return SimpleNamespace(
                returncode=0,
                stdout='{"jobs":[{"id":"job-1","name":"paper_demo","enabled":true}]}',
                stderr="",
            )
        if args[1:4] == ["cron", "runs", "--id"]:
            return SimpleNamespace(returncode=0, stdout='{"entries":[{"id":"r1"}', stderr="")
        raise AssertionError(args)

    monkeypatch.setattr("console.adapters.system_adapter.subprocess.run", _fake_run)

    service = DashboardService(root)
    status = service.get_system_status()

    assert status["status"] == "blocked"
    assert "cron_run_history" in status["critical_missing"]
    assert status["evidence"]["cron_run_history"]["parse_coverage"] == 0.0


def test_run_self_check_surfaces_health_evidence(monkeypatch, tmp_path: Path) -> None:
    root = _minimal_project_root(tmp_path)

    monkeypatch.setattr(
        "console.services.console_self_check_service.SystemAdapter.get_health",
        lambda self: {
            "status": "blocked",
            "score": 49,
            "evidence_status": "invalid",
            "critical_missing": ["cron_run_history"],
            "evidence": {"cron_run_history": {"ok": False}},
        },
    )

    result = run_self_check(root)

    assert result["ok"] is True
    assert result["health_status"] == "blocked"
    assert result["health_score"] == 49
    assert result["health_evidence_status"] == "invalid"
    assert result["critical_missing"] == ["cron_run_history"]


def test_apply_critical_evidence_gate_clamps_healthy_payload() -> None:
    gated = _apply_critical_evidence_gate(
        {"health_status": "healthy", "health_score": 100, "status": "healthy", "score": 100, "ok": True},
        {
            "health_status": "blocked",
            "health_score": 88,
            "health_evidence_status": "invalid",
            "critical_missing": ["cron_run_history"],
        },
    )

    assert gated["health_status"] == "blocked"
    assert gated["health_score"] == 49
    assert gated["status"] == "blocked"
    assert gated["score"] == 49
    assert gated["ok"] is False
