"""Tests for scripts/check_go_no_go.py.

2026-08-05 fix: the mismatch check previously read the RAW
health.broker_tracker_mismatch_count, which does not account for
G1-v2/v2-b/v2-c/v2-d lag exclusion (see
src/stock_swing/guardrails/postrun_mismatch.py). This caused a false
NO-GO whenever a normal, already-excused timing lag (e.g. add-to-existing
qty lag) produced a nonzero raw count while the live circuit breaker
correctly reported real_mismatch_count=0 and stayed "ok".

Fix: prefer broker_tracker_diff.real_mismatch_count (the same field the
live circuit breaker guardrail acts on) when available.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_go_no_go.py"


def _load_module(monkeypatch, project_root: Path):
    """Import check_go_no_go.py with PROJECT_ROOT patched to a temp dir."""
    spec = importlib.util.spec_from_file_location("check_go_no_go", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", project_root)
    return module


def _write_summary(project_root: Path, health: dict, broker_tracker_diff: dict | None = None):
    import json

    console_dir = project_root / "reports" / "console"
    console_dir.mkdir(parents=True, exist_ok=True)
    summary = {"health": health}
    if broker_tracker_diff is not None:
        summary["broker_tracker_diff"] = broker_tracker_diff
    (console_dir / "latest_console_summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )


def _base_health(**overrides) -> dict:
    base = {
        "ledger_gate_status": "VALID",
        "circuit_breaker_detail": {"status": "ok"},
        "attribution_coverage_pct": 98.5,
        "guardrail_status": "ok",
        "status": "OK",
        "broker_tracker_mismatch_count": 0,
    }
    base.update(overrides)
    return base


def test_mismatch_check_uses_real_mismatch_count_when_available(monkeypatch, tmp_path):
    """Regression: raw mismatch_count=2 (lag-excused) must PASS when
    broker_tracker_diff.real_mismatch_count=0 is present (2026-08-05 fix).
    """
    module = _load_module(monkeypatch, tmp_path)
    _write_summary(
        tmp_path,
        health=_base_health(broker_tracker_mismatch_count=2),
        broker_tracker_diff={"real_mismatch_count": 0, "mismatch_count": 2},
    )
    results = module.check()
    assert results["mismatch"]["pass"] is True
    assert results["mismatch"]["actual"] == 0
    assert "real, lag-excused" in results["mismatch"]["label"]


def test_mismatch_check_fails_on_true_real_mismatch(monkeypatch, tmp_path):
    """A genuine (non-excused) mismatch must still fail the check."""
    module = _load_module(monkeypatch, tmp_path)
    _write_summary(
        tmp_path,
        health=_base_health(broker_tracker_mismatch_count=3),
        broker_tracker_diff={"real_mismatch_count": 3, "mismatch_count": 3},
    )
    results = module.check()
    assert results["mismatch"]["pass"] is False
    assert results["mismatch"]["actual"] == 3


def test_mismatch_check_falls_back_to_raw_when_real_mismatch_count_absent(monkeypatch, tmp_path):
    """Older console_summary snapshots without real_mismatch_count still work
    (fallback to the raw field, matching pre-fix behavior)."""
    module = _load_module(monkeypatch, tmp_path)
    _write_summary(
        tmp_path,
        health=_base_health(broker_tracker_mismatch_count=0),
        broker_tracker_diff={},
    )
    results = module.check()
    assert results["mismatch"]["pass"] is True
    assert "raw" in results["mismatch"]["label"]


def test_mismatch_check_missing_broker_tracker_diff_key_entirely(monkeypatch, tmp_path):
    """summary with no broker_tracker_diff key at all -> falls back to raw."""
    module = _load_module(monkeypatch, tmp_path)
    _write_summary(tmp_path, health=_base_health(broker_tracker_mismatch_count=0))
    results = module.check()
    assert results["mismatch"]["pass"] is True
    assert "raw" in results["mismatch"]["label"]


def test_all_pass_when_real_mismatch_zero_despite_raw_nonzero(monkeypatch, tmp_path):
    """End-to-end: with all other Required conditions green and only the
    (excused) raw mismatch nonzero, overall verdict should be GO.
    """
    module = _load_module(monkeypatch, tmp_path)
    _write_summary(
        tmp_path,
        health=_base_health(broker_tracker_mismatch_count=2),
        broker_tracker_diff={"real_mismatch_count": 0},
    )
    # paper_3day_confirmation reads a separate file; write it so this test
    # can assert a full GO independent of that file's presence elsewhere.
    gng_path = tmp_path / "docs" / "go_no_go_report_20260731.md"
    gng_path.parent.mkdir(parents=True, exist_ok=True)
    gng_path.write_text("07-28 ok / 07-29 ok / 07-30 ok", encoding="utf-8")

    reconcile_dir = tmp_path / "data" / "audits"
    reconcile_dir.mkdir(parents=True, exist_ok=True)
    (reconcile_dir / "reconcile_status.json").write_text("{}", encoding="utf-8")

    results = module.check()
    assert all(r["pass"] for r in results.values()), results
