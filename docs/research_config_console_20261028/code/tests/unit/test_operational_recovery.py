"""Regression: 2026-10-19 missed runs must not be laundered by a diagnostic."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[2] / "scripts/check_operational_recovery.py"
_spec = importlib.util.spec_from_file_location("operational_recovery", _path)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
NOW = datetime(2026, 10, 20, 14, 45, tzinfo=timezone.utc)
STAMP = "2026-10-20T13:36:00+00:00"


def write(root, rel, value):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value))
    return p


def seed(root):
    write(root, "reports/console/latest_console_summary.json", {"run": {
        "timestamp": STAMP, "dry_run": False, "invocation_source": "paper_demo_scheduled"}})
    write(root, "data/guardrails/circuit_breaker.json", {"status": "halted", "last_evaluated_at": STAMP})
    rows = history(["2026-10-20"])
    rows[0]["last_observed_at"] = STAMP
    write(root, "data/guardrails/economic_risk_off.json", {"history": rows, "last_evaluated_at": STAMP})
    write(root, "data/tracking/pnl_state.json", {"trades": [
        {"status": "closed", "exit_time": "2026-10-16", "pnl": -10} for _ in range(30)]})


def test_genuine_fresh_evidence_recovers_operations_but_not_promotion(tmp_path):
    seed(tmp_path)
    report = module.assess(tmp_path, now=NOW)
    assert report["operational_recovered"]
    assert report["circuit_breaker"]["status"] == "halted"
    assert not report["economic_viability"]["pass"]
    assert not report["promotion_authorized_by_this_check"]


@pytest.mark.parametrize("dry_run,source", [(True, "paper_demo_dry_run"), (False, "manual_diagnostic"), (None, None)])
def test_diagnostic_or_unknown_provenance_never_counts(tmp_path, dry_run, source):
    seed(tmp_path)
    write(tmp_path, "reports/console/latest_console_summary.json", {"run": {
        "timestamp": STAMP, "dry_run": dry_run, "invocation_source": source}})
    assert not module.assess(tmp_path, now=NOW)["operational_recovered"]


def test_missing_and_corrupt_files_fail_closed_without_writes(tmp_path):
    report = module.assess(tmp_path, now=NOW)
    assert not report["operational_recovered"]
    assert report["economic_risk_off"]["observed_sessions"] == 0
    assert not list(tmp_path.iterdir())
    p = write(tmp_path, "reports/console/latest_console_summary.json", {})
    p.write_text("not json")
    assert module.assess(tmp_path, now=NOW)["console"]["error"] == "JSONDecodeError"


def test_stale_friday_not_excused_after_monday_missed(tmp_path):
    seed(tmp_path)
    write(tmp_path, "reports/console/latest_console_summary.json", {"run": {
        "timestamp": "2026-10-16T19:55:00Z", "dry_run": False, "invocation_source": "paper_demo_scheduled"}})
    assert not module.assess(tmp_path, now=NOW)["console"]["fresh"]


def test_weekend_and_dst_slot_calculation():
    sunday = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    assert module.expected_run_at(sunday).isoformat() == "2026-10-16T19:55:00+00:00"
    november = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
    assert module.expected_run_at(november).isoformat() == "2026-11-03T14:35:00+00:00"


def history(dates):
    return [{"market_date": day, "start_equity": 100, "latest_equity": 99,
             "start_external_cash_flow": 0, "latest_external_cash_flow": 0,
             "first_observed_at": day + "T13:25:00Z", "last_observed_at": day + "T19:55:00Z"}
            for day in dates]


def test_ready_count_uses_valid_consecutive_observed_windows_not_calendar_elapsed():
    dates = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19"]
    assert module._ready_candidates(history(dates), 5) == 2
    assert module._ready_candidates(history(dates[:3]), 5) == 0
    assert module._ready_candidates(history(dates[:4] + [dates[-1]]), 5) == 0
    assert module._ready_candidates(history(dates + [dates[-1]]), 5) == 0


def test_replay_dates_with_mismatched_actual_timestamps_do_not_count():
    rows = history(["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"])
    rows[-1]["first_observed_at"] = "2026-10-20T13:25:00Z"
    assert module._ready_candidates(rows, 5) == 0


@pytest.mark.parametrize("field,value", [("latest_equity", "NaN"), ("latest_equity", 0),
                                         ("last_observed_at", "2026-10-20T19:55:00Z")])
def test_fresh_state_timestamp_cannot_hide_invalid_or_future_observation(tmp_path, field, value):
    seed(tmp_path)
    path = tmp_path / "data/guardrails/economic_risk_off.json"
    risk = json.loads(path.read_text())
    risk["history"][0][field] = value
    path.write_text(json.dumps(risk))
    report = module.assess(tmp_path, now=NOW)
    assert not report["economic_risk_off"]["observing"]
    assert not report["operational_recovered"]


def test_report_save_does_not_overwrite_canonical_evidence(tmp_path):
    seed(tmp_path)
    canonical = tmp_path / "reports/console/latest_console_summary.json"
    before = canonical.read_bytes()
    path = tmp_path / "reports/operations/operational_recovery_status.json"
    module.save_report(module.assess(tmp_path, now=NOW), path)
    assert json.loads(path.read_text())["circuit_breaker"]["status"] == "halted"
    assert canonical.read_bytes() == before
