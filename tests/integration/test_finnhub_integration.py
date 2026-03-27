"""Integration tests for Finnhub client with retry logic."""

from unittest.mock import Mock, patch

import pytest

from stock_swing.sources.errors import SourceConnectionError
from stock_swing.sources.finnhub_client import FinnhubClient
from stock_swing.sources.retry import RetryConfig


pytest.importorskip("httpx")


@patch("httpx.Client")
def test_finnhub_retry_on_connection_error(mock_client_class: Mock) -> None:
    """Test that Finnhub client retries on transient connection errors."""
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
        mock_response.json.return_value = {"metric": {"eps": 6.15}}
        return mock_response
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = side_effect
    mock_client_class.return_value = mock_client
    
    # Configure with fast retry for testing
    retry_config = RetryConfig(
        max_attempts=3,
        initial_delay=0.01,
        backoff_factor=1.0,
    )
    
    client = FinnhubClient(api_key="test_key", retry_config=retry_config)
    envelope = client.fetch_basic_financials("AAPL")
    
    # Should succeed after retry
    assert envelope.payload["metric"]["eps"] == 6.15
    assert call_count == 2


@patch("httpx.Client")
def test_finnhub_fails_after_max_retries(mock_client_class: Mock) -> None:
    """Test that Finnhub client fails after exhausting retries."""
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
    
    client = FinnhubClient(api_key="test_key", retry_config=retry_config)
    
    with pytest.raises(SourceConnectionError):
        client.fetch_basic_financials("AAPL")
    
    # Should have attempted 3 times
    assert call_count == 3


@patch("httpx.Client")
def test_finnhub_multiple_endpoint_calls(mock_client_class: Mock) -> None:
    """Test calling multiple Finnhub endpoints in sequence."""
    
    def get_side_effect(url: str, params: dict):
        mock_response = Mock()
        mock_response.status_code = 200
        
        if "stock/metric" in url:
            mock_response.json.return_value = {"metric": {"eps": 6.15}}
        elif "calendar/earnings" in url:
            mock_response.json.return_value = {"earningsCalendar": []}
        elif "insider-transactions" in url:
            mock_response.json.return_value = {"data": []}
        else:
            mock_response.json.return_value = {}
        
        return mock_response
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = get_side_effect
    mock_client_class.return_value = mock_client
    
    client = FinnhubClient(api_key="test_key")
    
    # Fetch multiple endpoints
    env1 = client.fetch_basic_financials("AAPL")
    env2 = client.fetch_earnings_calendar(symbol="AAPL")
    env3 = client.fetch_insider_transactions("AAPL")
    
    # Verify all succeeded
    assert env1.endpoint == "stock/metric"
    assert env2.endpoint == "calendar/earnings"
    assert env3.endpoint == "stock/insider-transactions"
