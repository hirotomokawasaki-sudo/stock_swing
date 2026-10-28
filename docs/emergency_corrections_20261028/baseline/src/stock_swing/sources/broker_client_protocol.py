"""Broker client structural interface contract (IBKR migration Track A-2).

This module defines the minimal set of methods that any broker client
implementation (Alpaca, IBKR, or otherwise) must provide in order to be
usable by the execution layer (`PaperExecutor`, `Reconciler`,
`LiveGuardedExecutor`, `ProductionExecutor`) and by `HybridDataFetcher`.

Background
----------
Historically, `PaperExecutor` / `Reconciler` / etc. were type-hinted against
the concrete `stock_swing.sources.broker_client.BrokerClient` (an Alpaca-only
REST implementation). In practice, those call sites only ever use a narrow
subset of methods on that object (duck typing). This module makes that
narrow contract explicit as a `typing.Protocol`, so that:

  1. A future `IBKRBrokerClient` (or any other broker implementation) can be
     substituted at the execution-layer boundary without any changes to
     `PaperExecutor` / `Reconciler` / `LiveGuardedExecutor` /
     `ProductionExecutor` / `HybridDataFetcher`, as long as it implements
     this Protocol.
  2. The contract is documented and testable (see
     `tests/unit/test_broker_client_protocol.py`), instead of being an
     implicit assumption spread across call sites.

This is a **pure typing/documentation change**. It does not alter the
behavior of `BrokerClient` (Alpaca) in any way. `BrokerClient` already
satisfies this Protocol structurally (verified by a runtime `isinstance()`
check in the test suite, since the Protocol is declared
`@runtime_checkable`).

See docs/broker_migration_ibkr_plan.md (Track A-2) and
docs/broker_migration_alpaca_assumptions_audit.md (Track A-1) for the full
migration context.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from stock_swing.core.types import RawEnvelope


@runtime_checkable
class BrokerClientProtocol(Protocol):
    """Structural interface required by the execution/reconciliation layer.

    Any object providing these methods with matching signatures can be used
    wherever the execution layer currently expects a `BrokerClient`
    (Alpaca). This does not require inheriting from this class explicitly;
    Python's structural typing (duck typing) plus `@runtime_checkable`
    allows `isinstance(obj, BrokerClientProtocol)` checks against any
    conforming object.

    Notes on semantics that implementations must preserve:
      - All `fetch_*` methods return a `RawEnvelope` (or an object exposing
        a `.payload` attribute with equivalent shape) so that existing call
        sites using `env.payload if hasattr(env, "payload") else env` keep
        working unchanged.
      - `submit_order` / `cancel_order` / `get_order` return plain `dict`
        payloads (broker response body), not `RawEnvelope`, matching the
        current `BrokerClient` (Alpaca) behavior.
      - Implementations MUST continue to enforce paper-mode safety
        (blocking live order submission unless explicitly and safely
        configured) per `docs/policies/EXECUTION_POLICY.md`.
    """

    def fetch_account(self) -> RawEnvelope:
        """Return account snapshot (equity, buying_power, status, ...)."""
        ...

    def fetch_positions(self) -> RawEnvelope:
        """Return all open positions."""
        ...

    def fetch_position(self, symbol_or_asset_id: str) -> RawEnvelope:
        """Return a single position by symbol or broker asset id."""
        ...

    def fetch_orders(self, status: str = "all", limit: int = 100) -> RawEnvelope:
        """Return orders filtered by status."""
        ...

    def fetch_order(self, order_id: str) -> RawEnvelope:
        """Return a single order by broker order id."""
        ...

    def get_order(self, order_id: str) -> RawEnvelope:
        """Alias for fetch_order (used by Reconciler)."""
        ...

    def submit_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        qty: int,
        time_in_force: str,
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        """Submit an order and return the broker's raw response dict."""
        ...

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an open order by broker order id."""
        ...

    def fetch_bars(
        self,
        symbol: str,
        timeframe: str = "1Min",
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> RawEnvelope:
        """Return OHLCV bars for a symbol."""
        ...

    def fetch_latest_quote(self, symbol: str) -> RawEnvelope:
        """Return the latest bid/ask quote for a symbol."""
        ...
