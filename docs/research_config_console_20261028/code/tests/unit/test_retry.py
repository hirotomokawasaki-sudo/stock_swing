"""Tests for retry and backoff logic."""

import pytest

from stock_swing.sources.errors import (
    SourceAuthenticationError,
    SourceConnectionError,
    SourceNotFoundError,
    SourceRateLimitError,
    SourceServerError,
    SourceTimeoutError,
    SourceValidationError,
)
from stock_swing.sources.retry import (
    RetryConfig,
    is_retryable_error,
    retry_with_backoff,
)


def test_retry_config_defaults() -> None:
    """Test RetryConfig default values."""
    config = RetryConfig()
    
    assert config.max_attempts == 3
    assert config.initial_delay == 1.0
    assert config.max_delay == 30.0
    assert config.backoff_factor == 2.0
    assert config.timeout == 30.0


def test_retry_config_validation() -> None:
    """Test RetryConfig validation."""
    with pytest.raises(ValueError, match="max_attempts must be at least 1"):
        RetryConfig(max_attempts=0)
    
    with pytest.raises(ValueError, match="initial_delay must be positive"):
        RetryConfig(initial_delay=0)
    
    with pytest.raises(ValueError, match="max_delay must be >= initial_delay"):
        RetryConfig(initial_delay=10, max_delay=5)
    
    with pytest.raises(ValueError, match="backoff_factor must be >= 1.0"):
        RetryConfig(backoff_factor=0.5)
    
    with pytest.raises(ValueError, match="timeout must be positive"):
        RetryConfig(timeout=0)


def test_is_retryable_connection_error() -> None:
    """Test that connection errors are retryable."""
    error = SourceConnectionError("test", "connection failed")
    assert is_retryable_error(error) is True


def test_is_retryable_timeout_error() -> None:
    """Test that timeout errors are retryable."""
    error = SourceTimeoutError("test", "timeout")
    assert is_retryable_error(error) is True


def test_is_retryable_server_error() -> None:
    """Test that server errors are retryable."""
    error = SourceServerError("test", "500 internal error")
    assert is_retryable_error(error) is True


def test_is_retryable_rate_limit_error() -> None:
    """Test that rate limit errors are retryable."""
    error = SourceRateLimitError("test", "rate limited")
    assert is_retryable_error(error) is True


def test_is_not_retryable_authentication_error() -> None:
    """Test that authentication errors are not retryable."""
    error = SourceAuthenticationError("test", "invalid key")
    assert is_retryable_error(error) is False


def test_is_not_retryable_not_found_error() -> None:
    """Test that not found errors are not retryable."""
    error = SourceNotFoundError("test", "not found")
    assert is_retryable_error(error) is False


def test_is_not_retryable_validation_error() -> None:
    """Test that validation errors are not retryable."""
    error = SourceValidationError("test", "invalid params")
    assert is_retryable_error(error) is False


def test_retry_succeeds_on_first_attempt() -> None:
    """Test retry succeeds immediately if no error."""
    call_count = 0
    
    def func():
        nonlocal call_count
        call_count += 1
        return "success"
    
    config = RetryConfig(max_attempts=3)
    result = retry_with_backoff(func, config, "test")
    
    assert result == "success"
    assert call_count == 1


def test_retry_succeeds_after_transient_error() -> None:
    """Test retry succeeds after retryable error."""
    call_count = 0
    
    def func():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise SourceConnectionError("test", "connection failed")
        return "success"
    
    config = RetryConfig(max_attempts=3, initial_delay=0.01, backoff_factor=1.0)
    result = retry_with_backoff(func, config, "test")
    
    assert result == "success"
    assert call_count == 2


def test_retry_fails_after_max_attempts() -> None:
    """Test retry fails after exhausting all attempts."""
    call_count = 0
    
    def func():
        nonlocal call_count
        call_count += 1
        raise SourceConnectionError("test", "connection failed")
    
    config = RetryConfig(max_attempts=3, initial_delay=0.01, backoff_factor=1.0)
    
    with pytest.raises(SourceConnectionError):
        retry_with_backoff(func, config, "test")
    
    assert call_count == 3


def test_retry_fails_immediately_on_non_retryable_error() -> None:
    """Test that non-retryable errors fail immediately without retry."""
    call_count = 0
    
    def func():
        nonlocal call_count
        call_count += 1
        raise SourceAuthenticationError("test", "invalid key")
    
    config = RetryConfig(max_attempts=3)
    
    with pytest.raises(SourceAuthenticationError):
        retry_with_backoff(func, config, "test")
    
    # Should fail on first attempt only
    assert call_count == 1


def test_retry_respects_rate_limit_retry_after() -> None:
    """Test that retry respects Retry-After from rate limit errors."""
    call_count = 0
    
    def func():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise SourceRateLimitError("test", "rate limited", retry_after=0.01)
        return "success"
    
    config = RetryConfig(max_attempts=3, initial_delay=1.0)
    result = retry_with_backoff(func, config, "test")
    
    assert result == "success"
    assert call_count == 2
    # Note: actual delay verification would require time measurement
