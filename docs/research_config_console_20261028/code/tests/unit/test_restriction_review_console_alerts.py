"""Acceptance: PF review notices reach CLI and the real web alert renderer."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from console.services.dashboard_service import DashboardService
from stock_swing.reporting.console_renderer import ConsoleRenderer
from stock_swing.reporting.console_summary import ConsoleSummary
from stock_swing.reporting.restriction_review_alerts import build_restriction_review_alerts

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
CODE = "entry_restriction_review_candidate"


def review(symbol="IBM"):
    return {
        "status": "observing", "eligible_to_trade": False, "automatic_release": False,
        "candidates": [symbol], "rows": [{
            "symbol": symbol, "strategy_id": "breakout", "cohort": "config-A",
            "status": "review_candidate", "completed": 30, "required": 30, "pending": 0,
            "eligible_to_trade": False, "requires_operator_approval": True,
            "requires_strategy_exit_validation": True,
        }],
    }


def write_summary(root, value=None, stamp=NOW, **kwargs):
    summary = ConsoleSummary.build(
        run_id="paper-observer-run", equity=100000, open_position_count=0,
        invocation_source="paper_demo_scheduled", entry_filter_stats={
            "entry_restriction_review": value if value is not None else review(),
        }, **kwargs,
    )
    summary.timestamp = stamp.isoformat()
    path = root / "reports/console/latest_console_summary.json"
    summary.emit(path)
    return path, summary


@pytest.fixture
def service(tmp_path, monkeypatch):
    # Only external broker connectivity is disabled; use real adapters/services.
    monkeypatch.delenv("BROKER_API_KEY", raising=False)
    monkeypatch.delenv("BROKER_API_SECRET", raising=False)
    return DashboardService(tmp_path)


def test_ac_summary_json_and_cli_alert_does_not_grant_permission(tmp_path):
    before = review()
    _, summary = write_summary(tmp_path, before)
    alerts = summary.to_dict()["alerts"]
    assert len(alerts) == 1 and alerts[0]["code"] == CODE
    assert "購入制限は継続中" in alerts[0]["message"]
    assert "手動承認" in ConsoleRenderer().render(summary)
    assert summary.run_status == "OK" and before == review()
    assert alerts[0]["details"]["eligible_to_trade"] is False
    assert alerts[0]["details"]["automatic_release"] is False


@pytest.mark.parametrize("value", [None, [], "bad", {},
    {**review(), "status": "error"}, {**review(), "status": "disabled"},
    {**review(), "candidates": []}, {**review(), "candidates": [{}]},
    {**review(), "eligible_to_trade": True}, {**review(), "automatic_release": True},
    {**review(), "rows": [None]}, {**review(), "rows": {}},
])
def test_ac_missing_or_invalid_observer_result_never_advertises_a_candidate(value):
    assert build_restriction_review_alerts(value) == []


@pytest.mark.parametrize("changes", [
    {"status": "collecting"}, {"completed": 29}, {"completed": True},
    {"required": 0}, {"requires_operator_approval": False},
    {"requires_strategy_exit_validation": False}, {"eligible_to_trade": True},
])
def test_ac_unconfirmed_or_incomplete_row_does_not_create_alert(changes):
    value = review()
    value["rows"][0].update(changes)
    assert build_restriction_review_alerts(value) == []


def test_ac_multiple_cohorts_are_preserved_without_duplicate_symbol_notices():
    value = review()
    other = copy.deepcopy(value["rows"][0]); other["cohort"] = "config-B"
    value["rows"].append(other); value["candidates"].append("IBM")
    alerts = build_restriction_review_alerts(value)
    assert len(alerts) == 1 and alerts[0]["details"]["symbols"] == ["IBM"]
    assert [row["cohort"] for row in alerts[0]["details"]["cohorts"]] == ["config-A", "config-B"]


@pytest.mark.parametrize("age,expected", [(0, True), (24*3600, True), (24*3600+1, False), (-1, False)])
def test_ac_web_requires_fresh_nonfuture_paper_snapshot(service, tmp_path, age, expected):
    path, _ = write_summary(tmp_path, stamp=NOW-timedelta(seconds=age))
    original = path.read_bytes()
    alerts = service._get_entry_restriction_review_alerts(now=NOW)
    assert bool(alerts) is expected and path.read_bytes() == original
    if expected:
        assert alerts[0]["title"] == "購入停止の再検証候補（要承認）"
        assert "最終観測:" in alerts[0]["message"]


@pytest.mark.parametrize("patch", [
    {"dry_run": True}, {"dry_run": None}, {"mode": "live"},
    {"invocation_source": "paper_demo_dry_run"}, {"run_id": ""},
    {"invocation_source": "paper_demo_cli"},
    {"run_id": 12}, {"run_id": "   "},
    {"timestamp": "2026-10-28T12:00:00"}, {"timestamp": "invalid"},
])
def test_ac_diagnostic_or_ambiguous_snapshot_is_not_operational_notice(service, tmp_path, patch):
    path, _ = write_summary(tmp_path)
    value = json.loads(path.read_text()); value["run"].update(patch)
    path.write_text(json.dumps(value))
    assert service._get_entry_restriction_review_alerts(now=NOW) == []


def test_ac_candidate_withdrawal_missing_and_corrupt_replace_cached_alert(service, tmp_path):
    path, _ = write_summary(tmp_path)
    assert service._get_entry_restriction_review_alerts(now=NOW)
    collecting = review(); collecting.update(candidates=[])
    collecting["rows"][0]["status"] = "collecting"
    write_summary(tmp_path, collecting)
    assert service._get_entry_restriction_review_alerts(now=NOW) == []
    write_summary(tmp_path)
    assert service._get_entry_restriction_review_alerts(now=NOW)
    path.write_text("{broken JSON")
    assert service._get_entry_restriction_review_alerts(now=NOW) == []
    path.unlink()
    assert service._get_entry_restriction_review_alerts(now=NOW) == []
    for bad in [[], {"run": []}, {"run": {}}, {"run": None}]:
        path.write_text(json.dumps(bad))
        assert service._get_entry_restriction_review_alerts(now=NOW) == []


def test_ac_dry_run_summary_never_emits_review_alert(tmp_path):
    _, summary = write_summary(tmp_path, dry_run=True)
    assert not any(a.code == CODE for a in summary.alerts)


def test_ac_real_dashboard_alert_list_reaches_actual_js_renderer(service, tmp_path):
    """2026-10-28: funnel text alone did not reach the Web's separate alert list."""
    symbol = '<img src=x onerror="bad()">'
    write_summary(tmp_path, review(symbol), stamp=datetime.now(timezone.utc))
    alerts = service.get_alerts(
        overview={}, trading={"summary": {}}, positions={"summary": {}, "positions": []},
        cron_jobs={"jobs": []}, data_status={}, news={"diagnostics": {"tracked_symbols": ["IBM"]}},
    )
    notice = next(a for a in alerts if a["code"] == CODE)
    assert notice["details"]["symbols"] == [symbol]
    assert "解除しません" in notice["action_hint"]
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required to run the actual existing browser renderer")
    app = Path(__file__).resolve().parents[2] / "console/ui/app.js"
    script = """
const fs = require('fs'), vm = require('vm');
const ctx = {console: {log(){}}, document: {addEventListener(){}}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
ctx.payload = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(vm.runInContext(`(() => {
    const view = Object.create(Console.prototype); view.data = payload;
    return view.renderAlerts();
})()`, ctx));
"""
    result = subprocess.run([node, "-e", script, str(app)], input=json.dumps({"alerts": alerts}),
                            capture_output=True, text=True, check=True, timeout=10)
    assert "要対応アラート" in result.stdout and "購入停止の再検証候補（要承認）" in result.stdout
    assert "購入制限は継続中" in result.stdout and "手動承認" in result.stdout
    assert "&lt;img" in result.stdout and "<img" not in result.stdout
    assert "<button" not in result.stdout, "The notice must never offer an unlock control"
