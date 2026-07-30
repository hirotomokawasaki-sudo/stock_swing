"""Tests for P3-D: append-only trade event store."""
from __future__ import annotations

from pathlib import Path

from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.tracking.trade_event_store import TradeEvent, TradeEventStore


def test_append_and_read_all(tmp_path: Path) -> None:
    store = TradeEventStore(tmp_path)
    event = TradeEvent.create(
        "entry_price_corrected",
        symbol="KLAC",
        trade_id="t-1",
        payload={"old_entry": 2010.21, "new_entry": 245.09},
    )
    store.append(event)
    events = store.read_all()
    assert len(events) == 1
    assert events[0].event_type == "entry_price_corrected"
    assert events[0].payload["new_entry"] == 245.09


def test_events_are_append_only(tmp_path: Path) -> None:
    store = TradeEventStore(tmp_path)
    e1 = TradeEvent.create("trade_opened", symbol="AAPL")
    e2 = TradeEvent.create("trade_closed", symbol="AAPL")
    store.append(e1)
    store.append(e2)
    events = store.read_all()
    assert len(events) == 2
    assert events[0].event_type == "trade_opened"
    assert events[1].event_type == "trade_closed"


def test_pnl_tracker_emits_trade_opened_event(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    tracker.record_submission(
        "MSFT", "s1", "buy", 10, 300.0, "oid-1", "did-1",
    )
    events = tracker.event_store.read_all()
    assert any(e.event_type == "trade_opened" and e.symbol == "MSFT" for e in events)


def test_pnl_tracker_emits_trade_closed_event(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    tracker.record_submission("AAPL", "s1", "buy", 5, 150.0, "oid-2", "did-2")
    tracker.record_exit("AAPL", exit_price=160.0, exit_reason="trailing_stop")
    events = tracker.event_store.read_all()
    closed = [e for e in events if e.event_type == "trade_closed"]
    assert len(closed) == 1
    assert closed[0].symbol == "AAPL"
    assert closed[0].payload.get("exit_reason") == "trailing_stop"


def test_empty_store_returns_empty_list(tmp_path: Path) -> None:
    store = TradeEventStore(tmp_path)
    assert store.read_all() == []
