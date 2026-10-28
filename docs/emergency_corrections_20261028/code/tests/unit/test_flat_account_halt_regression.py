"""Production-path regressions for the 2026-10-21 flat-account false HALT.

Incident: confirmed broker positions=[] was captured as missing unrealized PnL.
Only external HTTP/SDK I/O is faked; main, snapshots and recovery are real.
All persistent state and config used by main are isolated under tmp_path.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from stock_swing.cli import paper_demo
from stock_swing.cli.cron_summary import CRON_SUMMARY_PREFIX
from stock_swing.guardrails.day_start_snapshot import capture_snapshot
from stock_swing.sources import massive_client
from stock_swing.tracking.pnl_tracker import PnLTracker


class _MassiveSDK:
    """External SDK fixture with fresh, flat daily bars: no entry signals."""

    def __init__(self, **kwargs):
        pass

    def list_aggs(self, **kwargs):
        for index in range(20):
            stamp = datetime.now(timezone.utc) - timedelta(days=19 - index)
            yield SimpleNamespace(
                timestamp=int(stamp.timestamp() * 1000), open=100.0,
                high=101.0, low=99.0, close=100.0, volume=2_000_000,
                vwap=100.0, transactions=10,
            )

    def get_ticker_details(self, symbol):
        return SimpleNamespace(
            ticker=symbol, name="Fixture Corp", market="stocks", currency_name="usd",
        )

    def get_rsi(self, **kwargs):
        return SimpleNamespace(values=[])


def _write_config(root: Path) -> None:
    runtime = root / "config/runtime/current_mode.yaml"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        "mode: paper\nledger_quality_gate:\n  current_status: VALID\n",
        encoding="utf-8",
    )
    guardrail = root / "config/guardrails/autonomous_stop.yaml"
    guardrail.parent.mkdir(parents=True)
    guardrail.write_text("paper_warning_only: false\nrules: {}\n", encoding="utf-8")


@pytest.fixture
def run_flat_account_main(monkeypatch, tmp_path, capsys):
    """Run real main without signals, writes outside tmp_path, or real network."""
    _write_config(tmp_path)
    monkeypatch.setattr(paper_demo, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_REGISTRY_PATH", tmp_path / "config/reference/symbol_registry.yaml")
    monkeypatch.setattr(paper_demo, "_ALLOC_CONFIG_PATH", tmp_path / "config/strategy/portfolio_allocation.yaml")
    monkeypatch.setattr(massive_client, "_MassiveRESTClient", _MassiveSDK)
    for key, value in {
        "BROKER_API_KEY": "fixture-key", "BROKER_API_SECRET": "fixture-secret",
        "BROKER_BASE_URL": "https://paper.example", "MASSIVE_API_KEY": "fixture-massive",
        "STOCK_SWING_FORCE_MARKET_DAY": "true", "PAPER_DEMO_MAX_WORKERS": "1",
    }.items():
        monkeypatch.setenv(key, value)

    def _deny_urlopen(*args, **kwargs):
        raise AssertionError("Unexpected external urllib I/O in HALT regression")

    monkeypatch.setattr(urllib.request, "urlopen", _deny_urlopen)
    original_http_client = httpx.Client

    def _run(
        payload, *, saved_baseline=False, partial_baseline=False,
        recovery_pending=False, dry_run=False, sell_then_refetch=False,
    ):
        if saved_baseline:
            capture_snapshot(
                tmp_path, equity=100_000.0, unrealized_pnl=25.0,
                source="broker_api",
            )
        if partial_baseline:
            capture_snapshot(
                tmp_path, equity=100_000.0, unrealized_pnl=None, source="broker_api",
            )
        sell_position = {
            "symbol": "NVDA", "qty": "3", "avg_entry_price": "120",
            "current_price": "100", "market_value": "300",
            "unrealized_pl": "-60", "unrealized_plpc": "-0.166667",
        }
        if sell_then_refetch:
            tracker = PnLTracker(tmp_path)
            tracker.record_submission(
                symbol="NVDA", strategy_id="breakout_momentum_v1", side="buy",
                qty=3, price=120.0, broker_order_id="fixture-prior-buy",
                decision_id="fixture-entry-decision",
            )
            exit_config = tmp_path / "config/strategy/simple_exit_v2.yaml"
            exit_config.parent.mkdir(parents=True, exist_ok=True)
            exit_config.write_text(
                "min_hold_days_enabled: false\nstop_loss_pct: -0.07\n",
                encoding="utf-8",
            )
        if recovery_pending:
            breaker = tmp_path / "data/guardrails/circuit_breaker.json"
            breaker.parent.mkdir(parents=True, exist_ok=True)
            breaker.write_text(json.dumps({
                "status": "recovery_pending", "action": "allow",
                "reason": "manual_clear", "clear_note": "synthetic recovery fixture",
            }), encoding="utf-8")
        calls = []
        submitted_order = None
        post_submit_positions_reads = 0

        def _transport(request):
            nonlocal submitted_order, post_submit_positions_reads
            calls.append((request.method, request.url.path))
            if request.method == "POST":
                order = json.loads(request.content)
                assert sell_then_refetch, "No order submission is permitted without the explicit SELL fixture"
                assert request.url.path == "/v2/orders", "Synthetic SELL must use the orders endpoint"
                assert order["symbol"] == "NVDA" and order["side"] == "sell", "Only the synthetic risk exit is permitted"
                assert submitted_order is None, "The fixture permits exactly one synthetic SELL"
                submitted_order = {
                    **order, "id": "fixture-sell-order", "symbol": "NVDA", "side": "sell",
                    "status": "accepted", "qty": str(order["qty"]), "filled_qty": "0",
                }
                return httpx.Response(200, json=submitted_order)
            assert request.method == "GET", "No unsupported external mutation is permitted"
            if request.url.path == "/v2/account":
                return httpx.Response(200, json={
                    "id": "account-fixture", "status": "ACTIVE", "equity": "100000", "cash": "100000",
                    "buying_power": "100000",
                })
            if request.url.path == "/v2/positions":
                if sell_then_refetch and submitted_order is None:
                    return httpx.Response(200, json=[sell_position])
                if submitted_order is not None:
                    post_submit_positions_reads += 1
                if payload == "fetch_failure":
                    return httpx.Response(401, json={"message": "synthetic fetch failure"})
                return httpx.Response(200, json=payload)
            if "quotes" in request.url.path:
                return httpx.Response(200, json={"quote": {"bp": 99.0, "ap": 101.0}})
            if request.url.path == "/v2/orders":
                return httpx.Response(200, json=[])
            if request.url.path == "/v2/orders/fixture-sell-order":
                return httpx.Response(200, json=submitted_order)
            raise AssertionError(f"Unexpected fixture request: {request.url.path}")

        monkeypatch.setattr(
            httpx, "Client",
            lambda **kwargs: original_http_client(
                transport=httpx.MockTransport(_transport), **kwargs,
            ),
        )
        argv = [
            "paper_demo", "--symbols", "NVDA", "--allow-outside-hours",
            "--min-momentum", "99", "--cron-summary-json",
        ]
        if dry_run:
            argv.append("--dry-run")
        monkeypatch.setattr(sys, "argv", argv)
        exit_code = paper_demo.main()
        output = capsys.readouterr()
        def _reject_nonfinite(constant):
            raise AssertionError(f"Nonfinite value {constant} must never reach machine-readable JSON")

        summaries = [
            line for line in output.out.splitlines()
            if line.startswith(CRON_SUMMARY_PREFIX)
        ]
        assert summaries, f"main must finish and emit its cron summary: {output.err}"
        summary = json.loads(summaries[-1].split("=", 1)[1], parse_constant=_reject_nonfinite)
        console_lines = [
            line for line in output.out.splitlines()
            if line.startswith("CONSOLE_SUMMARY_JSON ")
        ]
        assert console_lines, "Main must emit its machine-readable console state"
        console = json.loads(
            console_lines[-1].split(" ", 1)[1], parse_constant=_reject_nonfinite,
        )
        if payload != [] or sell_then_refetch:
            assert console["portfolio"]["unrealized_pnl"] is None, "Unknown current PnL must remain JSON null"
            assert console["portfolio"]["total_pnl"] is None, "Unknown PnL cannot produce a fabricated total"
            assert "unrealized_pnl" in console["missing_metrics"], "Missing current evidence must propagate to reports"
            assert console["health"]["status"] == "HALTED", "Machine-readable health must preserve HALT"
            assert any(
                alert["code"] == "unrealized_pnl_missing" for alert in console["alerts"]
            ), "Unknown PnL must carry a critical missing-evidence alert"
            assert "unrealized_pnl= N/A" in output.out, "Human-readable reporting must not show unknown as zero"
        breaker = json.loads(
            (tmp_path / "data/guardrails/circuit_breaker.json").read_text(encoding="utf-8")
        )
        snapshot = json.loads(
            (tmp_path / "data/guardrails/day_start_snapshot.json").read_text(encoding="utf-8")
        )
        assert ("GET", "/v2/positions") in calls, "Real main must fetch broker positions"
        if sell_then_refetch:
            assert submitted_order is not None, "Production must submit its synthetic risk exit"
            assert post_submit_positions_reads > 0, "Test must exercise the post-submit fresh read"
        return exit_code, summary, breaker, snapshot

    return _run


@pytest.mark.parametrize("recovery_pending", [False, True], ids=["initial", "recovery"])
def test_confirmed_flat_main_captures_zero_and_finishes_cleanly(
    run_flat_account_main, recovery_pending,
):
    """Regression: 2026-10-21 [] must not re-HALT a clean recovery run."""
    exit_code, summary, breaker, snapshot = run_flat_account_main(
        [], recovery_pending=recovery_pending,
    )
    assert snapshot["day_start_unrealized"] == pytest.approx(0.0), "Confirmed flat means zero PnL"
    assert snapshot["missing_fields"] == [], "Zero must be present, not missing"
    assert exit_code == 0, "A clean flat run must complete successfully"
    assert summary["status"] == "ok", "Cron must observe a successful run"
    assert breaker["status"] == "ok", "Clean recovery must reach ok through post-run verification"
    if recovery_pending:
        assert breaker["reason"] == "clean_run_verified", "Recovery cannot bypass clean-run verification"


_INVALID_POSITIONS = [
    pytest.param("fetch_failure", id="fetch-raises"),
    pytest.param(None, id="null-payload"),
    pytest.param({}, id="mapping-not-list"),
    pytest.param([None], id="malformed-row"),
    pytest.param([{"symbol": "NVDA", "qty": "0.5"}], id="fractional-missing-pnl"),
    pytest.param([{"symbol": "NVDA", "qty": "-1"}], id="short-missing-pnl"),
    pytest.param([{"symbol": "NVDA", "qty": "1"}], id="long-missing-pnl"),
    pytest.param([{"symbol": "NVDA", "qty": "1", "unrealized_pl": None}], id="null-pnl"),
    pytest.param([{"symbol": "NVDA", "qty": "1", "unrealized_pl": "bad"}], id="malformed-pnl"),
    pytest.param([{"symbol": "NVDA", "qty": "1", "unrealized_pl": "nan"}], id="nan-pnl"),
    pytest.param([{"symbol": "NVDA", "qty": "1", "unrealized_pl": "inf"}], id="infinite-pnl"),
    pytest.param([
        {"symbol": "NVDA", "qty": "1", "unrealized_pl": "15"}, None,
    ], id="partial-valid-then-malformed"),
]


@pytest.mark.parametrize("payload", _INVALID_POSITIONS)
@pytest.mark.parametrize("saved_baseline", [False, True], ids=["no-baseline", "saved-valid-baseline"])
def test_unknown_current_positions_halt_even_with_saved_valid_baseline(
    run_flat_account_main, payload, saved_baseline,
):
    """Regression: unknown positions/PnL must not turn into flat or clear recovery."""
    exit_code, summary, breaker, snapshot = run_flat_account_main(
        payload, saved_baseline=saved_baseline, recovery_pending=True,
    )
    assert exit_code == 1, "Unavailable current evidence must fail closed"
    assert summary["status"] == "error", "Cron must not call missing evidence a clean run"
    assert breaker["status"] == "halted", "Unknown current PnL must prevent recovery -> ok"
    if saved_baseline:
        assert snapshot["day_start_unrealized"] == pytest.approx(25.0), "Preserve a valid historical baseline"
    else:
        assert snapshot["day_start_unrealized"] is None, "Unknown current input must never capture zero"


def test_confirmed_flat_main_repairs_same_day_partial_snapshot(run_flat_account_main):
    """Regression: the prior incident's same-day null field must be repaired."""
    exit_code, summary, breaker, snapshot = run_flat_account_main(
        [], partial_baseline=True, recovery_pending=True,
    )
    assert snapshot["day_start_unrealized"] == pytest.approx(0.0), "Repair null from confirmed flat broker truth"
    assert snapshot["missing_fields"] == [], "The partial snapshot must become usable"
    assert exit_code == 0 and summary["status"] == "ok", "Repaired baseline must finish cleanly"
    assert breaker["status"] == "ok", "Repair permits verified recovery, not indefinite HALT"


@pytest.mark.parametrize("unrealized", [None, "bad", "nan"], ids=["null", "malformed", "nonfinite"])
def test_dry_run_with_unknown_pnl_finishes_error_summary_without_rendering_crash(
    run_flat_account_main, unrealized,
):
    """Unknown PnL must remain an explicit failure through dry-run reporting."""
    exit_code, summary, breaker, _snapshot = run_flat_account_main(
        [{"symbol": "NVDA", "qty": "1", "unrealized_pl": unrealized}],
        saved_baseline=True, dry_run=True,
    )
    assert exit_code == 1 and summary["status"] == "error", "Dry-run must report the real missing-data failure"
    assert breaker["status"] == "halted", "Presentation must not erase fail-closed state"


@pytest.mark.parametrize("payload", ["fetch_failure", {}, [None]], ids=["fetch-raises", "malformed", "malformed-list-row"])
def test_post_submit_unknown_positions_cannot_reuse_stale_pnl_as_clean_run(
    run_flat_account_main, payload,
):
    """Regression: a fresh read failure must not certify stale pre-order PnL."""
    exit_code, summary, breaker, snapshot = run_flat_account_main(
        payload, sell_then_refetch=True,
    )
    assert snapshot["day_start_unrealized"] == pytest.approx(-60.0), "Initial broker baseline remains valid"
    assert exit_code == 1 and summary["status"] == "error", "Unknown post-submit evidence is not clean"
    assert breaker["status"] == "halted", "Risk exit remains allowed, but fresh evidence failure must HALT BUYs"
