from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_swing.tracking.pnl_tracker import PnLTracker


def test_update_open_trade_peaks_and_symbol_context(tmp_path: Path):
    tracker = PnLTracker(tmp_path)

    tracker.record_submission(
        symbol="AAPL",
        strategy_id="test_strategy",
        side="buy",
        qty=10,
        price=100.0,
        broker_order_id="buy-1",
        decision_id="decision-1",
    )
    tracker.record_submission(
        symbol="AAPL",
        strategy_id="test_strategy",
        side="buy",
        qty=5,
        price=110.0,
        broker_order_id="buy-2",
        decision_id="decision-2",
    )

    open_trades = tracker.get_open_positions()
    older_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    newer_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    open_trades[0]["entry_time"] = older_time
    open_trades[1]["entry_time"] = newer_time
    open_trades[0]["peak_price"] = 103.0
    open_trades[1]["peak_price"] = 112.0
    tracker._save_state()

    updates = tracker.update_open_trade_peaks({"AAPL": 118.5})

    assert updates == 2
    refreshed = tracker.get_open_positions()
    assert all(trade["peak_price"] == 118.5 for trade in refreshed)

    context = tracker.get_open_position_context_by_symbol()
    assert context["AAPL"]["created_at"] == older_time
    assert context["AAPL"]["peak_price"] == 118.5


def test_update_open_trade_peaks_seeds_missing_peak_price(tmp_path: Path):
    tracker = PnLTracker(tmp_path)
    tracker.record_submission(
        symbol="MSFT",
        strategy_id="test_strategy",
        side="buy",
        qty=3,
        price=250.0,
        broker_order_id="buy-msft",
        decision_id="decision-msft",
    )

    open_trade = tracker.get_open_positions()[0]
    open_trade.pop("peak_price", None)
    tracker._save_state()

    updates = tracker.update_open_trade_peaks({"MSFT": 245.0})

    assert updates == 1
    assert tracker.get_open_positions()[0]["peak_price"] == 250.0
