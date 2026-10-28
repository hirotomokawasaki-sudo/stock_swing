"""Tests for source error normalization."""

import pytest

from stock_swing.sources.errors import (
    SourceAuthenticationError,
    SourceConnectionError,
    SourceError,
    SourceNotFoundError,
    SourceRateLimitError,
    SourceResponseError,
    SourceServerError,
    SourceTimeoutError,
    SourceValidationError,
)


def test_source_error_base() -> None:
    """Test base SourceError."""
    error = SourceError("test_source", "test message")
    
    assert error.source == "test_source"
    assert error.message == "test message"
    assert error.original_error is None
    assert str(error) == "[test_source] test message"


def test_source_error_with_original() -> None:
    """Test SourceError with original exception."""
    original = ValueError("original error")
    error = SourceError("test_source", "wrapped error", original)
    
    assert error.original_error is original


def test_source_connection_error() -> None:
    """Test SourceConnectionError."""
    error = SourceConnectionError("finnhub", "connection refused")
    
    assert isinstance(error, SourceError)
    assert error.source == "finnhub"


def test_source_timeout_error() -> None:
    """Test SourceTimeoutError."""
    error = SourceTimeoutError("fred", "request timeout after 30s")
    
    assert isinstance(error, SourceError)
    assert error.source == "fred"


def test_source_authentication_error() -> None:
    """Test SourceAuthenticationError."""
    error = SourceAuthenticationError("sec", "invalid API key")
    
    assert isinstance(error, SourceError)
    assert error.source == "sec"


def test_source_rate_limit_error() -> None:
    """Test SourceRateLimitError with retry_after."""
    error = SourceRateLimitError("broker", "rate limit exceeded", retry_after=60)
    
    assert isinstance(error, SourceError)
    assert error.retry_after == 60


def test_source_rate_limit_error_without_retry_after() -> None:
    """Test SourceRateLimitError without retry_after."""
    error = SourceRateLimitError("finnhub", "rate limit exceeded")
    
    assert error.retry_after is None


def test_source_not_found_error() -> None:
    """Test SourceNotFoundError."""
    error = SourceNotFoundError("finnhub", "symbol not found: XYZ")
    
    assert isinstance(error, SourceError)


def test_source_validation_error() -> None:
    """Test SourceValidationError."""
    error = SourceValidationError("fred", "missing required parameter: series_id")
    
    assert isinstance(error, SourceError)


def test_source_server_error() -> None:
    """Test SourceServerError."""
    error = SourceServerError("broker", "internal server error (500)")
    
    assert isinstance(error, SourceError)


def test_source_response_error() -> None:
    """Test SourceResponseError."""
    error = SourceResponseError("finnhub", "unexpected response format")
    
    assert isinstance(error, SourceError)
