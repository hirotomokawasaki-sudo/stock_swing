"""Observation diagnostics never gate or retry the trading command."""
import fcntl
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from stock_swing.reporting import restriction_review_alerts as health
from stock_swing.reporting.console_summary import ConsoleSummary
from stock_swing.reporting.console_renderer import ConsoleRenderer

spec = importlib.util.spec_from_file_location(
    "health_workflow_runner", Path(__file__).parents[2] / "scripts/cron/run_gateway_command.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

ENV = {"ENTRY_RESTRICTION_REVIEW_VERSION": "v7",
       "ENTRY_RESTRICTION_REVIEW_LEDGER_REVISION": "fixture-revision"}
ERROR = {"status": "error", "reason": "ValueError", "eligible_to_trade": False,
         "automatic_release": False, "candidates": [], "rows": []}


def ledger(root):
    folder = root / "data/tracking"
    folder.mkdir(parents=True)
    (folder / "pnl_state.json").write_text(json.dumps({"trades": [], "measurement_lineage": {
        "ledger_revision": "fixture-revision", "measurement_status": "unqualified"}}))
    (folder / "trade_events.jsonl").write_text("")
    return folder


def test_error_is_visible_but_does_not_change_trading_status_or_expose_reason():
    bad = {**ERROR, "reason": "secret credential / private/path"}
    summary = ConsoleSummary.build(run_id="fixture", equity=100, open_position_count=0,
        entry_filter_stats={"entry_restriction_review": bad})
    assert summary.run_status == "OK"
    alert = summary.to_dict()["alerts"][0]
    assert alert["code"] == "entry_restriction_observation_failed"
    assert alert["severity"] == "info" and alert["details"]["observation_status"] == "error"
    assert "PF観測失敗" in ConsoleRenderer().render(summary)
    assert "secret credential" not in json.dumps(alert)
    assert bad["reason"] == "secret credential / private/path"


def test_dry_run_error_is_not_an_operational_alert():
    summary = ConsoleSummary.build(run_id="fixture", equity=100, open_position_count=0,
        dry_run=True, entry_filter_stats={"entry_restriction_review": ERROR})
    assert not summary.alerts


@pytest.mark.parametrize("patch,reason", [
    ({"ENTRY_RESTRICTION_REVIEW_VERSION": ""}, "missing_version"),
    ({"ENTRY_RESTRICTION_REVIEW_VERSION": "v8"}, "unsupported_version"),
    ({"ENTRY_RESTRICTION_REVIEW_LEDGER_REVISION": ""}, "missing_ledger_revision"),
    ({"ENTRY_RESTRICTION_REVIEW_LEDGER_REVISION": "legacy"}, "missing_ledger_revision"),
    ({"ENTRY_RESTRICTION_REVIEW_LEDGER_REVISION": "wrong"}, "ledger_revision_mismatch"),
])
def test_required_configuration_is_validated(tmp_path, patch, reason):
    ledger(tmp_path)
    result = health.preflight_restriction_review(tmp_path, {**ENV, **patch})
    assert result["status"] == "error" and result["reason"] == reason
    assert result["eligible_to_trade"] is False and result["as_of"]


def test_preflight_reads_normal_pair_without_recovery_or_financial_changes(tmp_path):
    folder = ledger(tmp_path)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    result = health.preflight_restriction_review(tmp_path, ENV)
    assert result["status"] == "ok" and result["scope"] == "configuration_only_not_observation_success"
    assert all((folder / name).read_bytes() == raw for name, raw in before.items())
    assert not (tmp_path / "data/analysis").exists()


@pytest.mark.parametrize("damage", ["missing", "corrupt", "journal", "busy"])
def test_unavailable_ledger_is_not_repaired_or_waited_for(tmp_path, damage):
    folder = ledger(tmp_path)
    if damage == "missing": (folder / "pnl_state.json").unlink()
    if damage == "corrupt": (folder / "pnl_state.json").write_text("{")
    if damage == "journal": (folder / ".ledger_transaction.json").write_text("prepared evidence")
    with (folder / ".ledger.lock").open("a+b") as lock:
        if damage == "busy": fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        result = health.preflight_restriction_review(tmp_path, ENV)
        assert result["status"] == "error" and result["reason"] == "ledger_unavailable"
        assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


def test_disabled_and_legacy_preflight_do_not_create_a_ledger(tmp_path):
    for env in [{**ENV, "ENTRY_RESTRICTION_REVIEW_ENABLED": "false"},
                {"ENTRY_RESTRICTION_REVIEW_VERSION": "v1"}]:
        assert health.preflight_restriction_review(tmp_path, env)["status"] in {"disabled", "ok"}
    assert not (tmp_path / "data").exists()


def test_literal_exports_override_inherited_configuration_without_shell_evaluation(tmp_path):
    marker = tmp_path / "do_not_create"
    script = "\n".join(f"export {k}={v}" for k, v in ENV.items())
    config = runner.observation_environment(["/bin/bash", "-c", script], {})
    assert config == ENV
    for value in [f"$(touch {marker})", "v7; true", "v7\nexport ENTRY_RESTRICTION_REVIEW_VERSION=v1"]:
        with pytest.raises(ValueError):
            runner.observation_environment(["/bin/bash", "-c", "export ENTRY_RESTRICTION_REVIEW_VERSION=" + value], {})
    assert not marker.exists()


@pytest.mark.parametrize("observer,expected", [(ERROR, "error"),
    ({**ERROR, "status": "observing"}, "observing"),
    ({**ERROR, "status": "disabled"}, "disabled"), (None, "unknown")])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_same_child_observation_is_separate_and_trading_runs_once(tmp_path, monkeypatch, observer, expected, exit_code):
    monkeypatch.setenv("ENTRY_RESTRICTION_REVIEW_VERSION", "v7")
    monkeypatch.delenv("ENTRY_RESTRICTION_REVIEW_LEDGER_REVISION", raising=False)
    summary = {"run": {"run_id": "this-run", "timestamp": "2026-11-10T00:00:00+00:00", "dry_run": False},
               "decision_funnel": {"entry_restriction_review": observer}}
    source = ("from pathlib import Path; p=Path('sell_calls'); p.write_text(p.read_text()+'SELL:3\\n' if p.exists() else 'SELL:3\\n'); "
              f"print('CONSOLE_SUMMARY_JSON ' + {json.dumps(summary)!r}); "
              'print(\'CRON_SUMMARY_JSON={"job":"paper_demo","status":"ok","dry_run":false}\'); '
              f"raise SystemExit({exit_code})")
    code, report = runner.run_logged([sys.executable, "-c", source], root=tmp_path,
        name="stock_swing_paper_demo_midday", require_summary=True)
    assert code == exit_code and report["status"] == ("ok" if exit_code == 0 else "error")
    assert (tmp_path / "sell_calls").read_text() == "SELL:3\n"
    assert report["observation"]["status"] == expected
    assert report["observation"]["preflight"]["status"] == "error"
    assert report["observation"]["preflight"]["reason"] == "missing_ledger_revision"
    assert "OBSERVATION_PREFLIGHT_JSON=" in Path(report["log_file"]).read_text()


@pytest.mark.parametrize("status,dry_run,expected", [("skipped", False, "not_run"), ("ok", True, "dry_run"), ("ok", False, "unknown")])
def test_missing_console_snapshot_is_not_success_or_stale_file_fallback(tmp_path, status, dry_run, expected):
    stale = tmp_path / "reports/console/latest_console_summary.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps({"decision_funnel": {"entry_restriction_review": {"status": "observing"}}}))
    marker = json.dumps({"job": "paper_demo", "status": status, "dry_run": dry_run})
    code, report = runner.run_logged([sys.executable, "-c", f"print('CRON_SUMMARY_JSON=' + {marker!r})"],
        root=tmp_path, name="stock_swing_paper_demo_market_open", require_summary=True)
    assert code == 0 and report["observation"]["status"] == expected


def test_all_four_managed_workflow_names_have_observation_diagnostics():
    assert runner.OBSERVATION_JOBS == {"stock_swing_paper_demo_" + slot for slot in
        ("premarket", "market_open", "midday", "market_close")}
