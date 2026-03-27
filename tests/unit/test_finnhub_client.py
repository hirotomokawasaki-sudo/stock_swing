"""Tests for Finnhub client implementation."""

from unittest.mock import Mock, patch

import pytest

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
from stock_swing.sources.finnhub_client import FinnhubClient


# Skip tests if httpx is not installed
pytest.importorskip("httpx")


def test_finnhub_client_requires_api_key() -> None:
    """Test that FinnhubClient requires an API key."""
    with pytest.raises(ValueError, match="api_key is required"):
        FinnhubClient(api_key="")


def test_finnhub_client_initialization() -> None:
    """Test FinnhubClient initialization."""
    client = FinnhubClient(api_key="test_key")
    
    assert client.name == "finnhub"
    assert client.api_key == "test_key"
    assert client.base_url == "https://finnhub.io/api/v1"


@patch("httpx.Client")
def test_fetch_basic_financials_success(mock_client_class: Mock) -> None:
    """Test successful basic financials fetch."""
    # Mock response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "metric": {"eps": 6.15, "pe": 28.5},
        "series": {"annual": {}},
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    # Fetch
    client = FinnhubClient(api_key="test_key")
    envelope = client.fetch_basic_financials("AAPL")
    
    # Verify
    assert envelope.source == "finnhub"
    assert envelope.endpoint == "stock/metric"
    assert "symbol" in envelope.request_params
    assert envelope.request_params["symbol"] == "AAPL"
    assert "eps" in envelope.payload["metric"]


@patch("httpx.Client")
def test_fetch_earnings_calendar_success(mock_client_class: Mock) -> None:
    """Test successful earnings calendar fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "earningsCalendar": [
            {"date": "2026-04-01", "symbol": "AAPL", "epsEstimate": 1.5}
        ]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FinnhubClient(api_key="test_key")
    envelope = client.fetch_earnings_calendar(symbol="AAPL")
    
    assert envelope.endpoint == "calendar/earnings"
    assert "earningsCalendar" in envelope.payload


@patch("httpx.Client")
def test_fetch_insider_transactions_success(mock_client_class: Mock) -> None:
    """Test successful insider transactions fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "name": "Jane Doe",
                "share": 2500,
                "transactionCode": "P",
                "transactionPrice": 187.4,
            }
        ]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FinnhubClient(api_key="test_key")
    envelope = client.fetch_insider_transactions("AAPL")
    
    assert envelope.endpoint == "stock/insider-transactions"
    assert "data" in envelope.payload


@patch("httpx.Client")
def test_fetch_filing_sentiment_success(mock_client_class: Mock) -> None:
    """Test successful filing sentiment fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "sentiment": {"score": 0.75, "positive": 120, "negative": 30}
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FinnhubClient(api_key="test_key")
    envelope = client.fetch_filing_sentiment("0000320193-26-000012")
    
    assert envelope.endpoint == "stock/filings-sentiment"
    assert "sentiment" in envelope.payload


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
    
    client = FinnhubClient(api_key="invalid_key")
    
    with pytest.raises(SourceAuthenticationError, match="invalid or missing API key"):
        client.fetch_basic_financials("AAPL")


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
    
    client = FinnhubClient(api_key="test_key")
    
    with pytest.raises(SourceAuthenticationError, match="does not have permission"):
        client.fetch_basic_financials("AAPL")


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
    
    client = FinnhubClient(api_key="test_key")
    
    with pytest.raises(SourceNotFoundError, match="resource not found"):
        client.fetch_basic_financials("INVALID")


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
    
    client = FinnhubClient(api_key="test_key")
    
    with pytest.raises(SourceRateLimitError) as exc_info:
        client.fetch_basic_financials("AAPL")
    
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
    
    client = FinnhubClient(api_key="test_key")
    
    with pytest.raises(SourceServerError, match="server error: 500"):
        client.fetch_basic_financials("AAPL")


@patch("httpx.Client")
def test_fetch_timeout_error(mock_client_class: Mock) -> None:
    """Test timeout error handling."""
    import httpx
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = httpx.TimeoutException("timeout")
    mock_client_class.return_value = mock_client
    
    client = FinnhubClient(api_key="test_key")
    
    with pytest.raises(SourceTimeoutError, match="request timeout"):
        client.fetch_basic_financials("AAPL")


@patch("httpx.Client")
def test_fetch_connection_error(mock_client_class: Mock) -> None:
    """Test connection error handling."""
    import httpx
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = httpx.ConnectError("connection failed")
    mock_client_class.return_value = mock_client
    
    client = FinnhubClient(api_key="test_key")
    
    with pytest.raises(SourceConnectionError, match="connection failed"):
        client.fetch_basic_financials("AAPL")


@patch("httpx.Client")
def test_fetch_json_parse_error(mock_client_class: Mock) -> None:
    """Test JSON parsing error handling."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("invalid JSON")
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FinnhubClient(api_key="test_key")
    
    with pytest.raises(SourceResponseError, match="failed to parse JSON"):
        client.fetch_basic_financials("AAPL")


def test_fetch_missing_endpoint() -> None:
    """Test that fetch requires endpoint parameter."""
    client = FinnhubClient(api_key="test_key")
    
    with pytest.raises(SourceValidationError, match="endpoint parameter is required"):
        client.fetch(symbol="AAPL")
