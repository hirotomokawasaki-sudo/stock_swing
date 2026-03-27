"""Broker source client for paper-safe market data and order interface foundations.

Provides access to broker API for market data, paper order submission, and reconciliation.
This is a FOUNDATION layer for later paper execution integration.

CRITICAL: This implementation is paper/research safe only. Live execution behavior
is NOT implemented and must NOT be enabled without explicit approval and safety validation.

See EXECUTION_POLICY.md for execution constraints and requirements.
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


class BrokerClient(SourceClient):
    """Broker API client for market data and paper-safe order interface.
    
    This client provides FOUNDATION interfaces for:
    - Market data access (bars, quotes)
    - Paper-safe order interface foundations
    - Order status and position retrieval
    
    SAFETY: This is a paper/research-safe implementation.
    Live order submission flows are NOT implemented here.
    
    Attributes:
        name: Source name ("broker").
        api_key: Broker API key.
        api_secret: Broker API secret.
        base_url: Broker API base URL.
        paper_mode: If True, uses paper trading endpoints (default: True).
        retry_config: Retry configuration.
    """

    name = "broker"
    # Using Alpaca as reference broker (paper trading available)
    base_url_paper = "https://paper-api.alpaca.markets"
    base_url_live = "https://api.alpaca.markets"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper_mode: bool = True,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """Initialize Broker client.
        
        Args:
            api_key: Broker API key (required).
            api_secret: Broker API secret (required).
            paper_mode: If True, use paper trading endpoints (default: True).
                SAFETY: Live mode endpoints are blocked in this implementation.
            retry_config: Custom retry configuration.
            
        Raises:
            ValueError: If api_key or api_secret is empty, or if paper_mode is False.
            ImportError: If httpx is not installed.
            
        Safety:
            This implementation enforces paper_mode=True. Attempting to use
            live mode will raise ValueError to prevent accidental live execution.
        """
        super().__init__(retry_config)
        
        if not api_key:
            raise ValueError("api_key is required")
        if not api_secret:
            raise ValueError("api_secret is required")
        
        # SAFETY: Block live mode in this implementation
        if not paper_mode:
            raise ValueError(
                "Live mode is NOT supported in this implementation. "
                "This is a paper/research-safe broker client foundation only. "
                "Live execution requires explicit approval and safety validation."
            )
        
        if httpx is None:
            raise ImportError(
                "httpx is required for Broker client. "
                "Install with: pip install httpx"
            )
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_mode = paper_mode
        self.base_url = self.base_url_paper if paper_mode else self.base_url_live

    def fetch(self, **kwargs: Any) -> RawEnvelope:
        """Fetch data from broker API.
        
        Args:
            endpoint: Broker endpoint path (required).
            method: HTTP method (default: "GET").
            **kwargs: Additional endpoint-specific parameters or body.
            
        Returns:
            RawEnvelope with broker response data.
            
        Raises:
            SourceValidationError: If required parameters are missing.
            SourceAuthenticationError: If API credentials are invalid.
            SourceNotFoundError: If symbol or resource not found.
            SourceRateLimitError: If rate limit exceeded.
            SourceError: On any other error.
        """
        if "endpoint" not in kwargs:
            raise SourceValidationError(self.name, "endpoint parameter is required")
        
        endpoint = kwargs["endpoint"]
        method = kwargs.get("method", "GET")
        
        # Build request params (excluding 'endpoint' and 'method')
        request_params = {k: v for k, v in kwargs.items() if k not in ("endpoint", "method")}
        
        # Fetch with retry
        def fetch_func() -> dict[str, Any]:
            return self._fetch_endpoint(endpoint, method, request_params)
        
        payload = self._fetch_with_retry(fetch_func)
        
        return self._build_envelope(endpoint, request_params, payload)

    def fetch_bars(
        self,
        symbol: str,
        timeframe: str = "1Min",
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> RawEnvelope:
        """Fetch market data bars for a symbol.
        
        Args:
            symbol: Stock symbol (e.g., "AAPL").
            timeframe: Bar timeframe (e.g., "1Min", "5Min", "1Hour", "1Day").
            start: Start datetime (ISO8601 format, optional).
            end: End datetime (ISO8601 format, optional).
            limit: Maximum number of bars (optional).
            
        Returns:
            RawEnvelope with bar data (OHLCV).
        """
        params: dict[str, Any] = {
            "endpoint": f"v2/stocks/{symbol}/bars",
            "timeframe": timeframe,
        }
        
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit:
            params["limit"] = limit
        
        return self.fetch(**params)

    def fetch_latest_quote(self, symbol: str) -> RawEnvelope:
        """Fetch latest quote for a symbol.
        
        Args:
            symbol: Stock symbol (e.g., "AAPL").
            
        Returns:
            RawEnvelope with latest bid/ask data.
        """
        return self.fetch(endpoint=f"v2/stocks/{symbol}/quotes/latest")

    def fetch_account(self) -> RawEnvelope:
        """Fetch account information.
        
        Returns:
            RawEnvelope with account details (buying power, equity, etc.).
            
        Note:
            In paper mode, returns paper account information.
        """
        return self.fetch(endpoint="v2/account")

    def fetch_positions(self) -> RawEnvelope:
        """Fetch all open positions.
        
        Returns:
            RawEnvelope with position data.
            
        Note:
            In paper mode, returns paper positions.
        """
        return self.fetch(endpoint="v2/positions")

    def fetch_position(self, symbol_or_asset_id: str) -> RawEnvelope:
        """Fetch position for a specific symbol.
        
        Args:
            symbol_or_asset_id: Stock symbol or asset ID.
            
        Returns:
            RawEnvelope with position data.
        """
        return self.fetch(endpoint=f"v2/positions/{symbol_or_asset_id}")

    def fetch_orders(
        self,
        status: str = "all",
        limit: int = 100,
    ) -> RawEnvelope:
        """Fetch orders.
        
        Args:
            status: Order status filter ("open", "closed", "all").
            limit: Maximum number of orders to return.
            
        Returns:
            RawEnvelope with order data.
            
        Note:
            In paper mode, returns paper orders.
        """
        return self.fetch(endpoint="v2/orders", status=status, limit=limit)

    def fetch_order(self, order_id: str) -> RawEnvelope:
        """Fetch a specific order by ID.
        
        Args:
            order_id: Order ID.
            
        Returns:
            RawEnvelope with order details.
        """
        return self.fetch(endpoint=f"v2/orders/{order_id}")
    
    def get_order(self, order_id: str) -> RawEnvelope:
        """Get order by ID (alias for fetch_order).
        
        Args:
            order_id: Order ID.
            
        Returns:
            RawEnvelope with order details.
        """
        return self.fetch_order(order_id)
    
    def submit_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        qty: int,
        time_in_force: str,
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        """Submit order to broker (paper mode only).
        
        Args:
            symbol: Stock symbol.
            side: Order side (buy/sell).
            order_type: Order type (market/limit).
            qty: Quantity (shares).
            time_in_force: Time in force (day/gtc/etc).
            limit_price: Limit price if order_type=limit.
            
        Returns:
            Broker order response (dict with 'id', 'status', etc).
            
        Raises:
            ValueError: If paper_mode is False.
            SourceValidationError: If parameters are invalid.
        """
        if not self.paper_mode:
            raise ValueError("Live order submission is blocked. Use paper_mode=True.")
        
        # Build order payload
        order_payload = {
            "symbol": symbol,
            "side": side.lower(),
            "type": order_type.lower(),
            "qty": qty,
            "time_in_force": time_in_force.lower(),
        }
        
        if order_type.lower() == "limit" and limit_price is not None:
            order_payload["limit_price"] = limit_price
        
        # Submit via POST
        envelope = self.fetch(endpoint="v2/orders", method="POST", **order_payload)
        return envelope.get("payload", {})

    def _fetch_endpoint(
        self,
        endpoint: str,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch data from a broker endpoint.
        
        Args:
            endpoint: API endpoint path.
            method: HTTP method (GET, POST, etc.).
            params: Query parameters or request body.
            
        Returns:
            Response data as dict.
            
        Raises:
            SourceError: On any error (normalized).
        """
        url = f"{self.base_url}/{endpoint}"
        
        # Broker-specific auth headers (Alpaca format)
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }
        
        try:
            with httpx.Client(timeout=self.retry_config.timeout) as client:
                if method == "GET":
                    response = client.get(url, headers=headers, params=params)
                elif method == "POST":
                    response = client.post(url, headers=headers, json=params)
                elif method == "DELETE":
                    response = client.delete(url, headers=headers)
                else:
                    raise SourceValidationError(
                        self.name,
                        f"unsupported HTTP method: {method}",
                    )
            
            # Handle error status codes
            if response.status_code == 401:
                raise SourceAuthenticationError(
                    self.name,
                    "invalid API credentials",
                )
            elif response.status_code == 403:
                raise SourceAuthenticationError(
                    self.name,
                    "API key does not have permission for this operation",
                )
            elif response.status_code == 404:
                raise SourceNotFoundError(
                    self.name,
                    f"resource not found: {endpoint}",
                )
            elif response.status_code == 422:
                # Unprocessable entity (validation error)
                try:
                    error_data = response.json()
                    error_message = error_data.get("message", "validation error")
                except Exception:
                    error_message = "validation error"
                
                raise SourceValidationError(
                    self.name,
                    error_message,
                )
            elif response.status_code == 429:
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
            elif response.status_code not in (200, 201, 204):
                raise SourceResponseError(
                    self.name,
                    f"unexpected status code: {response.status_code}",
                )
            
            # Parse JSON response (if present)
            if response.status_code == 204:
                return {}
            
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
