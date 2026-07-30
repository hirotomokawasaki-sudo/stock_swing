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
