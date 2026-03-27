"""Base source client contract and shared conventions.

This module defines the abstract base class for all source clients and
provides common utilities for request/response handling, error normalization,
and metadata conventions.

See SOURCE_MAPPING.md for source-specific mapping rules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from stock_swing.core.types import RawEnvelope
from stock_swing.sources.errors import SourceError
from stock_swing.sources.retry import RetryConfig, retry_with_backoff


class SourceClient(ABC):
    """Abstract base class for all source clients.
    
    All source clients must inherit from this class and implement the fetch method.
    The base class provides common utilities for error handling, retry logic,
    and metadata conventions.
    
    Attributes:
        name: Source name (e.g., "finnhub", "fred", "sec", "broker").
        retry_config: Retry configuration for this client.
    """

    name: str
    retry_config: RetryConfig

    def __init__(self, retry_config: RetryConfig | None = None) -> None:
        """Initialize source client with optional retry configuration.
        
        Args:
            retry_config: Custom retry configuration. If None, uses default.
        """
        if not hasattr(self, "name"):
            raise ValueError(f"{self.__class__.__name__} must define 'name' attribute")
        self.retry_config = retry_config or RetryConfig()

    @abstractmethod
    def fetch(self, **kwargs: Any) -> RawEnvelope:
        """Fetch data from the source and return a raw envelope.
        
        Args:
            **kwargs: Source-specific request parameters.
            
        Returns:
            RawEnvelope with source data, metadata, and timestamps.
            
        Raises:
            SourceError: On any error (normalized error types).
            
        Implementation requirements:
            - Must validate required parameters
            - Must normalize provider errors to SourceError subclasses
            - Must populate RawEnvelope with complete metadata
            - Should use _fetch_with_retry for retry support
        """
        raise NotImplementedError

    def _fetch_with_retry(
        self,
        fetch_func: Any,  # Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        """Execute a fetch function with retry and backoff.
        
        Args:
            fetch_func: Function that performs the actual HTTP/API call.
                Should raise SourceError on failure.
                
        Returns:
            Response data (typically dict).
            
        Raises:
            SourceError: If all retry attempts fail.
            
        Note:
            This is a helper method for subclasses to use in their fetch implementation.
        """
        return retry_with_backoff(fetch_func, self.retry_config, self.name)

    def _build_envelope(
        self,
        endpoint: str,
        request_params: dict[str, Any],
        payload: dict[str, Any],
    ) -> RawEnvelope:
        """Build a RawEnvelope with consistent metadata.
        
        Args:
            endpoint: API endpoint or operation name.
            request_params: Original request parameters.
            payload: Raw response data from provider.
            
        Returns:
            RawEnvelope with source metadata and timestamps.
            
        Metadata conventions:
            - source: Client name (e.g., "finnhub")
            - endpoint: Provider-specific endpoint identifier
            - fetched_at: UTC timestamp when data was fetched
            - request_params: Normalized request parameters
            - payload: Raw provider response
        """
        return RawEnvelope(
            source=self.name,
            endpoint=endpoint,
            fetched_at=datetime.now(timezone.utc),
            request_params=request_params,
            payload=payload,
        )

    def _validate_required_params(
        self,
        params: dict[str, Any],
        required: list[str],
    ) -> None:
        """Validate that required parameters are present.
        
        Args:
            params: Request parameters to validate.
            required: List of required parameter names.
            
        Raises:
            SourceError: If any required parameter is missing.
        """
        from stock_swing.sources.errors import SourceValidationError

        missing = [key for key in required if key not in params]
        if missing:
            raise SourceValidationError(
                self.name,
                f"missing required parameters: {', '.join(missing)}",
            )
