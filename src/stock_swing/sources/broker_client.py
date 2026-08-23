"""Broker source client for paper-safe market data and order interface foundations.

Provides access to broker API for market data, paper order submission, and reconciliation.
This is a FOUNDATION layer for later paper execution integration.

CRITICAL: This implementation is paper/research safe only. Live execution behavior
is NOT implemented and must NOT be enabled without explicit approval and safety validation.

See EXECUTION_POLICY.md for execution constraints and requirements.
"""

from __future__ import annotations

import os
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
        base_url: str | None = None,
    ) -> None:
        """Initialize Broker client.
        
        Args:
            api_key: Broker API key (required).
            api_secret: Broker API secret (required).
            paper_mode: If True, use paper trading endpoints (default: True).
                SAFETY: Live mode endpoints are blocked in this implementation.
            retry_config: Custom retry configuration.
            base_url: Optional broker API base URL override. If omitted, resolves from
                BROKER_BASE_URL environment variable, then falls back to the default
                paper endpoint.
            
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
        resolved_base_url = (base_url or os.getenv("BROKER_BASE_URL") or self.base_url_paper).strip()
        self.base_url = resolved_base_url.rstrip("/")

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
        from datetime import datetime, timedelta, timezone

        request_params: dict[str, Any] = {
            "symbol": symbol,
            "timeframe": timeframe,
        }
        api_params: dict[str, Any] = {
            "timeframe": timeframe,
            "feed": "iex",
            "adjustment": "raw",
        }

        if end is None:
            end = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        request_params["end"] = end
        api_params["end"] = end

        if start is None:
            lookback_days = max((limit or 20) * 3, 30)
            start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat().replace("+00:00", "Z")
        request_params["start"] = start
        api_params["start"] = start

        if limit:
            request_params["limit"] = limit
            api_params["limit"] = limit

        payload = self._fetch_market_data_endpoint(
            f"v2/stocks/{symbol}/bars",
            api_params,
            not_found_message=f"resource not found: v2/stocks/{symbol}/bars",
        )
        return self._build_envelope(f"v2/stocks/{symbol}/bars", request_params, payload)

    def fetch_latest_quote(self, symbol: str) -> RawEnvelope:
        """Fetch latest quote for a symbol.

        Args:
            symbol: Stock symbol (e.g., "AAPL").

        Returns:
            RawEnvelope with latest bid/ask data.

        Note:
            2026-08-01 fix: quotes (like bars) live on Alpaca's market-data
            host (data.alpaca.markets), NOT the trading-account host
            (self.base_url / paper-api.alpaca.markets). The previous
            implementation routed this through self.fetch(), which hits
            self.base_url and always 404'd ("resource not found"), silently
            making every quote lookup fail. Callers (e.g. paper_demo.py's
            get_mid_price()) caught the exception and fell back to 0.0,
            which — combined with the 2026-07-29 FIX-002 change that blocks
            BUYs outright when price is unavailable — halted all new BUY
            submissions in production from 2026-07-29 18:44 JST onward
            without raising any error.
        """
        endpoint = f"v2/stocks/{symbol}/quotes/latest"
        payload = self._fetch_market_data_endpoint(
            endpoint,
            {"feed": "iex"},
            not_found_message=f"resource not found: {endpoint}",
        )
        return self._build_envelope(endpoint, {"symbol": symbol}, payload)

    def _fetch_market_data_endpoint(
        self,
        path: str,
        params: dict[str, Any],
        *,
        not_found_message: str,
    ) -> dict[str, Any]:
        """Shared GET helper for Alpaca market-data endpoints (data.alpaca.markets).

        Used by fetch_bars() and fetch_latest_quote(). Both live on the
        market-data host, distinct from self.base_url (the trading-account
        host used by fetch_account/fetch_positions/fetch_orders/submit_order).
        """
        data_url = f"https://data.alpaca.markets/{path.lstrip('/')}"
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }

        def fetch_func() -> dict[str, Any]:
            try:
                with httpx.Client(timeout=self.retry_config.timeout) as client:
                    response = client.get(data_url, headers=headers, params=params)
            except Exception as e:
                raise SourceConnectionError(self.name, f"failed to fetch {path}: {e}", original_error=e)

            if response.status_code == 401:
                raise SourceAuthenticationError(self.name, "invalid API credentials")
            if response.status_code == 403:
                raise SourceAuthenticationError(self.name, "API key does not have permission for this operation")
            if response.status_code == 404:
                raise SourceNotFoundError(self.name, not_found_message)
            if response.status_code == 422:
                try:
                    error_data = response.json()
                    error_message = error_data.get("message", "validation error")
                except Exception:
                    error_message = "validation error"
                raise SourceValidationError(self.name, error_message)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                retry_after_int = int(retry_after) if retry_after else None
                raise SourceRateLimitError(self.name, "rate limit exceeded", retry_after=retry_after_int)
            if response.status_code >= 500:
                raise SourceServerError(self.name, f"server error: {response.status_code}")
            if response.status_code not in (200, 201, 204):
                raise SourceResponseError(self.name, f"unexpected status code: {response.status_code}")
            if response.status_code == 204:
                return {}
            try:
                return response.json()
            except Exception as e:
                raise SourceResponseError(self.name, f"failed to parse JSON response: {e}", original_error=e)

        return self._fetch_with_retry(fetch_func)

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

        AUDIT FIX (2026-08-23): Alpaca's v2/orders endpoint returns at most
        `limit` orders (hard cap 500) with NO pagination applied by this
        single call -- by default it returns the MOST RECENT `limit` orders
        (descending order, no `after`/`direction` params sent). Once an
        account has more than `limit` total orders, calling this with
        limit=500 SILENTLY DROPS the oldest orders rather than raising or
        warning. This was confirmed live: a single fetch_orders(limit=500)
        call against this account's paper history returned orders starting
        2026-05-21, while genuinely older filled orders exist back to
        2026-05-12 -- a ~9-day, ~200-order gap. rebuild_pnl_state_from_
        broker.py's FIFO buy/sell matcher (match_buy_sell_orders()) has no
        way to detect a missing buy leg; when an old buy fill is silently
        missing, it FIFO-matches a sell against whatever buy fill happens to
        still be in the truncated window instead -- producing closed trades
        with entry_time AFTER exit_time (impossible chronology) and/or
        multiple buy legs incorrectly matched against the same sell fill.
        This was traced as the dominant root cause of the ~$150K+ PnL sitting
        in quarantined_trades (2026-08-23 equity-bridge audit): ~70 of 101
        quarantined trades share an exit_broker_order_id with at least one
        other quarantined trade, and the earliest entry_time across all
        trades (2026-05-13) predates this truncated window's earliest order
        (2026-05-21). Use fetch_all_orders() (below) for anything that needs
        the COMPLETE order history (e.g. ledger rebuild) instead of this
        method directly. This method's single-page behavior is left
        unchanged for existing callers that intentionally only want the most
        recent N orders (e.g. a quick status check).
        """
        return self.fetch(endpoint="v2/orders", status=status, limit=limit)

    def fetch_all_orders(
        self,
        status: str = "all",
        page_size: int = 500,
        max_pages: int = 50,
        after: str | None = None,
    ) -> RawEnvelope:
        """Fetch the COMPLETE order history via ascending-time pagination.

        AUDIT FIX (2026-08-23): see fetch_orders()'s docstring above for why
        a single fetch_orders(limit=500) call silently truncates to only the
        most recent `limit` orders once an account exceeds that many total
        orders. This method walks forward through the account's full order
        history using Alpaca's `direction=asc` + `after=<cursor>` pagination
        (confirmed working against the live paper account: a two-page walk
        starting at after="2000-01-01T00:00:00Z" recovered 691 total orders
        -- 613 filled -- spanning 2026-05-12 through 2026-08-20, vs. only
        500/422 from a single un-paginated call).

        Args:
            status: Order status filter ("open", "closed", "all").
            page_size: Orders per page (Alpaca's hard max is 500).
            max_pages: Safety cap on the number of pages walked, so a
                pagination bug (e.g. the cursor failing to advance) cannot
                spin forever. 50 pages * 500 = 25,000 orders, far beyond any
                plausible order count for this account; hitting this cap is
                itself worth surfacing as a warning via the returned
                envelope's payload (see "truncated" key below), not a
                silent drop.
            after: Optional ISO-8601 cursor to start from (exclusive). When
                omitted, starts from the epoch so the very first page covers
                the account's entire history.

        Returns:
            RawEnvelope whose payload is
            {"orders": [...], "page_count": int, "truncated": bool}.
            `orders` is deduplicated by order id and sorted ascending by
            created_at. `truncated=True` means max_pages was hit before a
            short/empty page was seen -- callers MUST treat this as
            "history may still be incomplete", not silently proceed as if
            it were complete.
        """
        cursor = after or "2000-01-01T00:00:00Z"
        all_orders: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        page_count = 0
        truncated = False

        for page_count in range(1, max_pages + 1):
            page_env = self.fetch(
                endpoint="v2/orders",
                status=status,
                limit=page_size,
                direction="asc",
                after=cursor,
            )
            batch = page_env.payload if isinstance(page_env.payload, list) else []
            new_in_batch = 0
            for order in batch:
                order_id = order.get("id")
                if order_id and order_id not in seen_ids:
                    seen_ids.add(order_id)
                    all_orders.append(order)
                    new_in_batch += 1

            if not batch or new_in_batch == 0:
                # Empty page, or a page that returned nothing new (cursor
                # stopped advancing) -- either way, the walk is complete.
                break

            cursor = batch[-1].get("created_at") or cursor

            if len(batch) < page_size:
                # Short page: this was the last page.
                break
        else:
            # Loop completed all max_pages iterations without an early
            # break -- history may still be incomplete.
            truncated = True

        all_orders.sort(key=lambda o: o.get("created_at") or "")

        return self._build_envelope(
            "v2/orders (paginated)",
            {"status": status, "page_size": page_size, "max_pages": max_pages, "after": after},
            {"orders": all_orders, "page_count": page_count, "truncated": truncated},
        )

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
    
    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an open order by ID (paper mode only).

        Returns the broker response dict, or raises on error.
        """
        if not self.paper_mode:
            raise ValueError("Live order cancellation is blocked. Use paper_mode=True.")
        envelope = self.fetch(endpoint=f"v2/orders/{order_id}", method="DELETE")
        return envelope.payload if hasattr(envelope, "payload") else envelope

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
        return envelope.payload

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
        base_url = self.base_url.rstrip("/")
        endpoint_path = endpoint.lstrip("/")
        if base_url.endswith("/v2") and endpoint_path.startswith("v2/"):
            endpoint_path = endpoint_path[3:]
        url = f"{base_url}/{endpoint_path}"
        
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
