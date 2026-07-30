from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

massive_stub = types.ModuleType("massive")
massive_stub.RESTClient = object
sys.modules.setdefault("massive", massive_stub)

from console.services.dashboard_service import DashboardService
from stock_swing.cli import collect_data
from stock_swing.cli.cron_summary import CRON_SUMMARY_PREFIX


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_collect_data_main_fails_closed_on_coverage_breach(monkeypatch, tmp_path, capsys) -> None:
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


def test_dashboard_filters_synthetic_external_news(tmp_path: Path) -> None:
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


# --- collect_data changed-line カバレッジ補強 ---
import json as _json
import sys as _sys
from pathlib import Path


def test_evaluate_required_source_failures_empty_written(tmp_path):
    """0 snapshots written → failure reported."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    failures = _evaluate_required_source_failures(tmp_path, "finnhub", written=[], timed_out=False)
    assert any("0 snapshots" in f for f in failures)


def test_evaluate_required_source_failures_timed_out(tmp_path):
    """timed_out=True → failure reported."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    failures = _evaluate_required_source_failures(tmp_path, "finnhub", written=["f.json"], timed_out=True)
    assert any("timed out" in f for f in failures)


def test_evaluate_required_source_failures_missing_status(tmp_path):
    """Missing status file → failure reported."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    failures = _evaluate_required_source_failures(tmp_path, "finnhub", written=["f.json"], timed_out=False)
    assert any("missing" in f for f in failures)


def test_evaluate_required_source_failures_invalid_json(tmp_path):
    """Invalid status JSON → failure reported."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True)
    (status_dir / "news_collection_status.json").write_text("{bad json")
    failures = _evaluate_required_source_failures(tmp_path, "finnhub", written=["f.json"], timed_out=False)
    assert any("invalid" in f for f in failures)


def test_evaluate_required_source_failures_low_coverage(tmp_path):
    """Coverage below threshold → failure reported."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True)
    # 50% coverage (5/10 ok) — below 99.5% threshold
    symbols = [{"symbol": f"S{i}", "news_count": 1 if i < 5 else 0, "reason": "ok" if i < 5 else "error"}
               for i in range(10)]
    (status_dir / "news_collection_status.json").write_text(_json.dumps({"symbols": symbols}))
    failures = _evaluate_required_source_failures(tmp_path, "finnhub", written=["f.json"], timed_out=False)
    assert any("coverage" in f.lower() or "%" in f for f in failures)


def test_evaluate_required_source_failures_pass(tmp_path):
    """All ok rows at threshold → no failures."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True)
    symbols = [{"symbol": f"S{i}", "news_count": 2, "reason": "ok"} for i in range(10)]
    (status_dir / "news_collection_status.json").write_text(_json.dumps({"symbols": symbols}))
    failures = _evaluate_required_source_failures(tmp_path, "finnhub", written=["f.json"], timed_out=False)
    assert failures == []


def test_evaluate_required_source_failures_unknown_source(tmp_path):
    """Unknown source with data written → no extra failures."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    failures = _evaluate_required_source_failures(tmp_path, "optional_source", written=["f1.json","f2.json"], timed_out=False)
    # No coverage or timing failures; may have status-file warnings
    assert not any("coverage" in f.lower() for f in failures)


# --- collect_data changed-line 追加カバレッジ ---
def test_evaluate_required_source_coverage_breach(tmp_path):
    """Coverage below threshold adds coverage breach message."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True)
    # 0% coverage (all errors)
    symbols = [{"symbol": f"S{i}", "news_count": 0, "reason": "timeout"} for i in range(10)]
    status = {"symbols": symbols, "timed_out": False}
    (status_dir / "news_collection_status.json").write_text(__import__("json").dumps(status))
    failures = _evaluate_required_source_failures(tmp_path, "finnhub", written=["f.json"])
    assert any("coverage" in f.lower() or "breach" in f.lower() for f in failures)


def test_evaluate_required_source_status_file_timed_out(tmp_path):
    """status file reports timeout → failure added."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    import json as _json
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True)
    symbols = [{"symbol": f"S{i}", "news_count": 3, "reason": "ok"} for i in range(10)]
    status = {"symbols": symbols, "timed_out": True}
    (status_dir / "news_collection_status.json").write_text(_json.dumps(status))
    failures = _evaluate_required_source_failures(tmp_path, "finnhub", written=["f.json"])
    assert any("timeout" in f.lower() for f in failures)


def test_evaluate_required_source_generic_status_file_error(tmp_path):
    """Generic source (non-finnhub) with bad status → failure reported."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    import json as _json
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True)
    (status_dir / "fred_collection_status.json").write_text(_json.dumps({"status": "error"}))
    failures = _evaluate_required_source_failures(tmp_path, "fred", written=["f.json"])
    assert any("status=error" in f for f in failures)


def test_evaluate_required_source_generic_status_file_ok(tmp_path):
    """Generic source with status=ok → no failures."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    import json as _json
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True)
    (status_dir / "fred_collection_status.json").write_text(_json.dumps({"status": "ok"}))
    failures = _evaluate_required_source_failures(tmp_path, "fred", written=["f.json"])
    assert failures == []


def test_evaluate_required_source_generic_status_invalid_json(tmp_path):
    """Generic source with invalid JSON status → failure reported."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True)
    (status_dir / "fred_quotes_status.json").write_text("{broken}")
    failures = _evaluate_required_source_failures(tmp_path, "fred", written=["f.json"])
    assert any("invalid" in f.lower() or "json" in f.lower() for f in failures)
