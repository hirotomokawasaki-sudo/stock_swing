"""Tests for SystemAdapter._evaluate_required_source('finnhub') no_company_news handling.

Regression: 2026-08-04. The console's source_sla health check
(SystemAdapter._evaluate_required_source) independently duplicated the same
'no_company_news == failure' bug as collect_data.py's
_evaluate_required_source_failures(). Both now share
collect_data.finnhub_news_row_succeeded() so they agree.

See docs/daily_logs/2026-08-04.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from console.adapters.system_adapter import SystemAdapter


def _write_status(tmp_path: Path, symbols: list[dict], timed_out: bool = False) -> None:
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True, exist_ok=True)
    (status_dir / "news_collection_status.json").write_text(
        json.dumps({
            "time": datetime.now(timezone.utc).isoformat(),
            "timed_out": timed_out,
            "symbols": symbols,
        }),
        encoding="utf-8",
    )


def test_no_company_news_alone_reports_ok(tmp_path):
    """AC: RBRK-only no_company_news among otherwise-ok symbols -> ok=True."""
    symbols = [{"symbol": f"S{i}", "news_count": 3, "used_fallback": False, "reason": "ok"} for i in range(43)]
    symbols.append({"symbol": "RBRK", "news_count": 0, "used_fallback": False, "reason": "no_company_news"})
    _write_status(tmp_path, symbols)

    adapter = SystemAdapter(tmp_path)
    result = adapter._evaluate_required_source("finnhub")

    assert result["ok"] is True, f"no_company_news alone must not fail source_sla, got: {result}"
    assert result["coverage_pct"] == 100.0
    assert result["failure_reasons"] == []


def test_real_failure_alongside_no_company_news_reports_not_ok(tmp_path):
    """A genuine failure (rate_limit) must still be reported even when
    no_company_news is also present."""
    symbols = [{"symbol": f"S{i}", "news_count": 3, "used_fallback": False, "reason": "ok"} for i in range(5)]
    symbols.append({"symbol": "RBRK", "news_count": 0, "used_fallback": False, "reason": "no_company_news"})
    symbols.append({"symbol": "BADSYM", "news_count": 0, "used_fallback": False, "reason": "rate_limit"})
    _write_status(tmp_path, symbols)

    adapter = SystemAdapter(tmp_path)
    result = adapter._evaluate_required_source("finnhub")

    assert result["ok"] is False
    assert "rate_limit" in result["failure_reasons"]
    assert "no_company_news" not in result["failure_reasons"]


def test_missing_status_file_reports_not_ok(tmp_path):
    """境界値: status file missing -> not ok, no crash."""
    adapter = SystemAdapter(tmp_path)
    result = adapter._evaluate_required_source("finnhub")
    assert result["ok"] is False
    assert result["reason"] == "missing_status"
