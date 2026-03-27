"""Integration tests for SEC client with retry logic."""

from unittest.mock import Mock, patch

import pytest

from stock_swing.sources.errors import SourceConnectionError
from stock_swing.sources.retry import RetryConfig
from stock_swing.sources.sec_client import SecClient


pytest.importorskip("httpx")


@patch("httpx.Client")
def test_sec_retry_on_connection_error(mock_client_class: Mock) -> None:
    """Test that SEC client retries on transient connection errors."""
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
            "cik": "320193",
            "name": "Apple Inc.",
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
    
    client = SecClient(
        user_agent="Test test@example.com",
        retry_config=retry_config,
    )
    envelope = client.fetch_company_submissions("320193")
    
    assert envelope.payload["name"] == "Apple Inc."
    assert call_count == 2


@patch("httpx.Client")
def test_sec_fails_after_max_retries(mock_client_class: Mock) -> None:
    """Test that SEC client fails after exhausting retries."""
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
    
    client = SecClient(
        user_agent="Test test@example.com",
        retry_config=retry_config,
    )
    
    with pytest.raises(SourceConnectionError):
        client.fetch_company_submissions("320193")
    
    assert call_count == 3


@patch("httpx.Client")
def test_sec_multiple_company_calls(mock_client_class: Mock) -> None:
    """Test calling multiple SEC endpoints in sequence."""
    
    def get_side_effect(url: str, headers: dict):
        mock_response = Mock()
        mock_response.status_code = 200
        
        if "submissions" in url:
            mock_response.json.return_value = {
                "cik": "320193",
                "name": "Apple Inc.",
            }
        elif "companyconcept" in url:
            mock_response.json.return_value = {
                "cik": "320193",
                "tag": "Revenue",
            }
        else:
            mock_response.json.return_value = {}
        
        return mock_response
    
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = get_side_effect
    mock_client_class.return_value = mock_client
    
    client = SecClient(user_agent="Test test@example.com")
    
    # Fetch multiple endpoints
    env1 = client.fetch_company_submissions("320193")
    env2 = client.fetch_company_concept("320193", "us-gaap", "Revenue")
    
    assert "submissions" in env1.endpoint
    assert "companyconcept" in env2.endpoint
