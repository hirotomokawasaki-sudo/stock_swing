from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

massive_stub = types.ModuleType("massive")
massive_stub.RESTClient = object
sys.modules.setdefault("massive", massive_stub)

from console.services.dashboard_service import DashboardService
from console.utils.structured_json import parse_json_from_output
from stock_swing.cli import collect_data, paper_demo
from stock_swing.cli.cron_summary import CRON_SUMMARY_PREFIX
from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.guardrails.day_start_snapshot import current_market_date
from stock_swing.strategy_engine.base_strategy import CandidateSignal


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_parse_json_from_output_rejects_partial_json():
    parsed = parse_json_from_output('noise {"jobs":[{"id":"a"}')
    assert parsed.ok is False
    assert "balanced JSON" in (parsed.error or "")


def test_dashboard_system_status_blocks_on_cron_parse_error(monkeypatch, tmp_path):
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
            "market_date": current_market_date(),
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

    def _fake_run(args, capture_output, text, check, timeout):
        if args[:4] == ["openclaw", "cron", "list", "--json"]:
            return SimpleNamespace(
                returncode=0,
                stdout='banner {"jobs":[{"id":"job-1","name":"paper_demo","enabled":true}]} tail',
                stderr="",
            )
        if args[:4] == ["openclaw", "cron", "runs", "--id"]:
            return SimpleNamespace(returncode=0, stdout='{"runs":[{"id":"r1"}', stderr="")
        raise AssertionError(args)

    monkeypatch.setattr("console.adapters.system_adapter.subprocess.run", _fake_run)

    service = DashboardService(tmp_path)
    status = service.get_system_status()

    assert status["status"] == "blocked"
    assert "cron_run_history" in status["critical_missing"]
    assert status["evidence"]["cron_run_history"]["parse_coverage"] == 0.0


def test_dashboard_filters_synthetic_external_news(tmp_path):
    _write_json(
        tmp_path / "data" / "raw" / "finnhub" / "finnhub_aapl_news_2026-07-30_000000.json",
        {
            "endpoint": "company-news",
            "payload": {
                "symbol": "AAPL",
                "news": [
                    {
                        "headline": "Synthetic",
                        "summary": "bad",
                        "source": "synthetic",
                        "url": "https://example.local/aapl",
                    },
                    {
                        "headline": "Real headline",
                        "summary": "real summary",
                        "source": "reuters",
                        "url": "https://example.com/aapl",
                        "datetime": 1785417600,
                    },
                ],
            },
        },
    )
    service = DashboardService(tmp_path)
    items = service._load_external_news_items(limit=10)
    assert len(items) == 1
    assert items[0]["headline"] == "Real headline"


def test_collect_data_main_fails_closed_on_coverage_breach(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(collect_data, "project_root", tmp_path)
    monkeypatch.setattr(collect_data, "should_skip_non_market_day", lambda: (False, ""))
    sources_dir = tmp_path / "config" / "sources"
    sources_dir.mkdir(parents=True)
    (sources_dir / "finnhub.yaml").write_text("required: true\nenabled: true\n", encoding="utf-8")

    def _stub_collect_finnhub(symbols, store, max_runtime_seconds=0):
        _write_json(
            tmp_path / "data" / "audits" / "news_collection_status.json",
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "timed_out": False,
                "symbols": [
                    {"symbol": "AAPL", "news_count": 1, "used_fallback": False, "reason": "ok"},
                    {"symbol": "MSFT", "news_count": 0, "used_fallback": False, "reason": "no_company_news"},
                ],
            },
        )
        return [str(tmp_path / "data" / "raw" / "finnhub" / "dummy.json")], False

    monkeypatch.setattr(collect_data, "collect_finnhub", _stub_collect_finnhub)
    monkeypatch.setattr(
        sys,
        "argv",
        ["collect_data", "--cron-summary-json", "--sources", "finnhub", "--symbols", "AAPL,MSFT"],
    )

    exit_code = collect_data.main()
    out = capsys.readouterr().out
    summary_line = [line for line in out.splitlines() if line.startswith(CRON_SUMMARY_PREFIX)][-1]
    summary = json.loads(summary_line.split("=", 1)[1])

    assert exit_code == 1
    assert summary["status"] == "failed"
    assert summary["required_failures"]


def test_attach_ai_telemetry_treats_non_llm_strategy_as_rule_based_zero():
    class _Decision:
        pass

    decision = _Decision()
    decision.strategy_id = "custom_breakout_variant"
    decision.action = "buy"
    decision.confidence = 0.9
    decision.signal_strength = 0.9
    decision.deny_reasons = []
    decision.evidence = {"foo": "bar"}
    decision.prompt_version = None
    decision.strategy_version_id = "custom_breakout_variant_v2"

    from stock_swing.utils.context_budget import attach_ai_telemetry

    attach_ai_telemetry(decision)

    assert decision.usage_source == "rule_based_zero"
    assert decision.input_tokens_actual == 0
    assert decision.input_tokens_estimated is None


def test_paper_demo_dry_run_halts_buys_when_day_start_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(paper_demo, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "should_skip_non_market_day", lambda: (False, ""))
    monkeypatch.setattr(paper_demo, "read_runtime_mode", lambda root: "paper")
    monkeypatch.setattr(
        paper_demo,
        "read_ledger_quality_gate",
        lambda root: {"current_status": "VALID", "enforce_invalid_ledger_blocks_live_ready": False},
    )
    monkeypatch.setattr(paper_demo.MarketCalendar, "is_market_open", lambda now=None: (True, "open"))
    monkeypatch.setattr(paper_demo.MarketCalendar, "is_regular_market_hours", lambda now=None: (True, "open"))
    monkeypatch.setattr(paper_demo, "should_skip_non_market_day", lambda: (False, ""))
    monkeypatch.setenv("BROKER_API_KEY", "key")
    monkeypatch.setenv("BROKER_API_SECRET", "secret")
    monkeypatch.setenv("BROKER_BASE_URL", "https://paper.example")

    guardrail_cfg = tmp_path / "config" / "guardrails" / "autonomous_stop.yaml"
    guardrail_cfg.parent.mkdir(parents=True, exist_ok=True)
    guardrail_cfg.write_text("paper_warning_only: false\nrules: {}\n", encoding="utf-8")

    class _KillSwitch:
        def __init__(self, state_file):
            self.state_file = state_file

        def check(self):
            return None

    class _Broker:
        def __init__(self, *args, **kwargs):
            self.base_url = "https://paper.example"

        def fetch_account(self):
            return SimpleNamespace(payload={"status": "ACTIVE", "equity": "100000", "buying_power": "100000"})

        def get_account(self):
            return {"equity": "100000"}

        def fetch_positions(self):
            return SimpleNamespace(payload=[])

    class _Fetcher:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_bars(self, symbol, timeframe="1Day", limit=20):
            record = CanonicalRecord(
                record_id="r1",
                schema_version="v1",
                source="massive",
                source_type="bars",
                symbol=symbol,
                event_type="bar",
                event_time=datetime.now(timezone.utc),
                as_of="2026-07-30",
                ingested_at=datetime.now(timezone.utc),
                timezone="UTC",
                payload_version="v1",
                payload={"close": 100.0},
            )
            return [record], "massive"

    def _momentum_results(self, records):
        return [
            FeatureResult(
                feature_name="price_momentum",
                symbol="AAPL",
                computed_at=datetime.now(timezone.utc),
                values={"momentum": 0.08, "trend": "up", "bars_used": 20, "latest_close": 100.0},
            )
        ]

    def _macro_results(self, records):
        return []

    def _buy_signal(self, features):
        return [
            CandidateSignal(
                strategy_id="breakout_momentum_v1",
                symbol="AAPL",
                action="buy",
                signal_strength=0.95,
                generated_at=datetime.now(timezone.utc),
                time_horizon="3d",
                confidence=0.9,
                reasoning="test buy",
                metadata={"latest_close": 100.0},
            )
        ]

    def _no_signals(self, *args, **kwargs):
        return []

    class _EntryFilterResult:
        passed = None
        blocked: list[tuple[str, str]] = []
        stats: dict[str, object] = {}

    def _filter_identity(self, decisions, records_by_symbol, closed_trades, etf_symbols):
        result = _EntryFilterResult()
        result.passed = decisions
        return result

    monkeypatch.setattr(paper_demo, "KillSwitch", _KillSwitch)
    monkeypatch.setattr(paper_demo, "BrokerClient", _Broker)
    monkeypatch.setattr("stock_swing.sources.hybrid_data_fetcher.HybridDataFetcher", _Fetcher)
    monkeypatch.setattr(paper_demo.PriceMomentumFeature, "compute", _momentum_results)
    monkeypatch.setattr(paper_demo.MacroRegimeFeature, "compute", _macro_results)
    monkeypatch.setattr(paper_demo.BreakoutMomentumStrategy, "generate", _buy_signal)
    monkeypatch.setattr(paper_demo.EventSwingStrategy, "generate", _no_signals)
    monkeypatch.setattr(paper_demo.SimpleExitV2Strategy, "generate", _no_signals)
    monkeypatch.setattr(paper_demo.EntryFilterEngine, "filter", _filter_identity)
    monkeypatch.setattr(paper_demo, "get_permanent_block_summary", lambda **kwargs: [])
    monkeypatch.setattr(paper_demo, "prioritize_buy_signals", lambda entry_signals, *args, **kwargs: entry_signals)
    monkeypatch.setattr(paper_demo, "prioritize_buy_signals_v2", lambda entry_signals, *args, **kwargs: entry_signals)
    monkeypatch.setattr(
        "stock_swing.guardrails.day_start_snapshot.get_prev_unrealized_for_guardrail",
        lambda *args, **kwargs: (None, ["day_start_unrealized"]),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["paper_demo", "--dry-run", "--cron-summary-json", "--symbols", "AAPL"],
    )

    exit_code = paper_demo.main()
    out = capsys.readouterr().out
    summary_line = [line for line in out.splitlines() if line.startswith(CRON_SUMMARY_PREFIX)][-1]
    summary = json.loads(summary_line.split("=", 1)[1])
    breaker = json.loads((tmp_path / "data" / "guardrails" / "circuit_breaker.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert summary["status"] == "error"
    assert breaker["status"] == "halted"
