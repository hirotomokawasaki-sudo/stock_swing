"""SEC (Securities and Exchange Commission) source client implementation.

Provides access to SEC EDGAR API for filing retrieval to support event-driven
trading decisions. See SOURCE_MAPPING.md for canonical field mappings.

Supported use cases (approved initial scope):
- Recent filings retrieval (10-K, 10-Q, 8-K, etc.)
- Company filings search by CIK or ticker
- Filing metadata access

API Documentation: https://www.sec.gov/edgar/sec-api-documentation
Note: SEC requires a User-Agent header with contact information.
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
    SourceConnectionError,
    SourceNotFoundError,
    SourceRateLimitError,
    SourceResponseError,
    SourceServerError,
    SourceTimeoutError,
    SourceValidationError,
)
from stock_swing.sources.retry import RetryConfig


class SecClient(SourceClient):
    """SEC EDGAR API client for filing retrieval.
    
    This client supports approved filing access patterns for event-driven
    swing trading support. All requests include a User-Agent header as
    required by SEC.
    
    Attributes:
        name: Source name ("sec").
        user_agent: User-Agent string (required by SEC).
        base_url: SEC EDGAR API base URL.
        retry_config: Retry configuration.
    """

    name = "sec"
    base_url = "https://data.sec.gov"

    def __init__(
        self,
        user_agent: str,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """Initialize SEC client.
        
        Args:
            user_agent: User-Agent string (required by SEC, should include contact info).
                Example: "MyCompany name@example.com"
            retry_config: Custom retry configuration.
            
        Raises:
            ValueError: If user_agent is empty.
            ImportError: If httpx is not installed.
            
        Note:
            SEC requires a User-Agent header with identifying information.
            Requests without a proper User-Agent may be rejected.
        """
        super().__init__(retry_config)
        
        if not user_agent:
            raise ValueError("user_agent is required (SEC API requirement)")
        
        if httpx is None:
            raise ImportError(
                "httpx is required for SEC client. "
                "Install with: pip install httpx"
            )
        
        self.user_agent = user_agent

    def fetch(self, **kwargs: Any) -> RawEnvelope:
        """Fetch data from SEC EDGAR.
        
        Args:
            endpoint: SEC endpoint path (required).
                Example: "submissions/CIK0000320193.json"
            **kwargs: Additional endpoint-specific parameters.
            
        Returns:
            RawEnvelope with SEC response data.
            
        Raises:
            SourceValidationError: If required parameters are missing.
            SourceNotFoundError: If CIK or filing not found.
            SourceRateLimitError: If rate limit exceeded.
            SourceError: On any other error.
        """
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

    def fetch_company_submissions(self, cik: str) -> RawEnvelope:
        """Fetch company submission history by CIK.
        
        Args:
            cik: Central Index Key (CIK) - 10-digit number with leading zeros.
                Example: "0000320193" for Apple Inc.
                
        Returns:
            RawEnvelope with company submission metadata and recent filings.
            
        Note:
            CIK must be formatted as 10 digits with leading zeros.
            Use format_cik() helper to normalize CIK format.
        """
        # Normalize CIK format
        normalized_cik = self._format_cik(cik)
        endpoint = f"submissions/CIK{normalized_cik}.json"
        
        return self.fetch(endpoint=endpoint, cik=cik)

    def fetch_company_concept(
        self,
        cik: str,
        taxonomy: str,
        tag: str,
    ) -> RawEnvelope:
        """Fetch company concept data (XBRL taxonomy tag values).
        
        Args:
            cik: Central Index Key (10-digit with leading zeros).
            taxonomy: Taxonomy (e.g., "us-gaap", "ifrs-full").
            tag: XBRL tag (e.g., "Revenue", "Assets").
            
        Returns:
            RawEnvelope with concept data across filings.
            
        Example:
            fetch_company_concept("0000320193", "us-gaap", "Revenue")
        """
        normalized_cik = self._format_cik(cik)
        endpoint = f"api/xbrl/companyconcept/CIK{normalized_cik}/{taxonomy}/{tag}.json"
        
        return self.fetch(endpoint=endpoint, cik=cik, taxonomy=taxonomy, tag=tag)

    def fetch_recent_filings(
        self,
        form_type: str | None = None,
        start_index: int = 0,
        count: int = 100,
    ) -> RawEnvelope:
        """Fetch recent filings from SEC.
        
        Args:
            form_type: Filter by form type (e.g., "10-K", "10-Q", "8-K").
                If None, returns all form types.
            start_index: Starting index for pagination (default: 0).
            count: Number of results to return (default: 100, max: 1000).
            
        Returns:
            RawEnvelope with recent filings data.
            
        Note:
            This uses the submissions endpoint without CIK filtering.
            For production use, consider caching or filtering by date range.
        """
        # Note: SEC doesn't have a single "recent filings" endpoint
        # This is a stub for the interface - actual implementation would
        # need to aggregate from multiple sources or use a different approach
        endpoint = "submissions/recent.json"
        
        params = {
            "start": start_index,
            "count": count,
        }
        if form_type:
            params["form"] = form_type
        
        return self.fetch(endpoint=endpoint, **params)

    def _fetch_endpoint(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch data from a SEC endpoint.
        
        Args:
            endpoint: API endpoint path.
            params: Query parameters (unused for SEC, kept for consistency).
            
        Returns:
            Response data as dict.
            
        Raises:
            SourceError: On any error (normalized).
        """
        url = f"{self.base_url}/{endpoint}"
        
        # SEC requires User-Agent header
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        
        try:
            with httpx.Client(timeout=self.retry_config.timeout) as client:
                # SEC API uses path-based routing, not query params
                response = client.get(url, headers=headers)
            
            # Handle error status codes
            if response.status_code == 403:
                # SEC returns 403 for missing/invalid User-Agent
                raise SourceValidationError(
                    self.name,
                    "missing or invalid User-Agent header (SEC requirement)",
                )
            elif response.status_code == 404:
                raise SourceNotFoundError(
                    self.name,
                    f"resource not found: {endpoint}",
                )
            elif response.status_code == 429:
                # Rate limit
                retry_after = response.headers.get("Retry-After")
                retry_after_int = int(retry_after) if retry_after else None
                raise SourceRateLimitError(
                    self.name,
                    "rate limit exceeded (SEC allows 10 requests/second)",
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

    @staticmethod
    def _format_cik(cik: str) -> str:
        """Format CIK as 10-digit string with leading zeros.
        
        Args:
            cik: CIK as string or integer.
            
        Returns:
            10-digit CIK with leading zeros.
            
        Example:
            "320193" -> "0000320193"
            "0000320193" -> "0000320193"
        """
        # Remove any existing leading zeros or "CIK" prefix
        cik_clean = cik.replace("CIK", "").lstrip("0")
        
        # Pad to 10 digits
        return cik_clean.zfill(10)
