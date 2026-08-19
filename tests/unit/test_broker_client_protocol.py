"""Tests for BrokerClientProtocol (IBKR migration Track A-2).

Purpose: verify that the existing Alpaca `BrokerClient` structurally
satisfies `BrokerClientProtocol`, and that the Protocol's method surface
matches exactly what the execution layer (`PaperExecutor` / `Reconciler` /
`LiveGuardedExecutor` / `ProductionExecutor` / `HybridDataFetcher`) actually
calls. This is a pure interface-contract test; it does not exercise any
network I/O.

See docs/broker_migration_ibkr_plan.md (Track A-2) for migration context.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("httpx")

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.broker_client_protocol import BrokerClientProtocol
from stock_swing.sources.retry import RetryConfig

TEST_RETRY = RetryConfig(max_attempts=1, initial_delay=0.01, max_delay=0.01)


def _make_client() -> BrokerClient:
    return BrokerClient(api_key="test_key", api_secret="test_secret", retry_config=TEST_RETRY)


class TestBrokerClientSatisfiesProtocol:
    """Acceptance: BrokerClient (Alpaca) must satisfy BrokerClientProtocol
    structurally, with no behavior changes (this is a pure typing addition).
    """

    def test_alpaca_broker_client_isinstance_of_protocol(self) -> None:
        client = _make_client()
        assert isinstance(client, BrokerClientProtocol), (
            "BrokerClient (Alpaca) must structurally satisfy BrokerClientProtocol "
            "so that a future IBKRBrokerClient can be substituted without "
            "touching PaperExecutor/Reconciler/etc."
        )

    @pytest.mark.parametrize(
        "method_name",
        [
            "fetch_account",
            "fetch_positions",
            "fetch_position",
            "fetch_orders",
            "fetch_order",
            "get_order",
            "submit_order",
            "cancel_order",
            "fetch_bars",
            "fetch_latest_quote",
        ],
    )
    def test_alpaca_broker_client_has_protocol_method(self, method_name: str) -> None:
        client = _make_client()
        assert hasattr(client, method_name), (
            f"BrokerClient is missing protocol method {method_name!r}"
        )
        assert callable(getattr(client, method_name))


class TestProtocolMethodSignaturesMatchImplementation:
    """Acceptance: each Protocol method signature must match the parameter
    names used by BrokerClient (Alpaca), since execution-layer call sites
    invoke some of these with keyword arguments.
    """

    @pytest.mark.parametrize(
        "method_name",
        [
            "fetch_account",
            "fetch_positions",
            "fetch_position",
            "fetch_orders",
            "fetch_order",
            "get_order",
            "submit_order",
            "cancel_order",
            "fetch_bars",
            "fetch_latest_quote",
        ],
    )
    def test_parameter_names_match(self, method_name: str) -> None:
        protocol_sig = inspect.signature(getattr(BrokerClientProtocol, method_name))
        impl_sig = inspect.signature(getattr(BrokerClient, method_name))

        protocol_params = [p for p in protocol_sig.parameters if p != "self"]
        impl_params = [p for p in impl_sig.parameters if p != "self"]

        assert protocol_params == impl_params, (
            f"{method_name}: protocol params {protocol_params} != "
            f"implementation params {impl_params}"
        )


class TestFakeBrokerConformsWithoutInheritance:
    """Acceptance: a completely independent class (simulating a future
    IBKRBrokerClient) satisfies BrokerClientProtocol via structural typing
    alone, without inheriting from BrokerClient or the Protocol.
    """

    def test_fake_ibkr_style_client_is_protocol_instance(self) -> None:
        class FakeIBKRBrokerClient:
            """Minimal stand-in with the right method surface, no inheritance."""

            def fetch_account(self):
                return None

            def fetch_positions(self):
                return None

            def fetch_position(self, symbol_or_asset_id):
                return None

            def fetch_orders(self, status="all", limit=100):
                return None

            def fetch_order(self, order_id):
                return None

            def get_order(self, order_id):
                return None

            def submit_order(self, symbol, side, order_type, qty, time_in_force, limit_price=None):
                return {}

            def cancel_order(self, order_id):
                return {}

            def fetch_bars(self, symbol, timeframe="1Min", start=None, end=None, limit=None):
                return None

            def fetch_latest_quote(self, symbol):
                return None

        fake = FakeIBKRBrokerClient()
        assert isinstance(fake, BrokerClientProtocol), (
            "A structurally-conforming class (e.g. a future IBKRBrokerClient) "
            "must satisfy BrokerClientProtocol without inheritance, proving "
            "the execution layer can accept it as a drop-in replacement."
        )

    def test_incomplete_fake_client_is_not_protocol_instance(self) -> None:
        """Boundary: a class missing a required method must NOT satisfy the
        protocol (guards against the protocol being accidentally too loose).
        """

        class IncompleteFakeClient:
            def fetch_account(self):
                return None

            def fetch_positions(self):
                return None

            # Missing: fetch_position, fetch_orders, fetch_order, get_order,
            # submit_order, cancel_order, fetch_bars, fetch_latest_quote

        incomplete = IncompleteFakeClient()
        assert not isinstance(incomplete, BrokerClientProtocol)
