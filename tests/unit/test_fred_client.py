"""Tests for FRED client implementation."""

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
from stock_swing.sources.fred_client import FredClient


pytest.importorskip("httpx")


def test_fred_client_requires_api_key() -> None:
    """Test that FredClient requires an API key."""
    with pytest.raises(ValueError, match="api_key is required"):
        FredClient(api_key="")


def test_fred_client_initialization() -> None:
    """Test FredClient initialization."""
    client = FredClient(api_key="test_key")
    
    assert client.name == "fred"
    assert client.api_key == "test_key"
    assert client.base_url == "https://api.stlouisfed.org/fred"


@patch("httpx.Client")
def test_fetch_series_observations_success(mock_client_class: Mock) -> None:
    """Test successful series observations fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "observations": [
            {"date": "2026-01-01", "value": "319.082"},
            {"date": "2026-02-01", "value": "319.456"},
        ]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="test_key")
    envelope = client.fetch_series_observations("CPIAUCSL")
    
    assert envelope.source == "fred"
    assert envelope.endpoint == "series/observations"
    assert "series_id" in envelope.request_params
    assert envelope.request_params["series_id"] == "CPIAUCSL"
    assert "observations" in envelope.payload


@patch("httpx.Client")
def test_fetch_series_observations_with_dates(mock_client_class: Mock) -> None:
    """Test series observations fetch with date filtering."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"observations": []}
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="test_key")
    envelope = client.fetch_series_observations(
        "GDP",
        observation_start="2025-01-01",
        observation_end="2026-01-01",
        limit=100,
    )
    
    assert envelope.request_params["observation_start"] == "2025-01-01"
    assert envelope.request_params["observation_end"] == "2026-01-01"
    assert envelope.request_params["limit"] == 100


@patch("httpx.Client")
def test_fetch_series_info_success(mock_client_class: Mock) -> None:
    """Test successful series info fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "seriess": [
            {
                "id": "CPIAUCSL",
                "title": "Consumer Price Index for All Urban Consumers",
                "units": "Index 1982-1984=100",
                "frequency": "Monthly",
            }
        ]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="test_key")
    envelope = client.fetch_series_info("CPIAUCSL")
    
    assert envelope.endpoint == "series"
    assert "seriess" in envelope.payload


@patch("httpx.Client")
def test_fetch_series_search_success(mock_client_class: Mock) -> None:
    """Test successful series search."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "seriess": [
            {"id": "CPIAUCSL", "title": "Consumer Price Index"},
            {"id": "CPILFESL", "title": "CPI Less Food and Energy"},
        ]
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="test_key")
    envelope = client.fetch_series_search("inflation")
    
    assert envelope.endpoint == "series/search"
    assert envelope.request_params["search_text"] == "inflation"


@patch("httpx.Client")
def test_fetch_authentication_error_via_400(mock_client_class: Mock) -> None:
    """Test authentication error via 400 status with api_key message."""
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error_message": "Invalid api_key provided"
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="invalid_key")
    
    with pytest.raises(SourceAuthenticationError, match="API key error"):
        client.fetch_series_observations("CPIAUCSL")


@patch("httpx.Client")
def test_fetch_not_found_error_via_400(mock_client_class: Mock) -> None:
    """Test not found error via 400 status with not found message."""
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error_message": "Series not found"
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="test_key")
    
    with pytest.raises(SourceNotFoundError, match="Series not found"):
        client.fetch_series_observations("INVALID")


@patch("httpx.Client")
def test_fetch_validation_error_via_400(mock_client_class: Mock) -> None:
    """Test validation error via 400 status."""
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error_message": "Missing required parameter"
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="test_key")
    
    with pytest.raises(SourceValidationError, match="Missing required parameter"):
        client.fetch_series_observations("CPIAUCSL")


@patch("httpx.Client")
def test_fetch_error_in_200_response(mock_client_class: Mock) -> None:
    """Test FRED error wrapped in 200 response."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "error_code": 400,
        "error_message": "Invalid series_id"
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="test_key")
    
    with pytest.raises(SourceValidationError, match="Invalid series_id"):
        client.fetch_series_observations("INVALID")


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
    
    client = FredClient(api_key="test_key")
    
    with pytest.raises(SourceRateLimitError) as exc_info:
        client.fetch_series_observations("CPIAUCSL")
    
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
    
    client = FredClient(api_key="test_key")
    
    with pytest.raises(SourceServerError, match="server error: 500"):
        client.fetch_series_observations("CPIAUCSL")


@patch("httpx.Client")
def test_fetch_timeout_error(mock_client_class: Mock) -> None:
    """Test timeout error handling."""
    import httpx
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = httpx.TimeoutException("timeout")
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="test_key")
    
    with pytest.raises(SourceTimeoutError, match="request timeout"):
        client.fetch_series_observations("CPIAUCSL")


@patch("httpx.Client")
def test_fetch_connection_error(mock_client_class: Mock) -> None:
    """Test connection error handling."""
    import httpx
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = httpx.ConnectError("connection failed")
    mock_client_class.return_value = mock_client
    
    client = FredClient(api_key="test_key")
    
    with pytest.raises(SourceConnectionError, match="connection failed"):
        client.fetch_series_observations("CPIAUCSL")


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
    
    client = FredClient(api_key="test_key")
    
    with pytest.raises(SourceResponseError, match="failed to parse JSON"):
        client.fetch_series_observations("CPIAUCSL")
