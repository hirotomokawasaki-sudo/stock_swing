"""Normalized error types for source clients.

This module provides a consistent error hierarchy for all source clients,
enabling uniform error handling across providers.
"""

from __future__ import annotations


class SourceError(Exception):
    """Base exception for all source client errors.
    
    Attributes:
        source: Name of the source that raised the error (e.g., "finnhub", "fred").
        message: Human-readable error message.
        original_error: Optional original exception for debugging.
    """

    def __init__(
        self,
        source: str,
        message: str,
        original_error: Exception | None = None,
    ) -> None:
        """Initialize SourceError.
        
        Args:
            source: Source name.
            message: Error message.
            original_error: Original exception if available.
        """
        self.source = source
        self.message = message
        self.original_error = original_error
        super().__init__(f"[{source}] {message}")


class SourceConnectionError(SourceError):
    """Raised when source connection fails (network, DNS, timeout).
    
    This indicates a transient error that may succeed on retry.
    """

    pass


class SourceTimeoutError(SourceError):
    """Raised when source request times out.
    
    This is a specific type of connection error for timeout conditions.
    """

    pass


class SourceAuthenticationError(SourceError):
    """Raised when source authentication fails (API key invalid, expired, etc.).
    
    This indicates a configuration error that requires manual intervention.
    """

    pass


class SourceRateLimitError(SourceError):
    """Raised when source rate limit is exceeded.
    
    Attributes:
        retry_after: Optional seconds to wait before retrying.
    """

    def __init__(
        self,
        source: str,
        message: str,
        retry_after: int | None = None,
        original_error: Exception | None = None,
    ) -> None:
        """Initialize SourceRateLimitError.
        
        Args:
            source: Source name.
            message: Error message.
            retry_after: Seconds to wait before retrying (from Retry-After header).
            original_error: Original exception if available.
        """
        super().__init__(source, message, original_error)
        self.retry_after = retry_after


class SourceNotFoundError(SourceError):
    """Raised when requested resource is not found (404, symbol not found, etc.).
    
    This is typically not transient and should not be retried.
    """

    pass


class SourceValidationError(SourceError):
    """Raised when request validation fails (invalid params, missing required fields).
    
    This indicates a client-side error that should not be retried.
    """

    pass


class SourceServerError(SourceError):
    """Raised when source returns a server error (5xx, internal error).
    
    This may be transient and could succeed on retry.
    """

    pass


class SourceResponseError(SourceError):
    """Raised when response parsing or validation fails.
    
    This indicates unexpected response format or schema mismatch.
    """

    pass
