"""Integration tests for raw ingestion with source clients."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from stock_swing.core.types import RawEnvelope
from stock_swing.ingestion.raw_ingestor import RawIngestor


@patch("httpx.Client")
def test_finnhub_ingestion_end_to_end(mock_client_class: Mock, tmp_path: Path) -> None:
    """Test end-to-end Finnhub ingestion."""
    from stock_swing.sources.finnhub_client import FinnhubClient
    
    # Mock HTTP response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "metric": {"eps": 6.15, "pe": 28.5}
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    # Ingest
    ingestor = RawIngestor(tmp_path)
    client = FinnhubClient(api_key="test_key")
    
    result_path = ingestor.ingest_finnhub(
        client,
        endpoint="stock/metric",
        symbol="AAPL",
    )
    
    # Verify file written
    assert result_path.exists()
    assert result_path.parent.name == "finnhub"
    assert "aapl" in result_path.name
    
    # Verify content
    import json
    content = json.loads(result_path.read_text())
    assert content["source"] == "finnhub"
    assert content["payload"]["metric"]["eps"] == 6.15


@patch("httpx.Client")
def test_fred_ingestion_end_to_end(mock_client_class: Mock, tmp_path: Path) -> None:
    """Test end-to-end FRED ingestion."""
    from stock_swing.sources.fred_client import FredClient
    
    # Mock HTTP response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "observations": [
            {"date": "2026-01-01", "value": "319.082"}
        ]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    # Ingest
    ingestor = RawIngestor(tmp_path)
    client = FredClient(api_key="test_key")
    
    result_path = ingestor.ingest_fred(
        client,
        series_id="CPIAUCSL",
        observation_start="2026-01-01",
    )
    
    # Verify file written
    assert result_path.exists()
    assert result_path.parent.name == "fred"
    assert "cpiaucsl" in result_path.name
    
    # Verify content
    import json
    content = json.loads(result_path.read_text())
    assert content["source"] == "fred"
    assert len(content["payload"]["observations"]) > 0


@patch("httpx.Client")
def test_sec_ingestion_end_to_end(mock_client_class: Mock, tmp_path: Path) -> None:
    """Test end-to-end SEC ingestion."""
    from stock_swing.sources.sec_client import SecClient
    
    # Mock HTTP response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "cik": "320193",
        "name": "Apple Inc.",
        "filings": {"recent": {}}
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    # Ingest
    ingestor = RawIngestor(tmp_path)
    client = SecClient(user_agent="Test test@example.com")
    
    result_path = ingestor.ingest_sec(
        client,
        cik="320193",
        endpoint_type="submissions",
    )
    
    # Verify file written
    assert result_path.exists()
    assert result_path.parent.name == "sec"
    assert "0000320193" in result_path.name
    
    # Verify content
    import json
    content = json.loads(result_path.read_text())
    assert content["source"] == "sec"
    assert content["payload"]["name"] == "Apple Inc."


@patch("httpx.Client")
def test_broker_ingestion_end_to_end(mock_client_class: Mock, tmp_path: Path) -> None:
    """Test end-to-end Broker ingestion."""
    from stock_swing.sources.broker_client import BrokerClient
    
    # Mock HTTP response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "bars": [
            {"t": "2026-03-06T09:30:00Z", "o": 183.12, "c": 183.31}
        ]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    # Ingest
    ingestor = RawIngestor(tmp_path)
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    
    result_path = ingestor.ingest_broker_bars(
        client,
        symbol="AAPL",
        timeframe="1Min",
    )
    
    # Verify file written
    assert result_path.exists()
    assert result_path.parent.name == "broker"
    assert "aapl" in result_path.name
    
    # Verify content
    import json
    content = json.loads(result_path.read_text())
    assert content["source"] == "broker"
    assert len(content["payload"]["bars"]) > 0


def test_multiple_source_ingestion(tmp_path: Path) -> None:
    """Test ingesting from multiple sources creates correct directory structure."""
    from stock_swing.sources.base import SourceClient
    from stock_swing.core.types import RawEnvelope
    
    class MockClient(SourceClient):
        def fetch(self, **kwargs):
            return RawEnvelope(
                source=self.name,
                endpoint="test",
                fetched_at=datetime.now(timezone.utc),
                request_params=kwargs,
                payload={"test": "data"},
            )
    
    ingestor = RawIngestor(tmp_path)
    
    # Ingest from different sources
    client1 = MockClient()
    client1.name = "source1"
    
    client2 = MockClient()
    client2.name = "source2"
    
    path1 = ingestor.ingest(client1, symbol="TEST1")
    path2 = ingestor.ingest(client2, symbol="TEST2")
    
    # Verify separate source directories
    assert path1.parent.name == "source1"
    assert path2.parent.name == "source2"
    assert path1.parent != path2.parent
    
    # Both under data/raw/
    assert path1.parent.parent.name == "raw"
    assert path2.parent.parent.name == "raw"
