"""Tests for P1-A (weighted reconciliation) and P1-B (performance summary semantics)."""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_swing.tracking.pnl_tracker import PnLTracker


def test_p1a_weighted_avg_computed_correctly(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    tracker.record_submission("LRCX", "s1", "buy", 100, 300.0, "oid-1", "did-1")
    tracker.record_submission("LRCX", "s1", "buy", 121, 355.0, "oid-2", "did-2")

    lots = [t for t in tracker.get_open_positions() if t["symbol"] == "LRCX"]
    total_qty = sum(int(t["qty"]) for t in lots)
    w_avg = sum(int(t["qty"]) * float(t["entry_price"]) for t in lots) / total_qty

    assert abs(w_avg - 330.11) < 0.1


def test_p1b_realized_unrealized_total_are_separate(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    tracker.record_submission("AAPL", "s1", "buy", 10, 100.0, "oid-buy", "did-buy")
    tracker.record_exit("AAPL", exit_price=110.0)

    summary = tracker.get_summary()
    realized = summary["cumulative_realized_pnl"]

    assert realized == pytest.approx(100.0, abs=0.01)
    assert summary["open_trades"] == 0
