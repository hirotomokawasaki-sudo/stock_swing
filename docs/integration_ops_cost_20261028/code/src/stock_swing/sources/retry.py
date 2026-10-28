"""Retry and timeout utilities for source clients.

Provides configurable retry logic with exponential backoff for transient errors.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from stock_swing.sources.errors import (
    SourceConnectionError,
    SourceError,
    SourceRateLimitError,
    SourceServerError,
    SourceTimeoutError,
)


T = TypeVar("T")


@dataclass
class RetryConfig:
    """Configuration for retry behavior.
    
    Attributes:
        max_attempts: Maximum number of attempts (including initial attempt).
        initial_delay: Initial delay in seconds before first retry.
        max_delay: Maximum delay in seconds between retries.
        backoff_factor: Multiplier for exponential backoff (e.g., 2.0 doubles delay each time).
        timeout: Request timeout in seconds (per attempt).
    """

    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    timeout: float = 30.0

    def __post_init__(self) -> None:
        """Validate retry configuration."""
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_delay <= 0:
            raise ValueError("initial_delay must be positive")
        if self.max_delay < self.initial_delay:
            raise ValueError("max_delay must be >= initial_delay")
        if self.backoff_factor < 1.0:
            raise ValueError("backoff_factor must be >= 1.0")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


def is_retryable_error(error: Exception) -> bool:
    """Determine if an error is transient and should be retried.
    
    Args:
        error: Exception to check.
        
    Returns:
        True if the error is retryable, False otherwise.
        
    Retryable errors:
        - SourceConnectionError
        - SourceTimeoutError
        - SourceServerError (5xx)
        - SourceRateLimitError
        
    Non-retryable errors:
        - SourceAuthenticationError (config issue)
        - SourceNotFoundError (resource doesn't exist)
        - SourceValidationError (client error)
        - SourceResponseError (schema mismatch)
    """
    return isinstance(
        error,
        (
            SourceConnectionError,
            SourceTimeoutError,
            SourceServerError,
            SourceRateLimitError,
        ),
    )


def retry_with_backoff(
    func: Callable[[], T],
    config: RetryConfig,
    source_name: str,
) -> T:
    """Execute a function with retry and exponential backoff.
    
    Args:
        func: Function to execute (should raise SourceError on failure).
        config: Retry configuration.
        source_name: Name of the source for error messages.
        
    Returns:
        Result of the function call.
        
    Raises:
        SourceError: If all retry attempts fail, the last error is raised.
        
    Behavior:
        - Retries only transient errors (see is_retryable_error)
        - Uses exponential backoff with configurable parameters
        - Respects rate limit Retry-After hints
        - Non-retryable errors fail immediately
    """
    delay = config.initial_delay
    last_error: Exception | None = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            return func()
        except SourceError as e:
            last_error = e

            # Non-retryable errors fail immediately
            if not is_retryable_error(e):
                raise

            # Last attempt exhausted
            if attempt == config.max_attempts:
                raise

            # Calculate delay
            if isinstance(e, SourceRateLimitError) and e.retry_after:
                wait_time = float(e.retry_after)
            else:
                wait_time = min(delay, config.max_delay)

            # Wait before retry
            time.sleep(wait_time)

            # Exponential backoff
            delay *= config.backoff_factor

    # Should not reach here, but raise last error if we do
    if last_error:
        raise last_error
    raise RuntimeError(f"[{source_name}] retry logic error: no attempts made")
