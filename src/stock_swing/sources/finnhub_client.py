"""Finnhub source client implementation.

Provides access to Finnhub API endpoints for fundamentals, earnings, insider transactions, 
and filing sentiment. See SOURCE_MAPPING.md for canonical field mappings.

Supported endpoints (approved initial scope):
- /stock/metric - Basic financials
- /calendar/earnings - Earnings calendar
- /stock/insider-transactions - Insider transactions
- /stock/filings-sentiment - Filing sentiment

API Documentation: https://finnhub.io/docs/api
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


class FinnhubClient(SourceClient):
    """Finnhub API client for fundamental data.
    
    This client supports the approved initial scope of Finnhub endpoints
    for event-driven swing trading support.
    
    Attributes:
        name: Source name ("finnhub").
        api_key: Finnhub API key.
        base_url: Finnhub API base URL.
        retry_config: Retry configuration.
    """

    name = "finnhub"
    base_url = "https://finnhub.io/api/v1"

    def __init__(
        self,
        api_key: str,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """Initialize Finnhub client.
        
        Args:
            api_key: Finnhub API key (required).
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
                "httpx is required for Finnhub client. "
                "Install with: pip install httpx"
            )
        
        self.api_key = api_key

    def fetch(self, **kwargs: Any) -> RawEnvelope:
        """Fetch data from Finnhub.
        
        Args:
            endpoint: Finnhub endpoint name (required).
                Supported: "stock/metric", "calendar/earnings", 
                "stock/insider-transactions", "stock/filings-sentiment"
            symbol: Stock symbol (required for most endpoints).
            **kwargs: Additional endpoint-specific parameters.
            
        Returns:
            RawEnvelope with Finnhub response data.
            
        Raises:
            SourceValidationError: If required parameters are missing.
            SourceAuthenticationError: If API key is invalid.
            SourceNotFoundError: If symbol or resource not found.
            SourceRateLimitError: If rate limit exceeded.
            SourceError: On any other error.
        """
        # Validate endpoint
        if "endpoint" not in kwargs:
            raise SourceValidationError(self.name, "endpoint parameter is required")
        
        endpoint = kwargs["endpoint"]
        
        # Build request params (excluding 'endpoint')
        request_params = {k: v for k, v in kwargs.items() if k != "endpoint"}
        
        # Fetch with retry
        def fetch_func() -> dict[str, Any]:
            return self._fetch_endpoint(endpoint, request_params)
        
        payload = self._fetch_with_retry(fetch_func)
        
        return self._build_envelope(endpoint, request_params, payload)

    def fetch_basic_financials(self, symbol: str, metric: str = "all") -> RawEnvelope:
        """Fetch basic financials for a symbol.
        
        Args:
            symbol: Stock symbol (e.g., "AAPL").
            metric: Metric type (default: "all").
            
        Returns:
            RawEnvelope with basic financials data.
        """
        return self.fetch(endpoint="stock/metric", symbol=symbol, metric=metric)

    def fetch_earnings_calendar(
        self,
        symbol: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> RawEnvelope:
        """Fetch earnings calendar.
        
        Args:
            symbol: Stock symbol (optional, filters by symbol).
            from_date: Start date (YYYY-MM-DD format, optional).
            to_date: End date (YYYY-MM-DD format, optional).
            
        Returns:
            RawEnvelope with earnings calendar data.
        """
        params: dict[str, Any] = {"endpoint": "calendar/earnings"}
        if symbol:
            params["symbol"] = symbol
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        
        return self.fetch(**params)

    def fetch_insider_transactions(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> RawEnvelope:
        """Fetch insider transactions for a symbol.
        
        Args:
            symbol: Stock symbol (e.g., "AAPL").
            from_date: Start date (YYYY-MM-DD format, optional).
            to_date: End date (YYYY-MM-DD format, optional).
            
        Returns:
            RawEnvelope with insider transaction data.
        """
        params: dict[str, Any] = {
            "endpoint": "stock/insider-transactions",
            "symbol": symbol,
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        
        return self.fetch(**params)

    def fetch_filing_sentiment(self, access_number: str) -> RawEnvelope:
        """Fetch filing sentiment analysis.
        
        Args:
            access_number: SEC filing accession number.
            
        Returns:
            RawEnvelope with filing sentiment data.
        """
        return self.fetch(
            endpoint="stock/filings-sentiment",
            accessNumber=access_number,
        )

    def _fetch_endpoint(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch data from a Finnhub endpoint.
        
        Args:
            endpoint: API endpoint path (e.g., "stock/metric").
            params: Query parameters.
            
        Returns:
            Response data as dict.
            
        Raises:
            SourceError: On any error (normalized).
        """
        url = f"{self.base_url}/{endpoint}"
        
        # Add API key to params
        query_params = {**params, "token": self.api_key}
        
        try:
            with httpx.Client(timeout=self.retry_config.timeout) as client:
                response = client.get(url, params=query_params)
            
            # Handle error status codes
            if response.status_code == 401:
                raise SourceAuthenticationError(
                    self.name,
                    "invalid or missing API key",
                )
            elif response.status_code == 403:
                raise SourceAuthenticationError(
                    self.name,
                    "API key does not have permission for this endpoint",
                )
            elif response.status_code == 404:
                raise SourceNotFoundError(
                    self.name,
                    f"resource not found: {endpoint}",
                )
            elif response.status_code == 429:
                # Try to extract retry-after header
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
