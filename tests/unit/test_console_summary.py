"""Tests for P4-C: structured console summary."""
from __future__ import annotations

import json
from types import SimpleNamespace

from stock_swing.reporting.console_summary import ConsoleSummary


def test_build_creates_summary_from_decisions() -> None:
    decisions = [
        SimpleNamespace(action="buy"),
        SimpleNamespace(action="buy"),
        SimpleNamespace(action="sell"),
        SimpleNamespace(action="deny"),
    ]
    submissions = [
        SimpleNamespace(status="submitted", sizing_details={"price_source": "decision_latest_close"}),
        SimpleNamespace(status="rejected", sizing_details={}),
    ]
    s = ConsoleSummary.build(
        run_id="test-run-1",
        equity=1_000_000.0,
        open_position_count=12,
        decisions=decisions,
        submissions=submissions,
        market_regime="neutral",
    )
    assert s.signals_buy == 2
    assert s.signals_sell == 1
    assert s.signals_deny == 1
    assert s.orders_submitted == 1
    assert s.orders_rejected == 1
    assert s.market_regime == "neutral"


def test_to_dict_contains_expected_keys() -> None:
    s = ConsoleSummary.build(run_id="r1", equity=100_000.0, open_position_count=5)
    d = s.to_dict()
    assert "signals" in d
    assert "orders" in d
    assert "risk" in d
    assert "data_quality" in d
    assert d["equity"] == 100_000.0


def test_emit_writes_parseable_json(capsys) -> None:
    s = ConsoleSummary.build(run_id="r2", equity=100_000.0, open_position_count=3)
    s.emit()
    captured = capsys.readouterr()
    line = [l for l in captured.out.splitlines() if "CONSOLE_SUMMARY_JSON" in l][0]
    payload = json.loads(line.replace("CONSOLE_SUMMARY_JSON ", ""))
    assert payload["run_id"] == "r2"
    assert payload["equity"] == 100_000.0
