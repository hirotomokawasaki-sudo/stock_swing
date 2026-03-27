"""Integration tests for Broker client with retry logic."""

from unittest.mock import Mock, patch

import pytest

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.errors import SourceConnectionError
from stock_swing.sources.retry import RetryConfig


pytest.importorskip("httpx")


@patch("httpx.Client")
def test_broker_retry_on_connection_error(mock_client_class: Mock) -> None:
    """Test that Broker client retries on transient connection errors."""
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
            "id": "account-123",
            "status": "ACTIVE",
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
    
    client = BrokerClient(
        api_key="test_key",
        api_secret="test_secret",
        retry_config=retry_config,
    )
    envelope = client.fetch_account()
    
    assert envelope.payload["status"] == "ACTIVE"
    assert call_count == 2


@patch("httpx.Client")
def test_broker_fails_after_max_retries(mock_client_class: Mock) -> None:
    """Test that Broker client fails after exhausting retries."""
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
    
    client = BrokerClient(
        api_key="test_key",
        api_secret="test_secret",
        retry_config=retry_config,
    )
    
    with pytest.raises(SourceConnectionError):
        client.fetch_account()
    
    assert call_count == 3


@patch("httpx.Client")
def test_broker_multiple_endpoint_calls(mock_client_class: Mock) -> None:
    """Test calling multiple Broker endpoints in sequence."""
    
    def get_side_effect(url: str, headers: dict, **kwargs):
        mock_response = Mock()
        mock_response.status_code = 200
        
        if "account" in url:
            mock_response.json.return_value = {"status": "ACTIVE"}
        elif "positions" in url:
            mock_response.json.return_value = []
        elif "orders" in url:
            mock_response.json.return_value = []
        elif "bars" in url:
            mock_response.json.return_value = {"bars": []}
        else:
            mock_response.json.return_value = {}
        
        return mock_response
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = get_side_effect
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    
    # Fetch multiple endpoints
    env1 = client.fetch_account()
    env2 = client.fetch_positions()
    env3 = client.fetch_orders()
    env4 = client.fetch_bars("AAPL")
    
    assert env1.endpoint == "v2/account"
    assert env2.endpoint == "v2/positions"
    assert env3.endpoint == "v2/orders"
    assert "AAPL" in env4.endpoint
