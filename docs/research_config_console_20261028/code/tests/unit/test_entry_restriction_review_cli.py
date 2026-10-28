"""Real paper_demo entrypoint: observer cannot change orders or external I/O.

Only HTTP/SDK/filesystem boundaries are replaced; signal generation, gates,
observer persistence, summary construction and rendering execute real code.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from stock_swing.cli import paper_demo
from stock_swing.risk.entry_restriction_review import STORE
from stock_swing.sources import massive_client
from stock_swing.tracking.pnl_tracker import PnLTracker


def _exercise_main(tmp_path, monkeypatch, capsys, observer_state):
    root = tmp_path
    runtime = root / "config/runtime/current_mode.yaml"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("mode: paper\nledger_quality_gate:\n  current_status: VALID\n")
    guardrails = root / "config/guardrails/autonomous_stop.yaml"
    guardrails.parent.mkdir(parents=True)
    guardrails.write_text("paper_warning_only: false\nrules: {}\n")
    monkeypatch.setattr(paper_demo, "project_root", root)
    monkeypatch.setattr(paper_demo, "_REGISTRY_PATH", root / "config/reference/symbol_registry.yaml")
    monkeypatch.setattr(paper_demo, "_ALLOC_CONFIG_PATH", root / "config/strategy/portfolio_allocation.yaml")
    for key, value in {
        "BROKER_API_KEY": "fixture-key", "BROKER_API_SECRET": "fixture-secret",
        "BROKER_BASE_URL": "https://paper.example", "MASSIVE_API_KEY": "fixture-massive",
        "STOCK_SWING_FORCE_MARKET_DAY": "true", "PAPER_DEMO_MAX_WORKERS": "1",
        "ENTRY_RESTRICTION_REVIEW_ENABLED": "false" if observer_state == "disabled" else "true",
        "ENTRY_FILTER_DISABLED": "false", "ENTRY_FILTER_PF_GATE_SKIP_SYMBOLS": "",
        "ENTRY_FILTER_PURCHASE_RESTRICTED_SYMBOLS": "",
        "PAPER_DEMO_ALLOW_OFFHOURS_BUYS": "true", "PAPER_DEMO_EXIT_ONLY": "false",
        "BROKER_ACCOUNT_ID": "fixture-account",
    }.items():
        monkeypatch.setenv(key, value)

    tracker = PnLTracker(root)
    for index in range(5):
        tracker.record_submission(symbol="IBM", strategy_id="breakout_momentum_v1", side="buy",
                                  qty=1, price=100, broker_order_id=f"buy-{index}", decision_id=f"{index}-fixture",
                                  account_id="fixture-account")
        tracker.record_exit(symbol="IBM", exit_price=90, broker_order_id=f"sell-{index}")
    original_trades = json.loads((root / "data/tracking/pnl_state.json").read_text())["trades"]
    requests = []
    class RisingSDK:
        def __init__(self, **kwargs):
            pass
        def list_aggs(self, **kwargs):
            for index in range(20):
                stamp = datetime.now(timezone.utc) - timedelta(days=19 - index)
                opening = 100 + 3 * index
                yield SimpleNamespace(timestamp=int(stamp.timestamp() * 1000), open=opening,
                                      high=opening + 4, low=opening - 2, close=opening + 2,
                                      volume=2_000_000, vwap=opening + 1, transactions=10)
        def get_ticker_details(self, symbol):
            return SimpleNamespace(ticker=symbol, name="Fixture Corp", market="stocks", currency_name="usd")
        def get_rsi(self, **kwargs):
            return SimpleNamespace(values=[])
    monkeypatch.setattr(massive_client, "_MassiveRESTClient", RisingSDK)
    def deny_urlopen(*args, **kwargs):
        raise AssertionError("Unexpected extra external data/notification fetch")
    monkeypatch.setattr(urllib.request, "urlopen", deny_urlopen)
    original_client = httpx.Client
    def transport(request):
        requests.append((request.method, request.url.path))
        assert request.method == "GET", "PF-blocked candidates must NEVER submit an order"
        if request.url.path == "/v2/account":
            return httpx.Response(200, json={"status": "ACTIVE", "equity": "100000", "cash": "100000", "buying_power": "100000"})
        if request.url.path in {"/v2/orders", "/v2/positions"}:
            return httpx.Response(200, json=[])
        if "quotes" in request.url.path:
            return httpx.Response(200, json={"quote": {"bp": 158, "ap": 160}})
        if request.url.path == "/v2/stocks/IBM/bars":
            return httpx.Response(200, json={"bars": []})
        raise AssertionError(f"Unexpected HTTP request: {request.url.path}")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(transport), **kwargs))
    if observer_state == "corrupt":
        (root / STORE).parent.mkdir(parents=True, exist_ok=True)
        (root / STORE).write_text("{")
    argv = ["paper_demo", "--symbols", "IBM", "--allow-outside-hours", "--min-momentum", "0.05", "--cron-summary-json"]
    if observer_state == "dry_run":
        argv.append("--dry-run")
    monkeypatch.setattr(sys, "argv", argv)
    code = paper_demo.main()
    output = capsys.readouterr()
    console = json.loads([line for line in output.out.splitlines() if line.startswith("CONSOLE_SUMMARY_JSON ")][-1].split(" ", 1)[1])
    assert console["run"]["invocation_source"] == (
        "paper_demo_dry_run" if observer_state == "dry_run" else "paper_demo_scheduled"
    ), "Web alert provenance must match the real CLI's persisted run contract"
    review = console["decision_funnel"]["entry_restriction_review"]
    assert "pf_gate=1" in output.out, "Real BUY must reach and fail the actual PF gate"
    assert code == 0 and console["decision_funnel"]["submitted"] == 0
    assert all(method == "GET" for method, _ in requests)
    assert json.loads((root / "data/tracking/pnl_state.json").read_text())["trades"] == original_trades
    assert review["eligible_to_trade"] is False and review["candidates"] == []
    if observer_state == "enabled":
        assert review["status"] == "observing" and review["observations"] == 1
        captured = json.loads((root / STORE).read_text())["state"]["observations"][0]
        assert captured["symbol"] == "IBM" and captured["strategy_id"] == "breakout_momentum_v1"
        assert captured["decision_id"] and captured["run_id"] and captured["config_hash"]
        assert captured["effective_config"]["signal_config"]["min_momentum"] == .05
        assert captured["outcome"] is None, "Historical bars must never become prospective evidence on capture"
    elif observer_state == "corrupt":
        assert review["status"] == "error" and (root / STORE).read_text() == "{"
    else:
        assert review["status"] == ("disabled" if observer_state == "disabled" else "dry_run")
        assert not (root / STORE).exists()
    return requests


@pytest.mark.parametrize("observer_state", ["enabled", "disabled", "corrupt", "dry_run"])
def test_real_main_preserves_pf_denial_with_or_without_observer(tmp_path, monkeypatch, capsys, observer_state):
    _exercise_main(tmp_path, monkeypatch, capsys, observer_state)


def test_enabled_disabled_and_failure_have_identical_external_requests(tmp_path, monkeypatch, capsys):
    traces = []
    for observer_state in ["enabled", "disabled", "corrupt"]:
        root = tmp_path / observer_state
        with monkeypatch.context() as boundary_patches:
            traces.append(_exercise_main(root, boundary_patches, capsys, observer_state))
    assert traces[0] == traces[1] == traces[2], "Observer must neither add market-data calls nor change the business HTTP path"
