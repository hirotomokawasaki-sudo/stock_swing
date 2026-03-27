"""Tests for Broker client implementation."""

from unittest.mock import Mock, patch

import pytest

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.errors import (
    SourceAuthenticationError,
    SourceConnectionError,
    SourceNotFoundError,
    SourceRateLimitError,
    SourceResponseError,
    SourceServerError,
    SourceTimeoutError,
    SourceValidationError,
)


pytest.importorskip("httpx")


def test_broker_client_requires_api_key() -> None:
    """Test that BrokerClient requires API key."""
    with pytest.raises(ValueError, match="api_key is required"):
        BrokerClient(api_key="", api_secret="secret")


def test_broker_client_requires_api_secret() -> None:
    """Test that BrokerClient requires API secret."""
    with pytest.raises(ValueError, match="api_secret is required"):
        BrokerClient(api_key="key", api_secret="")


def test_broker_client_blocks_live_mode() -> None:
    """Test that BrokerClient blocks live mode for safety."""
    with pytest.raises(ValueError, match="Live mode is NOT supported"):
        BrokerClient(api_key="key", api_secret="secret", paper_mode=False)


def test_broker_client_initialization_paper_mode() -> None:
    """Test BrokerClient initialization in paper mode."""
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    
    assert client.name == "broker"
    assert client.paper_mode is True
    assert client.base_url == client.base_url_paper


@patch("httpx.Client")
def test_fetch_bars_success(mock_client_class: Mock) -> None:
    """Test successful bars fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "bars": [
            {
                "t": "2026-03-06T09:30:00Z",
                "o": 183.12,
                "h": 183.45,
                "l": 182.91,
                "c": 183.31,
                "v": 1912200,
            }
        ]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    envelope = client.fetch_bars("AAPL", timeframe="1Min")
    
    assert envelope.source == "broker"
    assert "AAPL" in envelope.endpoint
    assert "bars" in envelope.payload


@patch("httpx.Client")
def test_fetch_latest_quote_success(mock_client_class: Mock) -> None:
    """Test successful latest quote fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "quote": {
            "t": "2026-03-06T09:30:00Z",
            "bp": 183.25,
            "ap": 183.30,
            "bs": 100,
            "as": 100,
        }
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    envelope = client.fetch_latest_quote("AAPL")
    
    assert envelope.endpoint.endswith("quotes/latest")
    assert "quote" in envelope.payload


@patch("httpx.Client")
def test_fetch_account_success(mock_client_class: Mock) -> None:
    """Test successful account fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "account-123",
        "account_number": "PA123456789",
        "status": "ACTIVE",
        "buying_power": "100000.00",
        "equity": "100000.00",
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    envelope = client.fetch_account()
    
    assert envelope.endpoint == "v2/account"
    assert envelope.payload["status"] == "ACTIVE"


@patch("httpx.Client")
def test_fetch_positions_success(mock_client_class: Mock) -> None:
    """Test successful positions fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "symbol": "AAPL",
            "qty": "10",
            "market_value": "1833.10",
            "avg_entry_price": "180.00",
        }
    ]
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    envelope = client.fetch_positions()
    
    assert envelope.endpoint == "v2/positions"
    assert len(envelope.payload) > 0


@patch("httpx.Client")
def test_fetch_orders_success(mock_client_class: Mock) -> None:
    """Test successful orders fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "id": "order-123",
            "symbol": "AAPL",
            "side": "buy",
            "qty": "10",
            "status": "filled",
        }
    ]
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    envelope = client.fetch_orders(status="all")
    
    assert envelope.endpoint == "v2/orders"
    assert len(envelope.payload) > 0


@patch("httpx.Client")
def test_fetch_authentication_error(mock_client_class: Mock) -> None:
    """Test authentication error handling (401)."""
    mock_response = Mock()
    mock_response.status_code = 401
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="invalid_key", api_secret="invalid_secret")
    
    with pytest.raises(SourceAuthenticationError, match="invalid API credentials"):
        client.fetch_account()


@patch("httpx.Client")
def test_fetch_permission_error(mock_client_class: Mock) -> None:
    """Test permission error handling (403)."""
    mock_response = Mock()
    mock_response.status_code = 403
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    
    with pytest.raises(SourceAuthenticationError, match="does not have permission"):
        client.fetch_account()


@patch("httpx.Client")
def test_fetch_not_found_error(mock_client_class: Mock) -> None:
    """Test not found error handling (404)."""
    mock_response = Mock()
    mock_response.status_code = 404
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    
    with pytest.raises(SourceNotFoundError, match="resource not found"):
        client.fetch_position("INVALID")


@patch("httpx.Client")
def test_fetch_validation_error(mock_client_class: Mock) -> None:
    """Test validation error handling (422)."""
    mock_response = Mock()
    mock_response.status_code = 422
    mock_response.json.return_value = {"message": "invalid symbol"}
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    
    with pytest.raises(SourceValidationError, match="invalid symbol"):
        client.fetch_bars("INVALID")


@patch("httpx.Client")
def test_fetch_rate_limit_error(mock_client_class: Mock) -> None:
    """Test rate limit error handling (429)."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "60"}
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    
    with pytest.raises(SourceRateLimitError) as exc_info:
        client.fetch_account()
    
    assert exc_info.value.retry_after == 60


@patch("httpx.Client")
def test_fetch_server_error(mock_client_class: Mock) -> None:
    """Test server error handling (5xx)."""
    mock_response = Mock()
    mock_response.status_code = 500
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    
    with pytest.raises(SourceServerError, match="server error: 500"):
        client.fetch_account()


@patch("httpx.Client")
def test_fetch_timeout_error(mock_client_class: Mock) -> None:
    """Test timeout error handling."""
    import httpx
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = httpx.TimeoutException("timeout")
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    
    with pytest.raises(SourceTimeoutError, match="request timeout"):
        client.fetch_account()


@patch("httpx.Client")
def test_fetch_connection_error(mock_client_class: Mock) -> None:
    """Test connection error handling."""
    import httpx
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = httpx.ConnectError("connection failed")
    mock_client_class.return_value = mock_client
    
    client = BrokerClient(api_key="test_key", api_secret="test_secret")
    
    with pytest.raises(SourceConnectionError, match="connection failed"):
        client.fetch_account()
