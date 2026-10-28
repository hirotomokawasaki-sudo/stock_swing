"""Regression: 2026-10-19 DNS outage blocked deterministic agentTurn jobs."""
from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[2] / "scripts/cron/run_gateway_command.py"
_spec = importlib.util.spec_from_file_location("gateway_workflow_runner", _path)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def run(tmp_path, source, **kwargs):
    return runner.run_logged([sys.executable, "-c", source], root=tmp_path,
                             name="canary", **kwargs)


def test_success_keeps_full_owner_only_log_and_summary(tmp_path):
    source = 'print("detail"); print(\'CRON_SUMMARY_JSON={"status":"ok","submitted":0}\')'
    code, report = run(tmp_path, source, require_summary=True)
    assert code == 0
    assert report["workflow"]["submitted"] == 0
    log = Path(report["log_file"])
    assert "detail" in log.read_text()
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


@pytest.mark.parametrize("line", ["", "CRON_SUMMARY_JSON=not-json",
                                'CRON_SUMMARY_JSON=[]',
                                'CRON_SUMMARY_JSON={"status":"error"}',
                                'CRON_SUMMARY_JSON={"other":"ok"}'])
def test_missing_corrupt_or_error_summary_is_not_success(tmp_path, line):
    code, report = run(tmp_path, f"print({line!r})", require_summary=True)
    assert code != 0 and report["status"] == "error"


def test_process_failure_overrides_success_summary_and_does_not_retry(tmp_path):
    marker = tmp_path / "calls"
    source = (f"from pathlib import Path; p=Path({str(marker)!r}); "
              "p.write_text(p.read_text()+'x' if p.exists() else 'x'); "
              'print(\'CRON_SUMMARY_JSON={"status":"ok"}\'); raise SystemExit(7)')
    code, report = run(tmp_path, source, require_summary=True)
    assert code == 7 and report["status"] == "error"
    assert marker.read_text() == "x"


def test_missing_executable_returns_failure(tmp_path):
    code, report = runner.run_logged([str(tmp_path / "missing")], root=tmp_path,
                                    name="missing")
    assert code == 127 and report["status"] == "error"


def test_ancillary_command_needs_successful_exit_not_json(tmp_path):
    code, report = run(tmp_path, 'print("audit complete")')
    assert code == 0 and "audit complete" in report["output_tail"]


def test_shell_metacharacters_in_argv_are_literal(tmp_path):
    marker = tmp_path / "must_not_exist"
    payload = f"$(touch {marker})"
    code, report = runner.run_logged([sys.executable, "-c", "import sys; print(sys.argv[1])", payload],
                                    root=tmp_path, name="literal")
    assert code == 0 and payload in report["output_tail"]
    assert not marker.exists()
