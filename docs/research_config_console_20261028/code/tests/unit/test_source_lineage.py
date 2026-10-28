from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

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
                    # NOTE (2026-08-04): 'no_company_news' is now treated as a
                    # successful-but-empty result (see collect_data.
                    # finnhub_news_row_succeeded), not a failure, since it just
                    # means the API call succeeded and the symbol legitimately
                    # has no articles (e.g. RBRK). Use 'rate_limit' here so this
                    # test still exercises a genuine collector failure causing
                    # a coverage breach.
                    {"symbol": "MSFT", "news_count": 0, "used_fallback": False, "reason": "rate_limit"},
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
    # 2026-08-14 fix: same root cause as the identical test in
    # test_remediation_20260730.py -- _load_external_news_items() only scans
    # files whose embedded filename date is within the last 5 days. A
    # hardcoded historical date ages out of that window and makes the file
    # invisible before any synthetic-filtering logic runs. Use today's date.
    _today = datetime.now().strftime("%Y-%m-%d")
    _write_json(
        tmp_path / "data" / "raw" / "finnhub" / f"finnhub_aapl_news_{_today}_000000.json",
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


# --- finnhub_news_row_succeeded / no_company_news handling (2026-08-04) ----
#
# Regression: RBRK legitimately has zero Finnhub company-news articles in
# most 3-day lookback windows. Prior to this fix, the collector's
# 'no_company_news' reason (a *successful* API call with an empty, correct
# result) was counted the same as a real failure (rate_limit/auth_error/
# timeout/api_error), causing stock_swing_news_collection to report a
# coverage breach and fail almost every run from 2026-07-30 onward even
# though every symbol was queried successfully. See docs/daily_logs/2026-08-04.md.

def test_finnhub_news_row_succeeded_no_company_news_counts_as_success():
    """AC: 'no_company_news' (legitimately empty result) is NOT a failure."""
    from stock_swing.cli.collect_data import finnhub_news_row_succeeded
    row = {"symbol": "RBRK", "news_count": 0, "used_fallback": False, "reason": "no_company_news"}
    assert finnhub_news_row_succeeded(row) is True


@pytest.mark.parametrize("reason", ["rate_limit", "auth_error", "timeout", "api_error", "empty_response"])
def test_finnhub_news_row_succeeded_real_failures_not_counted_as_success(reason):
    """Genuine collector failures must remain failures, unaffected by the
    no_company_news exemption."""
    from stock_swing.cli.collect_data import finnhub_news_row_succeeded
    row = {"symbol": "MSFT", "news_count": 0, "used_fallback": False, "reason": reason}
    assert finnhub_news_row_succeeded(row) is False


def test_finnhub_news_row_succeeded_used_fallback_not_success():
    """used_fallback rows are never counted as success, regardless of reason."""
    from stock_swing.cli.collect_data import finnhub_news_row_succeeded
    row = {"symbol": "MSFT", "news_count": 1, "used_fallback": True, "reason": "ok"}
    assert finnhub_news_row_succeeded(row) is False


def test_finnhub_news_row_succeeded_ok_with_zero_count_not_success():
    """reason='ok' with news_count=0 is an inconsistent/edge-case row and
    must NOT be treated as success (only explicit no_company_news is)."""
    from stock_swing.cli.collect_data import finnhub_news_row_succeeded
    row = {"symbol": "MSFT", "news_count": 0, "used_fallback": False, "reason": "ok"}
    assert finnhub_news_row_succeeded(row) is False


def test_evaluate_required_source_failures_regression_rbrk_no_company_news_passes(tmp_path):
    """
    Regression: 2026-08-03/04 stock_swing_news_collection failures.
    43/44 symbols 'ok' + 1 symbol (RBRK) 'no_company_news' must be treated
    as 100% coverage (44/44 successful calls), not a coverage breach.
    """
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True)
    symbols = [{"symbol": f"S{i}", "news_count": 3, "used_fallback": False, "reason": "ok"} for i in range(43)]
    symbols.append({"symbol": "RBRK", "news_count": 0, "used_fallback": False, "reason": "no_company_news"})
    status = {"symbols": symbols, "timed_out": False}
    (status_dir / "news_collection_status.json").write_text(json.dumps(status))

    failures = _evaluate_required_source_failures(tmp_path, "finnhub", written=["f.json"], timed_out=False)

    assert failures == [], f"no_company_news alone must not cause a failure, got: {failures}"


def test_evaluate_required_source_failures_real_failure_still_breaches_coverage(tmp_path):
    """A genuine collector failure (rate_limit) alongside no_company_news
    must still be reported (the no_company_news exemption must not mask
    other real failures)."""
    from stock_swing.cli.collect_data import _evaluate_required_source_failures
    status_dir = tmp_path / "data" / "audits"
    status_dir.mkdir(parents=True)
    symbols = [{"symbol": f"S{i}", "news_count": 3, "used_fallback": False, "reason": "ok"} for i in range(5)]
    symbols.append({"symbol": "RBRK", "news_count": 0, "used_fallback": False, "reason": "no_company_news"})
    symbols.append({"symbol": "BADSYM", "news_count": 0, "used_fallback": False, "reason": "rate_limit"})
    status = {"symbols": symbols, "timed_out": False}
    (status_dir / "news_collection_status.json").write_text(json.dumps(status))

    failures = _evaluate_required_source_failures(tmp_path, "finnhub", written=["f.json"], timed_out=False)

    assert any("rate_limit" in f for f in failures), f"rate_limit failure must still be reported: {failures}"
    assert not any("no_company_news" in f for f in failures), f"no_company_news must not appear as a failure: {failures}"
