"""Tests for BrokerClient.fetch_all_orders() (AUDIT FIX, 2026-08-23).

Background: fetch_orders(limit=500) is a SINGLE un-paginated call. Alpaca's
v2/orders endpoint silently returns only the most recent `limit` orders once
an account has more than that many total orders -- no pagination, no
warning. This was traced as the dominant root cause of ~$150K+ of PnL
sitting in quarantined_trades with impossible entry>exit chronology: the
FIFO buy/sell matcher in rebuild_pnl_state_from_broker.py has no way to
detect a missing buy leg when the order history window is truncated.

fetch_all_orders() walks the account's full order history using
direction=asc + after=<cursor> pagination so callers that need the complete
history (e.g. a ledger rebuild) don't silently operate on a truncated
window.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.retry import RetryConfig

pytest.importorskip("httpx")

TEST_RETRY = RetryConfig(max_attempts=1, initial_delay=0.01, max_delay=0.01)


def create_client() -> BrokerClient:
    return BrokerClient(api_key="test_key", api_secret="test_secret", retry_config=TEST_RETRY)


def _order(order_id: str, created_at: str, status: str = "filled") -> dict:
    return {"id": order_id, "created_at": created_at, "status": status, "symbol": "AAPL"}


def _mock_response(payload) -> Mock:
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


@patch("httpx.Client")
def test_fetch_all_orders_single_short_page_no_pagination_needed(mock_client_class: Mock) -> None:
    """A single page shorter than page_size means history is complete after page 1."""
    orders = [_order(f"o{i}", f"2026-05-{10+i:02d}T00:00:00Z") for i in range(3)]
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = _mock_response(orders)
    mock_client_class.return_value = mock_client

    client = create_client()
    env = client.fetch_all_orders(page_size=500)

    assert mock_client.get.call_count == 1
    assert env.payload["truncated"] is False
    assert env.payload["page_count"] == 1
    assert len(env.payload["orders"]) == 3


@patch("httpx.Client")
def test_fetch_all_orders_walks_multiple_pages(mock_client_class: Mock) -> None:
    """Regression: this is the exact real-world scenario that motivated the
    fix -- a full page (page_size) followed by a shorter final page must
    result in ALL orders being returned, not just the first page's worth.
    """
    page1 = [_order(f"a{i}", f"2026-05-{10 + i:02d}T00:00:00Z") for i in range(5)]
    page2 = [_order(f"b{i}", f"2026-07-{1 + i:02d}T00:00:00Z") for i in range(2)]

    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = [_mock_response(page1), _mock_response(page2)]
    mock_client_class.return_value = mock_client

    client = create_client()
    env = client.fetch_all_orders(page_size=5)

    assert mock_client.get.call_count == 2
    assert env.payload["truncated"] is False
    assert env.payload["page_count"] == 2
    ids = {o["id"] for o in env.payload["orders"]}
    assert ids == {"a0", "a1", "a2", "a3", "a4", "b0", "b1"}


@patch("httpx.Client")
def test_fetch_all_orders_advances_cursor_using_after_param(mock_client_class: Mock) -> None:
    """The second page's request must use `after` = the last order's
    created_at from the first page, and direction=asc, so the walk moves
    strictly forward through time rather than re-fetching the same window.
    """
    page1 = [_order("a0", "2026-05-10T00:00:00Z"), _order("a1", "2026-05-11T00:00:00Z")]
    page2: list = []

    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = [_mock_response(page1), _mock_response(page2)]
    mock_client_class.return_value = mock_client

    client = create_client()
    client.fetch_all_orders(page_size=2)

    assert mock_client.get.call_count == 2
    second_call_params = mock_client.get.call_args_list[1].kwargs.get("params", {})
    assert second_call_params.get("direction") == "asc"
    assert second_call_params.get("after") == "2026-05-11T00:00:00Z"


@patch("httpx.Client")
def test_fetch_all_orders_deduplicates_by_id(mock_client_class: Mock) -> None:
    """If a page boundary happens to re-return an order (e.g. same-timestamp
    tie at the cursor), it must not be double-counted.
    """
    page1 = [_order("dup", "2026-05-10T00:00:00Z"), _order("a1", "2026-05-10T00:00:00Z")]
    page2 = [_order("dup", "2026-05-10T00:00:00Z")]  # boundary re-return, no new orders

    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = [_mock_response(page1), _mock_response(page2)]
    mock_client_class.return_value = mock_client

    client = create_client()
    env = client.fetch_all_orders(page_size=2)

    # Second page had zero NEW orders -> walk stops there (no infinite loop),
    # and "dup" appears exactly once in the final result.
    ids = [o["id"] for o in env.payload["orders"]]
    assert ids.count("dup") == 1
    assert len(env.payload["orders"]) == 2


@patch("httpx.Client")
def test_fetch_all_orders_empty_history(mock_client_class: Mock) -> None:
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = _mock_response([])
    mock_client_class.return_value = mock_client

    client = create_client()
    env = client.fetch_all_orders()

    assert env.payload["orders"] == []
    assert env.payload["truncated"] is False


@patch("httpx.Client")
def test_fetch_all_orders_hits_max_pages_reports_truncated(mock_client_class: Mock) -> None:
    """If the safety cap is hit before a short/empty page is seen, the
    result MUST be flagged truncated=True so callers can't mistake a
    still-incomplete walk for a complete one.
    """
    # Every page is exactly page_size long with fresh ids, so the loop never
    # naturally terminates before hitting max_pages.
    def make_page(page_num: int) -> list:
        return [_order(f"p{page_num}_{i}", f"2026-0{page_num}-0{i+1}T00:00:00Z") for i in range(3)]

    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.side_effect = [_mock_response(make_page(i)) for i in range(1, 4)]
    mock_client_class.return_value = mock_client

    client = create_client()
    env = client.fetch_all_orders(page_size=3, max_pages=3)

    assert mock_client.get.call_count == 3
    assert env.payload["truncated"] is True
    assert env.payload["page_count"] == 3


@patch("httpx.Client")
def test_fetch_all_orders_result_sorted_ascending_by_created_at(mock_client_class: Mock) -> None:
    page1 = [_order("late", "2026-05-15T00:00:00Z"), _order("early", "2026-05-10T00:00:00Z")]

    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = _mock_response(page1)
    mock_client_class.return_value = mock_client

    client = create_client()
    env = client.fetch_all_orders(page_size=500)

    ids_in_order = [o["id"] for o in env.payload["orders"]]
    assert ids_in_order == ["early", "late"]


@patch("httpx.Client")
def test_fetch_all_orders_status_filter_passed_through(mock_client_class: Mock) -> None:
    mock_client = Mock()
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client.get.return_value = _mock_response([])
    mock_client_class.return_value = mock_client

    client = create_client()
    client.fetch_all_orders(status="closed")

    call_params = mock_client.get.call_args.kwargs.get("params", {})
    assert call_params.get("status") == "closed"
