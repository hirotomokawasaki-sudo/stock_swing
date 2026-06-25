"""Tests for atomic PnL state writes (P0-A)."""

import json
from pathlib import Path

from stock_swing.tracking.pnl_tracker import PnLTracker


def test_atomic_save_produces_valid_json(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    tracker.record_submission(
        symbol="AAPL",
        strategy_id="test",
        side="buy",
        qty=10,
        price=150.0,
        broker_order_id="oid-1",
        decision_id="did-1",
    )
    state_file = tmp_path / PnLTracker.STATE_FILE
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "trades" in data or "last_updated" in data


def test_atomic_save_no_tmp_file_left(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    tracker._save_state()
    tmp_files = list((tmp_path / "data" / "tracking").glob(".pnl_state.*.tmp"))
    assert tmp_files == [], f"Leftover tmp files: {tmp_files}"


def test_state_round_trip(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    tracker.record_submission(
        symbol="MSFT",
        strategy_id="s1",
        side="buy",
        qty=5,
        price=300.0,
        broker_order_id="oid-2",
        decision_id="did-2",
    )
    tracker2 = PnLTracker(tmp_path)
    positions = tracker2.get_open_positions()
    assert any(p["symbol"] == "MSFT" for p in positions)
