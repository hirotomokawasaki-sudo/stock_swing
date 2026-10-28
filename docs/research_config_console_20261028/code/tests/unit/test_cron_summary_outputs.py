from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

massive_stub = types.ModuleType("massive")
massive_stub.RESTClient = object
sys.modules.setdefault("massive", massive_stub)

from stock_swing.cli import collect_data, paper_demo
from stock_swing.cli.cron_summary import CRON_SUMMARY_PREFIX


def test_collect_data_dry_run_emits_cron_summary(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["collect_data", "--dry-run", "--cron-summary-json", "--sources", "finnhub"],
    )

    assert collect_data.main() == 0

    out = capsys.readouterr().out
    summary_line = [line for line in out.splitlines() if line.startswith(CRON_SUMMARY_PREFIX)][-1]
    payload = json.loads(summary_line.split("=", 1)[1])
    assert payload["job"] == "collect_data"
    assert payload["status"] == "ok"
    assert payload["dry_run"] is True
    assert payload["snapshot_count"] == 0


def test_paper_demo_build_cron_summary_counts_actions():
    decisions = [
        SimpleNamespace(action="buy", risk_state="pass"),
        SimpleNamespace(action="sell", risk_state="pass"),
        SimpleNamespace(action="deny", risk_state="fail"),
        SimpleNamespace(action="hold", risk_state="skip"),
    ]
    submissions = [
        SimpleNamespace(status="submitted"),
        SimpleNamespace(status="rejected"),
    ]

    summary = paper_demo._build_cron_summary(
        symbols=["AMD", "NVDA"],
        decisions=decisions,
        submissions=submissions,
        equity=123456.78,
        dry_run=False,
        exit_code=0,
        extra={"reason": "unit_test"},
    )

    assert summary == {
        "job": "paper_demo",
        "status": "ok",
        "exit_code": 0,
        "dry_run": False,
        "symbols": 2,
        "decisions": 4,
        "actionable": 2,
        "denied": 1,
        "held": 1,
        "submitted_orders": 1,
        "attempted_submissions": 2,
        "equity": 123456.78,
        "reason": "unit_test",
    }
