"""Integration tests for FRED client with retry logic."""

from unittest.mock import Mock, patch

import pytest

from stock_swing.sources.errors import SourceConnectionError
from stock_swing.sources.fred_client import FredClient
from stock_swing.sources.retry import RetryConfig


pytest.importorskip("httpx")


@patch("httpx.Client")
def test_fred_retry_on_connection_error(mock_client_class: Mock) -> None:
    """Test that FRED client retries on transient connection errors."""
    import httpx
    
    call_count = 0
    
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise httpx.ConnectError("connection failed")
        
        # Success on second attempt
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "observations": [
                {"date": "2026-01-01", "value": "319.082"}
            ]
        }
        return mock_response
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = side_effect
    mock_client_class.return_value = mock_client
    
    retry_config = RetryConfig(
        max_attempts=3,
        initial_delay=0.01,
        backoff_factor=1.0,
    )
    
    client = FredClient(api_key="test_key", retry_config=retry_config)
    envelope = client.fetch_series_observations("CPIAUCSL")
    
    assert envelope.payload["observations"][0]["value"] == "319.082"
    assert call_count == 2


@patch("httpx.Client")
def test_fred_fails_after_max_retries(mock_client_class: Mock) -> None:
    """Test that FRED client fails after exhausting retries."""
    import httpx
    
    call_count = 0
    
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection failed")
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = side_effect
    mock_client_class.return_value = mock_client
    
    retry_config = RetryConfig(
        max_attempts=3,
        initial_delay=0.01,
        backoff_factor=1.0,
    )
    
    client = FredClient(api_key="test_key", retry_config=retry_config)
    
    with pytest.raises(SourceConnectionError):
        client.fetch_series_observations("CPIAUCSL")
    
    assert call_count == 3


@patch("httpx.Client")
def test_fred_multiple_series_calls(mock_client_class: Mock) -> None:
    """Test calling multiple FRED series in sequence."""
    
    def get_side_effect(url: str, params: dict):
        mock_response = Mock()
        mock_response.status_code = 200
        
        if "series/observations" in url:
            series_id = params.get("series_id", "")
            mock_response.json.return_value = {
                "observations": [{"date": "2026-01-01", "value": "100.0"}]
            }
        elif "series/search" in url:
            mock_response.json.return_value = {"seriess": []}
        else:
            mock_response.json.return_value = {}
        
        return mock_response
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = get_side_effect
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="test_key")
    
    # Fetch multiple series
    env1 = client.fetch_series_observations("CPIAUCSL")
    env2 = client.fetch_series_observations("GDP")
    env3 = client.fetch_series_search("inflation")
    
    assert env1.endpoint == "series/observations"
    assert env2.endpoint == "series/observations"
    assert env3.endpoint == "series/search"
