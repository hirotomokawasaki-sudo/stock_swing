"""R7-v2 (2026-08-14): collect_data.collect_fred() regression tests.

Replaces the long-standing not_implemented stub with a real FredClient call
against FRED_MACRO_SERIES (CPIAUCSL/UNRATE/T10Y2Y/ICSA).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from stock_swing.core.path_manager import PathManager
from stock_swing.core.types import RawEnvelope
from stock_swing.storage.stage_store import StageStore
from stock_swing.cli import collect_data as module


def _make_store(tmp_path):
    return StageStore(PathManager(tmp_path))


def test_collect_fred_no_api_key_writes_failed_status(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "project_root", tmp_path)
    import stock_swing.cli.paper_demo as paper_demo
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    # module-level `_load_env(project_root / ".env")` in paper_demo.py already
    # ran once at import time (before this test's monkeypatch), potentially
    # populating FRED_API_KEY from the real .env into os.environ for the
    # whole process. Must delenv *after* the paper_demo import, not before.
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    written = module.collect_fred(_make_store(tmp_path))

    assert written == []
    status_path = tmp_path / "data" / "audits" / "fred_collection_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert "FRED_API_KEY" in status["reason"]


def test_collect_fred_client_init_failure_writes_failed_status(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setenv("FRED_API_KEY", "dummy-key")
    import stock_swing.cli.paper_demo as paper_demo
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)

    with patch("stock_swing.sources.fred_client.FredClient", side_effect=RuntimeError("boom")):
        written = module.collect_fred(_make_store(tmp_path))

    assert written == []
    status_path = tmp_path / "data" / "audits" / "fred_collection_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert "FredClient init failed" in status["reason"]


def test_collect_fred_writes_snapshot_per_series_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setenv("FRED_API_KEY", "dummy-key")
    import stock_swing.cli.paper_demo as paper_demo
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)

    def _fake_fetch(series_id, limit=24, sort_order="desc"):
        return RawEnvelope(
            source="fred",
            endpoint="series/observations",
            fetched_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            request_params={"series_id": series_id},
            payload={"observations": [{"date": "2026-08-01", "value": "1.0"}]},
        )

    mock_client = MagicMock()
    mock_client.fetch_series_observations.side_effect = _fake_fetch

    with patch("stock_swing.sources.fred_client.FredClient", return_value=mock_client):
        written = module.collect_fred(_make_store(tmp_path))

    assert len(written) == len(module.FRED_MACRO_SERIES)
    status_path = tmp_path / "data" / "audits" / "fred_collection_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "ok"
    assert status["series_ok"] == len(module.FRED_MACRO_SERIES)
    assert status["series_failed"] == []

    raw_dir = tmp_path / "data" / "raw" / "fred"
    written_files = list(raw_dir.glob("*.json"))
    assert len(written_files) == len(module.FRED_MACRO_SERIES)


def test_collect_fred_partial_failure_is_degraded(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setenv("FRED_API_KEY", "dummy-key")
    import stock_swing.cli.paper_demo as paper_demo
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)

    call_count = {"n": 0}

    def _fake_fetch(series_id, limit=24, sort_order="desc"):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("rate_limited")
        return RawEnvelope(
            source="fred", endpoint="series/observations",
            fetched_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            request_params={"series_id": series_id},
            payload={"observations": [{"date": "2026-08-01", "value": "1.0"}]},
        )

    mock_client = MagicMock()
    mock_client.fetch_series_observations.side_effect = _fake_fetch

    with patch("stock_swing.sources.fred_client.FredClient", return_value=mock_client):
        written = module.collect_fred(_make_store(tmp_path))

    assert len(written) == len(module.FRED_MACRO_SERIES) - 1
    status_path = tmp_path / "data" / "audits" / "fred_collection_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "degraded"
    assert len(status["series_failed"]) == 1


def test_collect_fred_all_failures_is_failed_status(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setenv("FRED_API_KEY", "dummy-key")
    import stock_swing.cli.paper_demo as paper_demo
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)

    mock_client = MagicMock()
    mock_client.fetch_series_observations.side_effect = RuntimeError("down")

    with patch("stock_swing.sources.fred_client.FredClient", return_value=mock_client):
        written = module.collect_fred(_make_store(tmp_path))

    assert written == []
    status_path = tmp_path / "data" / "audits" / "fred_collection_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert len(status["series_failed"]) == len(module.FRED_MACRO_SERIES)


def test_fred_macro_series_matches_macro_regime_feature_expectations():
    """Regression: keep collect_data.FRED_MACRO_SERIES in sync with the
    series IDs macro_regime_feature.py actually looks for."""
    from stock_swing.feature_engine.macro_regime_feature import (
        _CPI_SERIES, _UNRATE_SERIES, _YIELD_CURVE_SERIES, _CLAIMS_SERIES,
    )
    assert set(module.FRED_MACRO_SERIES) == {
        _CPI_SERIES, _UNRATE_SERIES, _YIELD_CURVE_SERIES, _CLAIMS_SERIES,
    }
