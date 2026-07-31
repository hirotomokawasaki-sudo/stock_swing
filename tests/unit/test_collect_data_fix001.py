"""FIX-001: Production data separation regression tests.

Ensures collect_data.py never writes synthetic records on the production path.
"""

from __future__ import annotations

import json
from pathlib import Path

from stock_swing.core.path_manager import PathManager
from stock_swing.storage.stage_store import StageStore


def _make_store(tmp_path):
    return StageStore(PathManager(tmp_path))


def test_collect_finnhub_no_synthetic_metric_without_client(tmp_path, monkeypatch):
    """Without an API client, metric snapshots must not fall back to synthetic payloads."""
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    written, timed_out = module.collect_finnhub(["AAPL"], _make_store(tmp_path))

    assert timed_out is False
    assert written == []
    metric_files = list((tmp_path / "data" / "raw" / "finnhub").glob("*metric*.json"))
    assert metric_files == [], f"Synthetic metric snapshots must not be written: {metric_files}"


def test_collect_finnhub_no_synthetic_news_fallback(tmp_path, monkeypatch):
    """News fetch failures must not generate synthetic news rows."""
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    module.collect_finnhub(["MSFT"], _make_store(tmp_path))

    raw_files = list((tmp_path / "data" / "raw").rglob("*.json"))
    for raw_file in raw_files:
        data = json.loads(raw_file.read_text(encoding="utf-8"))
        payload = data.get("payload", {})
        news = payload.get("news") if isinstance(payload, dict) else None
        if isinstance(news, list):
            for item in news:
                assert item.get("source") != "synthetic", f"Synthetic news found in {raw_file.name}"
                assert "example.local" not in item.get("url", ""), f"Synthetic URL found in {raw_file.name}"


def test_collect_fred_returns_empty_no_write(tmp_path, monkeypatch):
    """collect_fred should record status only and write no raw CPI payload."""
    from stock_swing.cli import collect_data as module

    monkeypatch.setattr(module, "project_root", tmp_path)
    written = module.collect_fred(_make_store(tmp_path))

    assert written == []
    raw_files = list((tmp_path / "data" / "raw").rglob("*.json"))
    assert raw_files == [], f"collect_fred should not write raw snapshots: {raw_files}"


def test_collect_sec_returns_empty_no_write(tmp_path, monkeypatch):
    """collect_sec should return [] and avoid hash-generated synthetic SEC data."""
    from stock_swing.cli import collect_data as module

    monkeypatch.setattr(module, "project_root", tmp_path)
    written = module.collect_sec(["AAPL", "MSFT"], _make_store(tmp_path))

    assert written == []
    raw_files = list((tmp_path / "data" / "raw").rglob("*.json"))
    assert raw_files == []


def test_collect_broker_returns_empty_without_credentials(tmp_path, monkeypatch):
    """collect_broker without BROKER_API_KEY/SECRET must write no snapshots.

    2026-08-01: collect_broker() was reimplemented to actually call the
    broker API (previously a permanent 'not_implemented' stub). This test
    locks in the fail-safe path: missing credentials must not attempt any
    network call and must return written=[] with a 'failed' status file.
    """
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.delenv("BROKER_API_KEY", raising=False)
    monkeypatch.delenv("BROKER_API_SECRET", raising=False)
    written = module.collect_broker(["AAPL"], _make_store(tmp_path))

    assert written == []
    status_path = tmp_path / "data" / "audits" / "broker_quotes_status.json"
    assert status_path.exists()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"


def test_collect_broker_bars_returns_empty_without_credentials(tmp_path, monkeypatch):
    """collect_broker_bars without credentials must write no snapshots (fail-safe)."""
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.delenv("BROKER_API_KEY", raising=False)
    monkeypatch.delenv("BROKER_API_SECRET", raising=False)
    written = module.collect_broker_bars(["AAPL"], _make_store(tmp_path))

    assert written == []
    status_path = tmp_path / "data" / "audits" / "broker_bars_status.json"
    assert status_path.exists()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"


def test_collect_broker_writes_real_snapshots_with_mocked_client(tmp_path, monkeypatch):
    """collect_broker with a working client must write account/positions/quote snapshots.

    2026-08-01: regression guard for the real implementation (previously a
    stub that always returned []). Uses a mocked BrokerClient so this test
    never makes a live network call.
    """
    from types import SimpleNamespace
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.setenv("BROKER_API_KEY", "test_key")
    monkeypatch.setenv("BROKER_API_SECRET", "test_secret")
    monkeypatch.setenv("BROKER_BASE_URL", "https://paper-api.alpaca.markets/v2")

    class _FakeBrokerClient:
        def __init__(self, **kwargs):
            pass

        def fetch_account(self):
            return SimpleNamespace(payload={"equity": "100000", "status": "ACTIVE"})

        def fetch_positions(self):
            return SimpleNamespace(payload=[{"symbol": "AAPL", "qty": "10"}])

        def fetch_latest_quote(self, symbol):
            return SimpleNamespace(payload={"symbol": symbol, "quote": {"bp": 100.0, "ap": 100.2}})

    monkeypatch.setattr("stock_swing.sources.broker_client.BrokerClient", _FakeBrokerClient)

    written = module.collect_broker(["AAPL", "MSFT"], _make_store(tmp_path))

    assert len(written) == 4, f"expected account+positions+2 quotes, got: {written}"
    status_path = tmp_path / "data" / "audits" / "broker_quotes_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "ok"
    assert status["symbols_ok"] == 2
    assert status["symbols_failed"] == []


def test_write_raw_snapshot_is_synthetic_false_by_default(tmp_path):
    """_write_raw_snapshot must stamp is_synthetic=False on production snapshots."""
    from stock_swing.cli.collect_data import _write_raw_snapshot

    store = _make_store(tmp_path)
    path = _write_raw_snapshot(store, "finnhub", "AAPL", "stock/metric", {"test": 1})
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    assert data.get("is_synthetic") is False
    assert data.get("quality_status") == "ok"
    assert data.get("ingested_at")
    assert data.get("source_id")


def test_write_raw_snapshot_has_envelope_fields(tmp_path):
    """_write_raw_snapshot must include lineage and quality envelope fields."""
    from stock_swing.cli.collect_data import _write_raw_snapshot

    store = _make_store(tmp_path)
    path = _write_raw_snapshot(store, "test", "TEST", "test/endpoint", {"v": 1})
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    required_fields = [
        "event_time",
        "available_at",
        "ingested_at",
        "source_id",
        "revision_id",
        "quality_status",
        "is_synthetic",
    ]
    for field in required_fields:
        assert field in data, f"Missing envelope field: {field}"
