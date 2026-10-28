"""Tests for scripts/rebuild_pnl_state_from_broker.fetch_all_filled_orders()
(AUDIT FIX, 2026-08-23, partial-fill-before-cancel).

Background: this function used to filter orders to status == 'filled'
ONLY, silently dropping orders that were PARTIALLY filled before being
cancelled/expired (a real, common Alpaca paper-trading pattern: an order
that gets partially filled and then cancelled by the broker or expires
still has a nonzero filled_qty and represents a real, PnL-relevant fill).
Confirmed live on this account: 4 such orders (ADBE/MSFT/CDNS/AVGO, all
2026-06-01) totaling 402 real shares -- every one of them was the MISSING
buy leg for a sell that later appeared in the filtered order list, causing
match_buy_sell_orders() to mismatch that sell against an unrelated LATER
buy fill and produce an impossible entry_time > exit_time trade.

Fix: filter to `float(filled_qty or 0) > 0` instead of `status == 'filled'`
-- this is a strict superset (every status=='filled' order also has
filled_qty > 0), so no previously-included order is now excluded.
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from scripts.rebuild_pnl_state_from_broker import fetch_all_filled_orders


class _FakeEnvelope:
    def __init__(self, payload):
        self.payload = payload


def _make_broker(orders: list[dict]) -> Mock:
    broker = Mock()
    broker.fetch_all_orders.return_value = _FakeEnvelope({
        "orders": orders,
        "page_count": 1,
        "truncated": False,
    })
    return broker


def _order(
    order_id: str,
    symbol: str,
    side: str,
    status: str,
    qty: float,
    filled_qty: float,
    filled_avg_price: float | None = 100.0,
    created_at: str = "2026-06-01T00:00:00Z",
) -> dict:
    return {
        "id": order_id,
        "symbol": symbol,
        "side": side,
        "status": status,
        "qty": qty,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price,
        "created_at": created_at,
    }


class TestFetchAllFilledOrdersIncludesPartialFillsBeforeCancel:
    def test_includes_canceled_order_with_nonzero_filled_qty(self) -> None:
        orders = [
            _order("o1", "ADBE", "buy", status="canceled", qty=242, filled_qty=101),
            _order("o2", "ADBE", "sell", status="filled", qty=101, filled_qty=101),
        ]
        broker = _make_broker(orders)

        result = fetch_all_filled_orders(broker)

        ids = {o["id"] for o in result}
        assert "o1" in ids, "a canceled order with filled_qty > 0 must be included (real partial fill)"
        assert "o2" in ids

    def test_excludes_canceled_order_with_zero_filled_qty(self) -> None:
        orders = [
            _order("o1", "AAPL", "buy", status="canceled", qty=10, filled_qty=0),
            _order("o2", "AAPL", "sell", status="filled", qty=5, filled_qty=5),
        ]
        broker = _make_broker(orders)

        result = fetch_all_filled_orders(broker)

        ids = {o["id"] for o in result}
        assert "o1" not in ids, "a fully-unfilled canceled order (never traded) must still be excluded"
        assert "o2" in ids

    def test_includes_all_status_filled_orders_unconditionally(self) -> None:
        """Regression guard: the new filter must be a strict superset of the
        old status=='filled' filter -- no previously-included order should
        now be excluded."""
        orders = [
            _order("o1", "MSFT", "buy", status="filled", qty=100, filled_qty=100),
            _order("o2", "MSFT", "sell", status="filled", qty=100, filled_qty=100),
        ]
        broker = _make_broker(orders)

        result = fetch_all_filled_orders(broker)

        assert len(result) == 2

    def test_excludes_expired_order_with_zero_filled_qty(self) -> None:
        orders = [
            _order("o1", "TSLA", "buy", status="expired", qty=50, filled_qty=0),
        ]
        broker = _make_broker(orders)

        result = fetch_all_filled_orders(broker)

        assert result == []

    def test_includes_expired_order_with_nonzero_filled_qty(self) -> None:
        orders = [
            _order("o1", "TSLA", "buy", status="expired", qty=50, filled_qty=30),
        ]
        broker = _make_broker(orders)

        result = fetch_all_filled_orders(broker)

        assert len(result) == 1
        assert result[0]["id"] == "o1"

    def test_handles_missing_filled_qty_field_gracefully(self) -> None:
        """An order dict missing the filled_qty key entirely (not just 0)
        must not raise and must be excluded (no fill occurred)."""
        orders = [{"id": "o1", "symbol": "NVDA", "side": "buy", "status": "canceled", "qty": 10}]
        broker = _make_broker(orders)

        result = fetch_all_filled_orders(broker)

        assert result == []


class TestFetchAllFilledOrdersRealAccountScenario:
    def test_reproduces_the_adbe_partial_fill_cancel_scenario(self) -> None:
        """End-to-end reproduction of the exact live scenario that motivated
        this fix (2026-08-23 equity-bridge investigation): an ADBE buy for
        242 shares partially fills 101 shares then gets cancelled; a later
        sell of exactly 101 shares is the correct FIFO match for that fill,
        not some unrelated later buy.
        """
        orders = [
            _order(
                "adbe-buy-canceled", "ADBE", "buy", status="canceled",
                qty=242, filled_qty=101, filled_avg_price=270.0,
                created_at="2026-06-01T20:58:28Z",
            ),
            _order(
                "adbe-sell-1", "ADBE", "sell", status="filled",
                qty=101, filled_qty=101, filled_avg_price=256.25,
                created_at="2026-06-03T17:01:31Z",
            ),
            _order(
                "adbe-buy-later", "ADBE", "buy", status="filled",
                qty=95, filled_qty=95, filled_avg_price=221.62,
                created_at="2026-07-07T19:55:43Z",
            ),
        ]
        broker = _make_broker(orders)

        result = fetch_all_filled_orders(broker)
        ids = {o["id"] for o in result}

        assert ids == {"adbe-buy-canceled", "adbe-sell-1", "adbe-buy-later"}

        # Feed into the real FIFO matcher to confirm the chronology is now correct.
        from scripts.rebuild_pnl_state_from_broker import match_buy_sell_orders

        # match_buy_sell_orders() reads filled_at, not created_at; supply it.
        for o, filled_at in zip(
            result,
            ["2026-06-01T20:58:30Z", "2026-06-03T17:01:33Z", "2026-07-07T19:55:50Z"],
        ):
            o["filled_at"] = filled_at

        closed_trades, _open = match_buy_sell_orders(result, corporate_actions=[])
        adbe_trades = [t for t in closed_trades if t["symbol"] == "ADBE"]
        assert len(adbe_trades) == 1
        trade = adbe_trades[0]
        assert trade["entry_time"] < trade["exit_time"], (
            "the ADBE 101-share sell must FIFO-match against its own partial-fill "
            "buy (canceled order), not the unrelated later 95-share buy -- this is "
            "exactly the impossible-chronology bug this fix resolves"
        )
        assert trade["qty"] == 101
