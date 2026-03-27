"""Tests for SEC client implementation."""

from unittest.mock import Mock, patch

import pytest

from stock_swing.sources.errors import (
    SourceConnectionError,
    SourceNotFoundError,
    SourceRateLimitError,
    SourceResponseError,
    SourceServerError,
    SourceTimeoutError,
    SourceValidationError,
)
from stock_swing.sources.sec_client import SecClient


pytest.importorskip("httpx")


def test_sec_client_requires_user_agent() -> None:
    """Test that SecClient requires a User-Agent."""
    with pytest.raises(ValueError, match="user_agent is required"):
        SecClient(user_agent="")


def test_sec_client_initialization() -> None:
    """Test SecClient initialization."""
    client = SecClient(user_agent="Test Company test@example.com")
    
    assert client.name == "sec"
    assert client.user_agent == "Test Company test@example.com"
    assert client.base_url == "https://data.sec.gov"


def test_format_cik() -> None:
    """Test CIK formatting helper."""
    client = SecClient(user_agent="Test test@example.com")
    
    # Various input formats
    assert client._format_cik("320193") == "0000320193"
    assert client._format_cik("0000320193") == "0000320193"
    assert client._format_cik("CIK0000320193") == "0000320193"
    assert client._format_cik("1234567890") == "1234567890"


@patch("httpx.Client")
def test_fetch_company_submissions_success(mock_client_class: Mock) -> None:
    """Test successful company submissions fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "cik": "320193",
        "entityType": "operating",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000012"],
                "filingDate": ["2026-03-01"],
                "form": ["8-K"],
            }
        }
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = SecClient(user_agent="Test test@example.com")
    envelope = client.fetch_company_submissions("320193")
    
    assert envelope.source == "sec"
    assert "CIK0000320193.json" in envelope.endpoint
    assert envelope.payload["name"] == "Apple Inc."


@patch("httpx.Client")
def test_fetch_company_concept_success(mock_client_class: Mock) -> None:
    """Test successful company concept fetch."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "cik": "320193",
        "taxonomy": "us-gaap",
        "tag": "Revenue",
        "units": {
            "USD": [
                {"end": "2025-09-30", "val": 394328000000}
            ]
        }
    }
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = SecClient(user_agent="Test test@example.com")
    envelope = client.fetch_company_concept("320193", "us-gaap", "Revenue")
    
    assert envelope.endpoint.endswith("us-gaap/Revenue.json")
    assert envelope.payload["tag"] == "Revenue"


@patch("httpx.Client")
def test_fetch_user_agent_header_sent(mock_client_class: Mock) -> None:
    """Test that User-Agent header is included in requests."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = SecClient(user_agent="MyCompany contact@example.com")
    client.fetch_company_submissions("320193")
    
    # Verify User-Agent was sent
    call_args = mock_client.get.call_args
    assert "headers" in call_args.kwargs
    assert call_args.kwargs["headers"]["User-Agent"] == "MyCompany contact@example.com"


@patch("httpx.Client")
def test_fetch_missing_user_agent_error(mock_client_class: Mock) -> None:
    """Test 403 error for missing User-Agent."""
    mock_response = Mock()
    mock_response.status_code = 403
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = SecClient(user_agent="Test test@example.com")
    
    with pytest.raises(SourceValidationError, match="User-Agent"):
        client.fetch_company_submissions("320193")


@patch("httpx.Client")
def test_fetch_not_found_error(mock_client_class: Mock) -> None:
    """Test 404 error for non-existent CIK."""
    mock_response = Mock()
    mock_response.status_code = 404
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = SecClient(user_agent="Test test@example.com")
    
    with pytest.raises(SourceNotFoundError, match="resource not found"):
        client.fetch_company_submissions("9999999999")


@patch("httpx.Client")
def test_fetch_rate_limit_error(mock_client_class: Mock) -> None:
    """Test rate limit error handling (429)."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "10"}
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client
    
    client = SecClient(user_agent="Test test@example.com")
    
    with pytest.raises(SourceRateLimitError) as exc_info:
        client.fetch_company_submissions("320193")
    
    assert exc_info.value.retry_after == 10
    assert "10 requests/second" in str(exc_info.value)


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
    
    client = SecClient(user_agent="Test test@example.com")
    
    with pytest.raises(SourceServerError, match="server error: 500"):
        client.fetch_company_submissions("320193")


@patch("httpx.Client")
def test_fetch_timeout_error(mock_client_class: Mock) -> None:
    """Test timeout error handling."""
    import httpx
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = httpx.TimeoutException("timeout")
    mock_client_class.return_value = mock_client
    
    client = SecClient(user_agent="Test test@example.com")
    
    with pytest.raises(SourceTimeoutError, match="request timeout"):
        client.fetch_company_submissions("320193")


@patch("httpx.Client")
def test_fetch_connection_error(mock_client_class: Mock) -> None:
    """Test connection error handling."""
    import httpx
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = httpx.ConnectError("connection failed")
    mock_client_class.return_value = mock_client
    
    client = SecClient(user_agent="Test test@example.com")
    
    with pytest.raises(SourceConnectionError, match="connection failed"):
        client.fetch_company_submissions("320193")


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
    
    client = SecClient(user_agent="Test test@example.com")
    
    with pytest.raises(SourceResponseError, match="failed to parse JSON"):
        client.fetch_company_submissions("320193")


def test_fetch_missing_endpoint() -> None:
    """Test that fetch requires endpoint parameter."""
    client = SecClient(user_agent="Test test@example.com")
    
    with pytest.raises(SourceValidationError, match="endpoint parameter is required"):
        client.fetch(cik="320193")
