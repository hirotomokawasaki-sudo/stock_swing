"""Tests for P1-C: entry/exit metadata backfill."""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_swing.tracking.pnl_tracker import PnLTracker


def test_backfill_preserves_existing_metadata(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    tracker.record_submission(
        "AAPL",
        "original_strategy",
        "buy",
        10,
        150.0,
        "oid-1",
        "did-1",
        signal_strength=0.87,
    )
    tracker.record_exit("AAPL", exit_price=160.0, exit_reason="trailing_stop")

    closed = [t for t in tracker.state.trades if t["status"] == "closed"]
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "trailing_stop"
    assert "original_strategy" in str(closed[0].get("original_strategy_id", ""))


def test_backfill_fills_missing_entry_signal_strength(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    tracker.record_submission(
        "MSFT",
        "s1",
        "buy",
        5,
        300.0,
        "oid-2",
        "did-2",
        signal_strength=None,
    )
    tracker.record_exit("MSFT", exit_price=315.0)

    closed = [t for t in tracker.state.trades if t["status"] == "closed"]
    assert closed[0]["entry_signal_strength"] is None

    closed[0]["entry_signal_strength"] = 0.82
    tracker._save_state()

    tracker2 = PnLTracker(tmp_path)
    closed2 = [t for t in tracker2.state.trades if t["status"] == "closed"]
    assert closed2[0]["entry_signal_strength"] == pytest.approx(0.82)
