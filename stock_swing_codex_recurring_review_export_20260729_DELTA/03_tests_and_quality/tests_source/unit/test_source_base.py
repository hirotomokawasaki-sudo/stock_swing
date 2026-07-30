"""Tests for base source client contract."""

from datetime import datetime
from typing import Any

import pytest

from stock_swing.core.types import RawEnvelope
from stock_swing.sources.base import SourceClient
from stock_swing.sources.errors import SourceValidationError
from stock_swing.sources.retry import RetryConfig


class TestSourceClient(SourceClient):
    """Test implementation of SourceClient."""
    
    name = "test_source"
    
    def fetch(self, **kwargs: Any) -> RawEnvelope:
        """Simple fetch implementation for testing."""
        return self._build_envelope(
            endpoint=kwargs.get("endpoint", "test"),
            request_params=kwargs,
            payload={"data": "test"},
        )


def test_source_client_requires_name_attribute() -> None:
    """Test that SourceClient subclasses must define name attribute."""
    
    class InvalidClient(SourceClient):
        def fetch(self, **kwargs: Any) -> RawEnvelope:
            return RawEnvelope(
                source="test",
                endpoint="test",
                fetched_at=datetime.now(),
                request_params={},
                payload={},
            )
    
    with pytest.raises(ValueError, match="must define 'name' attribute"):
        InvalidClient()


def test_source_client_default_retry_config() -> None:
    """Test that source client uses default retry config."""
    client = TestSourceClient()
    
    assert client.retry_config.max_attempts == 3
    assert client.retry_config.timeout == 30.0


def test_source_client_custom_retry_config() -> None:
    """Test that source client accepts custom retry config."""
    config = RetryConfig(max_attempts=5, timeout=60.0)
    client = TestSourceClient(retry_config=config)
    
    assert client.retry_config.max_attempts == 5
    assert client.retry_config.timeout == 60.0


def test_build_envelope() -> None:
    """Test _build_envelope helper."""
    client = TestSourceClient()
    
    envelope = client._build_envelope(
        endpoint="test_endpoint",
        request_params={"symbol": "AAPL"},
        payload={"data": "test"},
    )
    
    assert envelope.source == "test_source"
    assert envelope.endpoint == "test_endpoint"
    assert envelope.request_params == {"symbol": "AAPL"}
    assert envelope.payload == {"data": "test"}
    assert isinstance(envelope.fetched_at, datetime)


def test_validate_required_params_success() -> None:
    """Test parameter validation when all required params are present."""
    client = TestSourceClient()
    
    params = {"symbol": "AAPL", "date": "2026-03-06"}
    # Should not raise
    client._validate_required_params(params, ["symbol", "date"])


def test_validate_required_params_missing() -> None:
    """Test parameter validation when required params are missing."""
    client = TestSourceClient()
    
    params = {"symbol": "AAPL"}
    
    with pytest.raises(SourceValidationError, match="missing required parameters: date"):
        client._validate_required_params(params, ["symbol", "date"])


def test_validate_required_params_multiple_missing() -> None:
    """Test parameter validation with multiple missing params."""
    client = TestSourceClient()
    
    params = {}
    
    with pytest.raises(SourceValidationError, match="symbol, date"):
        client._validate_required_params(params, ["symbol", "date"])


def test_fetch_returns_envelope() -> None:
    """Test that fetch returns a properly structured RawEnvelope."""
    client = TestSourceClient()
    
    envelope = client.fetch(endpoint="test", symbol="AAPL")
    
    assert isinstance(envelope, RawEnvelope)
    assert envelope.source == "test_source"
    assert envelope.endpoint == "test"
    assert "symbol" in envelope.request_params
