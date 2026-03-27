"""FRED (Federal Reserve Economic Data) source client implementation.

Provides access to FRED API for macro data retrieval to support regime classification
and economic event context. See SOURCE_MAPPING.md for canonical field mappings.

Supported use cases (approved initial scope):
- Macro series data for regime classification
- Economic indicators for event support

API Documentation: https://fred.stlouisfed.org/docs/api/fred/
"""

from __future__ import annotations

from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from stock_swing.core.types import RawEnvelope
from stock_swing.sources.base import SourceClient
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
from stock_swing.sources.retry import RetryConfig


class FredClient(SourceClient):
    """FRED API client for macro data.
    
    This client supports macro series retrieval for regime classification
    and economic event support in event-driven swing trading.
    
    Attributes:
        name: Source name ("fred").
        api_key: FRED API key.
        base_url: FRED API base URL.
        retry_config: Retry configuration.
    """

    name = "fred"
    base_url = "https://api.stlouisfed.org/fred"

    def __init__(
        self,
        api_key: str,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """Initialize FRED client.
        
        Args:
            api_key: FRED API key (required).
            retry_config: Custom retry configuration.
            
        Raises:
            ValueError: If api_key is empty.
            ImportError: If httpx is not installed.
        """
        super().__init__(retry_config)
        
        if not api_key:
            raise ValueError("api_key is required")
        
        if httpx is None:
            raise ImportError(
                "httpx is required for FRED client. "
                "Install with: pip install httpx"
            )
        
        self.api_key = api_key

    def fetch(self, **kwargs: Any) -> RawEnvelope:
        """Fetch data from FRED.
        
        Args:
            endpoint: FRED endpoint name (default: "series/observations").
                Supported: "series/observations", "series", "series/search"
            series_id: FRED series ID (e.g., "CPIAUCSL", "GDP") - required for most endpoints.
            **kwargs: Additional endpoint-specific parameters.
            
        Returns:
            RawEnvelope with FRED response data.
            
        Raises:
            SourceValidationError: If required parameters are missing.
            SourceAuthenticationError: If API key is invalid.
            SourceNotFoundError: If series or resource not found.
            SourceRateLimitError: If rate limit exceeded.
            SourceError: On any other error.
        """
        endpoint = kwargs.get("endpoint", "series/observations")
        
        # Build request params (excluding 'endpoint')
        request_params = {k: v for k, v in kwargs.items() if k != "endpoint"}
        
        # Fetch with retry
        def fetch_func() -> dict[str, Any]:
            return self._fetch_endpoint(endpoint, request_params)
        
        payload = self._fetch_with_retry(fetch_func)
        
        return self._build_envelope(endpoint, request_params, payload)

    def fetch_series_observations(
        self,
        series_id: str,
        observation_start: str | None = None,
        observation_end: str | None = None,
        limit: int | None = None,
        sort_order: str = "asc",
    ) -> RawEnvelope:
        """Fetch observations (data points) for a FRED series.
        
        Args:
            series_id: FRED series ID (e.g., "CPIAUCSL" for CPI).
            observation_start: Start date (YYYY-MM-DD format, optional).
            observation_end: End date (YYYY-MM-DD format, optional).
            limit: Maximum number of observations (optional).
            sort_order: Sort order ("asc" or "desc", default: "asc").
            
        Returns:
            RawEnvelope with series observations.
            
        Example series IDs for regime classification:
            - CPIAUCSL: Consumer Price Index
            - GDP: Gross Domestic Product
            - UNRATE: Unemployment Rate
            - FEDFUNDS: Federal Funds Rate
            - DGS10: 10-Year Treasury Rate
        """
        params: dict[str, Any] = {
            "endpoint": "series/observations",
            "series_id": series_id,
            "sort_order": sort_order,
        }
        
        if observation_start:
            params["observation_start"] = observation_start
        if observation_end:
            params["observation_end"] = observation_end
        if limit:
            params["limit"] = limit
        
        return self.fetch(**params)

    def fetch_series_info(self, series_id: str) -> RawEnvelope:
        """Fetch metadata for a FRED series.
        
        Args:
            series_id: FRED series ID.
            
        Returns:
            RawEnvelope with series metadata (title, units, frequency, etc.).
        """
        return self.fetch(endpoint="series", series_id=series_id)

    def fetch_series_search(
        self,
        search_text: str,
        limit: int = 10,
    ) -> RawEnvelope:
        """Search for FRED series by keyword.
        
        Args:
            search_text: Search query text.
            limit: Maximum number of results (default: 10).
            
        Returns:
            RawEnvelope with search results.
        """
        return self.fetch(
            endpoint="series/search",
            search_text=search_text,
            limit=limit,
        )

    def _fetch_endpoint(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch data from a FRED endpoint.
        
        Args:
            endpoint: API endpoint path (e.g., "series/observations").
            params: Query parameters.
            
        Returns:
            Response data as dict.
            
        Raises:
            SourceError: On any error (normalized).
        """
        url = f"{self.base_url}/{endpoint}"
        
        # Add API key and JSON format to params
        query_params = {
            **params,
            "api_key": self.api_key,
            "file_type": "json",
        }
        
        try:
            with httpx.Client(timeout=self.retry_config.timeout) as client:
                response = client.get(url, params=query_params)
            
            # Handle error status codes
            if response.status_code == 400:
                # FRED returns 400 for various client errors
                try:
                    error_data = response.json()
                    error_message = error_data.get("error_message", "bad request")
                    
                    # Check if it's an authentication issue
                    if "api_key" in error_message.lower() or "invalid" in error_message.lower():
                        raise SourceAuthenticationError(
                            self.name,
                            f"API key error: {error_message}",
                        )
                    
                    # Check if it's a not found issue
                    if "not found" in error_message.lower():
                        raise SourceNotFoundError(
                            self.name,
                            error_message,
                        )
                    
                    # Otherwise, validation error
                    raise SourceValidationError(
                        self.name,
                        error_message,
                    )
                except (ValueError, KeyError):
                    raise SourceValidationError(
                        self.name,
                        f"bad request: {response.status_code}",
                    )
            
            elif response.status_code == 429:
                # Rate limit
                retry_after = response.headers.get("Retry-After")
                retry_after_int = int(retry_after) if retry_after else None
                raise SourceRateLimitError(
                    self.name,
                    "rate limit exceeded",
                    retry_after=retry_after_int,
                )
            
            elif response.status_code >= 500:
                raise SourceServerError(
                    self.name,
                    f"server error: {response.status_code}",
                )
            
            elif response.status_code != 200:
                raise SourceResponseError(
                    self.name,
                    f"unexpected status code: {response.status_code}",
                )
            
            # Parse JSON response
            try:
                data = response.json()
            except Exception as e:
                raise SourceResponseError(
                    self.name,
                    f"failed to parse JSON response: {e}",
                    original_error=e,
                )
            
            # FRED wraps errors in 200 responses with error_code field
            if isinstance(data, dict) and "error_code" in data:
                error_message = data.get("error_message", "unknown error")
                
                # Map FRED error codes to our error types
                if data["error_code"] == 400:
                    if "api_key" in error_message.lower():
                        raise SourceAuthenticationError(self.name, error_message)
                    elif "not found" in error_message.lower():
                        raise SourceNotFoundError(self.name, error_message)
                    else:
                        raise SourceValidationError(self.name, error_message)
                
                elif data["error_code"] == 429:
                    raise SourceRateLimitError(self.name, error_message)
                
                else:
                    raise SourceResponseError(
                        self.name,
                        f"FRED error: {error_message}",
                    )
            
            return data
        
        except httpx.TimeoutException as e:
            raise SourceTimeoutError(
                self.name,
                f"request timeout after {self.retry_config.timeout}s",
                original_error=e,
            )
        except httpx.ConnectError as e:
            raise SourceConnectionError(
                self.name,
                f"connection failed: {e}",
                original_error=e,
            )
        except httpx.HTTPError as e:
            raise SourceConnectionError(
                self.name,
                f"HTTP error: {e}",
                original_error=e,
            )
