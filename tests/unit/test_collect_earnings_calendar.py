"""Tests for collect_data.collect_earnings_calendar (2026-08-07).

Regression: EarningsEventFeature -> EventSwingStrategy (event_swing_v1) had
never produced a single decision in production (0/2306 decision files as of
2026-08-07) because no collector ever called
FinnhubClient.fetch_earnings_calendar(). This locks in the new collector:
single API call for the whole universe, filtered locally to the requested
symbols, with fail-safe (never-raise, never-synthesize) behavior matching
the rest of collect_data.py's sources.
"""
from __future__ import annotations

import json
from pathlib import Path

from stock_swing.core.path_manager import PathManager
from stock_swing.storage.stage_store import StageStore


def _make_store(tmp_path):
    return StageStore(PathManager(tmp_path))


def test_no_client_without_api_key_returns_empty(tmp_path, monkeypatch):
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    written, status = module.collect_earnings_calendar(["AAPL", "MSFT"], _make_store(tmp_path))

    assert written == []
    assert status["status"] == "failed"
    assert status["reason"] == "missing_client"


def test_single_api_call_for_whole_universe(tmp_path, monkeypatch):
    """Must call fetch_earnings_calendar() exactly once (no per-symbol loop),
    unlike collect_finnhub()'s metric/news collection."""
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo
    from stock_swing.core.types import RawEnvelope
    from datetime import datetime, timezone

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")

    call_count = {"n": 0}

    class _FakeClient:
        def __init__(self, api_key, retry_config=None):
            pass

        def fetch_earnings_calendar(self, from_date=None, to_date=None):
            call_count["n"] += 1
            return RawEnvelope(
                source="finnhub",
                endpoint="calendar/earnings",
                fetched_at=datetime.now(timezone.utc),
                request_params={"from": from_date, "to": to_date},
                payload={
                    "earningsCalendar": [
                        {"symbol": "AAPL", "date": "2026-08-10", "epsEstimate": 1.5},
                        {"symbol": "TSLA", "date": "2026-08-11", "epsEstimate": 0.8},
                        {"symbol": "NOTINUNIVERSE", "date": "2026-08-12", "epsEstimate": 2.0},
                    ]
                },
            )

    monkeypatch.setattr(module, "FinnhubClient", _FakeClient)

    written, status = module.collect_earnings_calendar(["AAPL", "TSLA"], _make_store(tmp_path))

    assert call_count["n"] == 1
    assert status["status"] == "ok"
    assert status["symbols_with_upcoming_earnings"] == 2
    assert status["total_calendar_rows_fetched"] == 3
    assert len(written) == 1


def test_filters_out_symbols_outside_universe(tmp_path, monkeypatch):
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo
    from stock_swing.core.types import RawEnvelope
    from datetime import datetime, timezone

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")

    class _FakeClient:
        def __init__(self, api_key, retry_config=None):
            pass

        def fetch_earnings_calendar(self, from_date=None, to_date=None):
            return RawEnvelope(
                source="finnhub",
                endpoint="calendar/earnings",
                fetched_at=datetime.now(timezone.utc),
                request_params={},
                payload={
                    "earningsCalendar": [
                        {"symbol": "AAPL", "date": "2026-08-10", "epsEstimate": 1.5},
                        {"symbol": "RANDOMCO", "date": "2026-08-10", "epsEstimate": 0.5},
                    ]
                },
            )

    monkeypatch.setattr(module, "FinnhubClient", _FakeClient)

    written, status = module.collect_earnings_calendar(["AAPL"], _make_store(tmp_path))

    assert status["symbols_with_upcoming_earnings"] == 1
    assert len(written) == 1
    raw_files = list((tmp_path / "data" / "raw" / "finnhub").glob("*earnings_calendar*"))
    assert len(raw_files) == 1
    data = json.loads(Path(raw_files[0]).read_text(encoding="utf-8"))
    symbols_in_payload = {row["symbol"] for row in data["payload"]["earningsCalendar"]}
    assert symbols_in_payload == {"AAPL"}


def test_no_matching_symbols_writes_no_snapshot(tmp_path, monkeypatch):
    """If the calendar has rows but none are in our universe, no raw
    snapshot is written (nothing useful to persist), but status is still ok."""
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo
    from stock_swing.core.types import RawEnvelope
    from datetime import datetime, timezone

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")

    class _FakeClient:
        def __init__(self, api_key, retry_config=None):
            pass

        def fetch_earnings_calendar(self, from_date=None, to_date=None):
            return RawEnvelope(
                source="finnhub",
                endpoint="calendar/earnings",
                fetched_at=datetime.now(timezone.utc),
                request_params={},
                payload={"earningsCalendar": [{"symbol": "RANDOMCO", "date": "2026-08-10"}]},
            )

    monkeypatch.setattr(module, "FinnhubClient", _FakeClient)

    written, status = module.collect_earnings_calendar(["AAPL"], _make_store(tmp_path))

    assert written == []
    assert status["status"] == "ok"
    assert status["symbols_with_upcoming_earnings"] == 0


def test_empty_calendar_payload_does_not_raise(tmp_path, monkeypatch):
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo
    from stock_swing.core.types import RawEnvelope
    from datetime import datetime, timezone

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")

    class _FakeClient:
        def __init__(self, api_key, retry_config=None):
            pass

        def fetch_earnings_calendar(self, from_date=None, to_date=None):
            return RawEnvelope(
                source="finnhub", endpoint="calendar/earnings",
                fetched_at=datetime.now(timezone.utc), request_params={}, payload={},
            )

    monkeypatch.setattr(module, "FinnhubClient", _FakeClient)

    written, status = module.collect_earnings_calendar(["AAPL"], _make_store(tmp_path))

    assert written == []
    assert status["status"] == "ok"
    assert status["total_calendar_rows_fetched"] == 0


def test_api_error_reported_as_failed_status(tmp_path, monkeypatch):
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")

    class _FakeClient:
        def __init__(self, api_key, retry_config=None):
            pass

        def fetch_earnings_calendar(self, from_date=None, to_date=None):
            raise RuntimeError("500 internal server error")

    monkeypatch.setattr(module, "FinnhubClient", _FakeClient)

    written, status = module.collect_earnings_calendar(["AAPL"], _make_store(tmp_path))

    assert written == []
    assert status["status"] == "failed"
    assert status["reason"] == "api_error"


def test_rate_limit_error_classified_correctly(tmp_path, monkeypatch):
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")

    class _FakeClient:
        def __init__(self, api_key, retry_config=None):
            pass

        def fetch_earnings_calendar(self, from_date=None, to_date=None):
            raise RuntimeError("429 rate limit exceeded")

    monkeypatch.setattr(module, "FinnhubClient", _FakeClient)

    written, status = module.collect_earnings_calendar(["AAPL"], _make_store(tmp_path))

    assert status["reason"] == "rate_limit"


def test_client_init_failure_does_not_raise(tmp_path, monkeypatch):
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")

    class _BrokenClient:
        def __init__(self, api_key, retry_config=None):
            raise ValueError("boom")

    monkeypatch.setattr(module, "FinnhubClient", _BrokenClient)

    written, status = module.collect_earnings_calendar(["AAPL"], _make_store(tmp_path))

    assert written == []
    assert status["status"] == "failed"
    assert "client_init_failed" in status["reason"]


def test_status_file_written_to_audits_dir(tmp_path, monkeypatch):
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    module.collect_earnings_calendar(["AAPL"], _make_store(tmp_path))

    status_path = tmp_path / "data" / "audits" / "earnings_calendar_status.json"
    assert status_path.exists()
    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"


def test_written_snapshot_is_not_synthetic(tmp_path, monkeypatch):
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo
    from stock_swing.core.types import RawEnvelope
    from datetime import datetime, timezone

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")

    class _FakeClient:
        def __init__(self, api_key, retry_config=None):
            pass

        def fetch_earnings_calendar(self, from_date=None, to_date=None):
            return RawEnvelope(
                source="finnhub", endpoint="calendar/earnings",
                fetched_at=datetime.now(timezone.utc), request_params={},
                payload={"earningsCalendar": [{"symbol": "AAPL", "date": "2026-08-10"}]},
            )

    monkeypatch.setattr(module, "FinnhubClient", _FakeClient)

    written, _ = module.collect_earnings_calendar(["AAPL"], _make_store(tmp_path))
    data = json.loads(Path(written[0]).read_text(encoding="utf-8"))
    assert data["is_synthetic"] is False
