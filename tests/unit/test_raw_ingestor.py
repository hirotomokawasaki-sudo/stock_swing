"""Tests for RawIngestor."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from stock_swing.core.types import RawEnvelope
from stock_swing.ingestion.raw_ingestor import RawIngestor
from stock_swing.sources.base import SourceClient
from stock_swing.storage.stage_store import RawOverwriteError


class MockSourceClient(SourceClient):
    """Mock source client for testing."""
    
    name = "test_source"
    
    def fetch(self, **kwargs):
        return RawEnvelope(
            source=self.name,
            endpoint=kwargs.get("endpoint", "test"),
            fetched_at=datetime(2026, 3, 6, 14, 30, 15, 123456, tzinfo=timezone.utc),
            request_params=kwargs,
            payload={"data": "test"},
        )


def test_raw_ingestor_initialization(tmp_path: Path) -> None:
    """Test RawIngestor initialization."""
    ingestor = RawIngestor(tmp_path)
    
    assert ingestor.paths.project_root == tmp_path
    assert ingestor.store.allow_raw_overwrite is False


def test_raw_ingestor_with_overwrite_allowed(tmp_path: Path) -> None:
    """Test RawIngestor with overwrite allowed."""
    ingestor = RawIngestor(tmp_path, allow_raw_overwrite=True)
    
    assert ingestor.store.allow_raw_overwrite is True


def test_ingest_basic(tmp_path: Path) -> None:
    """Test basic ingestion flow."""
    ingestor = RawIngestor(tmp_path)
    client = MockSourceClient()
    
    result_path = ingestor.ingest(client, endpoint="test", symbol="AAPL")
    
    assert result_path.exists()
    assert result_path.parent.name == "test_source"
    assert result_path.parent.parent.name == "raw"
    assert "aapl" in result_path.name
    assert "2026-03-06" in result_path.name


def test_ingest_creates_source_subdirectory(tmp_path: Path) -> None:
    """Test that ingest creates source-specific subdirectories."""
    ingestor = RawIngestor(tmp_path)
    client = MockSourceClient()
    
    result_path = ingestor.ingest(client, symbol="AAPL")
    
    assert result_path.parent.name == "test_source"
    assert (tmp_path / "data" / "raw" / "test_source").exists()


def test_ingest_fails_on_duplicate_by_default(tmp_path: Path) -> None:
    """Test that ingest fails on duplicate raw file by default."""
    ingestor = RawIngestor(tmp_path)
    client = MockSourceClient()
    
    # First ingest succeeds
    ingestor.ingest(client, symbol="AAPL")
    
    # Second ingest with same data fails (same timestamp in mock)
    with pytest.raises(RawOverwriteError):
        ingestor.ingest(client, symbol="AAPL")


def test_ingest_allows_overwrite_when_configured(tmp_path: Path) -> None:
    """Test that ingest allows overwrite when configured."""
    ingestor = RawIngestor(tmp_path, allow_raw_overwrite=True)
    client = MockSourceClient()
    
    # Both ingests succeed
    path1 = ingestor.ingest(client, symbol="AAPL")
    path2 = ingestor.ingest(client, symbol="AAPL")
    
    assert path1 == path2


def test_build_filename_with_symbol(tmp_path: Path) -> None:
    """Test filename building with symbol."""
    ingestor = RawIngestor(tmp_path)
    
    envelope = RawEnvelope(
        source="finnhub",
        endpoint="stock/metric",
        fetched_at=datetime(2026, 3, 6, 14, 30, 15, 123456, tzinfo=timezone.utc),
        request_params={},
        payload={},
    )
    
    filename = ingestor._build_filename("finnhub", envelope, {"symbol": "AAPL"})
    
    assert filename == "finnhub_aapl_2026-03-06_143015123456.json"


def test_build_filename_with_series_id(tmp_path: Path) -> None:
    """Test filename building with series_id."""
    ingestor = RawIngestor(tmp_path)
    
    envelope = RawEnvelope(
        source="fred",
        endpoint="series/observations",
        fetched_at=datetime(2026, 3, 6, 14, 30, 15, 123456, tzinfo=timezone.utc),
        request_params={},
        payload={},
    )
    
    filename = ingestor._build_filename("fred", envelope, {"series_id": "CPIAUCSL"})
    
    assert filename == "fred_cpiaucsl_2026-03-06_143015123456.json"


def test_build_filename_with_cik(tmp_path: Path) -> None:
    """Test filename building with CIK."""
    ingestor = RawIngestor(tmp_path)
    
    envelope = RawEnvelope(
        source="sec",
        endpoint="submissions/CIK0000320193.json",
        fetched_at=datetime(2026, 3, 6, 14, 30, 15, 123456, tzinfo=timezone.utc),
        request_params={},
        payload={},
    )
    
    filename = ingestor._build_filename("sec", envelope, {"cik": "0000320193"})
    
    assert filename == "sec_0000320193_2026-03-06_143015123456.json"


def test_build_filename_normalizes_special_chars(tmp_path: Path) -> None:
    """Test filename normalization of special characters."""
    ingestor = RawIngestor(tmp_path)
    
    envelope = RawEnvelope(
        source="test",
        endpoint="test",
        fetched_at=datetime(2026, 3, 6, 14, 30, 15, 123456, tzinfo=timezone.utc),
        request_params={},
        payload={},
    )
    
    # Symbol with special chars
    filename = ingestor._build_filename("test", envelope, {"symbol": "BRK/A"})
    
    assert filename == "test_brk_a_2026-03-06_143015123456.json"
    assert "/" not in filename


def test_build_filename_fallback_to_data(tmp_path: Path) -> None:
    """Test filename building falls back to 'data' when no identifier."""
    ingestor = RawIngestor(tmp_path)
    
    envelope = RawEnvelope(
        source="test",
        endpoint="test",
        fetched_at=datetime(2026, 3, 6, 14, 30, 15, 123456, tzinfo=timezone.utc),
        request_params={},
        payload={},
    )
    
    filename = ingestor._build_filename("test", envelope, {})
    
    assert filename == "test_data_2026-03-06_143015123456.json"


def test_ingest_finnhub_with_symbol(tmp_path: Path) -> None:
    """Test Finnhub ingestion with symbol."""
    from stock_swing.sources.finnhub_client import FinnhubClient
    
    ingestor = RawIngestor(tmp_path)
    
    # Mock client
    client = Mock(spec=FinnhubClient)
    client.name = "finnhub"
    client.fetch.return_value = RawEnvelope(
        source="finnhub",
        endpoint="stock/metric",
        fetched_at=datetime.now(timezone.utc),
        request_params={"symbol": "AAPL"},
        payload={"metric": {"eps": 6.15}},
    )
    
    result_path = ingestor.ingest_finnhub(client, endpoint="stock/metric", symbol="AAPL")
    
    assert result_path.exists()
    assert "finnhub" in str(result_path)
    assert "aapl" in result_path.name


def test_ingest_fred_with_series_id(tmp_path: Path) -> None:
    """Test FRED ingestion with series_id."""
    from stock_swing.sources.fred_client import FredClient
    
    ingestor = RawIngestor(tmp_path)
    
    # Mock client
    client = Mock(spec=FredClient)
    client.name = "fred"
    client.fetch.return_value = RawEnvelope(
        source="fred",
        endpoint="series/observations",
        fetched_at=datetime.now(timezone.utc),
        request_params={"series_id": "CPIAUCSL"},
        payload={"observations": []},
    )
    
    result_path = ingestor.ingest_fred(client, series_id="CPIAUCSL")
    
    assert result_path.exists()
    assert "fred" in str(result_path)
    assert "cpiaucsl" in result_path.name


def test_ingest_sec_submissions(tmp_path: Path) -> None:
    """Test SEC submissions ingestion."""
    from stock_swing.sources.sec_client import SecClient
    
    ingestor = RawIngestor(tmp_path)
    
    # Mock client
    client = Mock(spec=SecClient)
    client.name = "sec"
    client.fetch_company_submissions.return_value = RawEnvelope(
        source="sec",
        endpoint="submissions/CIK0000320193.json",
        fetched_at=datetime.now(timezone.utc),
        request_params={"cik": "0000320193"},
        payload={"cik": "320193", "name": "Apple Inc."},
    )
    
    result_path = ingestor.ingest_sec(client, cik="0000320193")
    
    assert result_path.exists()
    assert "sec" in str(result_path)
    assert "0000320193" in result_path.name


def test_ingest_broker_bars(tmp_path: Path) -> None:
    """Test broker bars ingestion."""
    from stock_swing.sources.broker_client import BrokerClient
    
    ingestor = RawIngestor(tmp_path)
    
    # Mock client
    client = Mock(spec=BrokerClient)
    client.name = "broker"
    client.fetch_bars.return_value = RawEnvelope(
        source="broker",
        endpoint="v2/stocks/AAPL/bars",
        fetched_at=datetime.now(timezone.utc),
        request_params={"symbol": "AAPL", "timeframe": "1Min"},
        payload={"bars": []},
    )
    
    result_path = ingestor.ingest_broker_bars(client, symbol="AAPL")
    
    assert result_path.exists()
    assert "broker" in str(result_path)
    assert "aapl" in result_path.name


def test_ingest_broker_account(tmp_path: Path) -> None:
    """Test broker account ingestion."""
    from stock_swing.sources.broker_client import BrokerClient
    
    ingestor = RawIngestor(tmp_path)
    
    # Mock client
    client = Mock(spec=BrokerClient)
    client.name = "broker"
    client.fetch_account.return_value = RawEnvelope(
        source="broker",
        endpoint="v2/account",
        fetched_at=datetime.now(timezone.utc),
        request_params={},
        payload={"status": "ACTIVE"},
    )
    
    result_path = ingestor.ingest_broker_account(client)
    
    assert result_path.exists()
    assert "broker" in str(result_path)
    assert "account" in result_path.name
