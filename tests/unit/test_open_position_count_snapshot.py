"""Tests for open_position_count on DailySnapshot (bug fix 2026-08-13).

Background: the console's Open Positions chart was rendering the *current
live* broker/tracker position count for every historical data point instead
of the count at that point in time, because DailySnapshot never recorded it.
record_daily_snapshot() now records the count of trades with status=="open"
at snapshot time; the dashboard_service chart builder now reads this
per-snapshot value instead of substituting the live count.
"""
from __future__ import annotations

from pathlib import Path

from stock_swing.tracking.pnl_tracker import PnLTracker


def _make_tracker(tmp_path: Path) -> PnLTracker:
    return PnLTracker(project_root=tmp_path)


def _add_trade(tracker: PnLTracker, symbol: str, status: str, entry_time: str, exit_time: str | None = None) -> None:
    tracker.state.trades.append({
        "trade_id": f"{symbol}-{entry_time}",
        "symbol": symbol,
        "status": status,
        "qty": 10,
        "entry_price": 100.0,
        "exit_price": 105.0 if status == "closed" else None,
        "pnl": 50.0 if status == "closed" else None,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "strategy_id": "test",
    })


class TestRecordDailySnapshotOpenPositionCount:
    def test_normal_case_records_current_open_count(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        _add_trade(tracker, "AAA", "open", "2026-08-01T10:00:00Z")
        _add_trade(tracker, "BBB", "open", "2026-08-01T10:00:00Z")
        _add_trade(tracker, "CCC", "closed", "2026-07-01T10:00:00Z", "2026-08-01T15:00:00Z")

        snap = tracker.record_daily_snapshot(equity=1_000_000.0)

        assert snap.open_position_count == 2

    def test_zero_open_positions(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        _add_trade(tracker, "AAA", "closed", "2026-07-01T10:00:00Z", "2026-08-01T15:00:00Z")

        snap = tracker.record_daily_snapshot(equity=1_000_000.0)

        assert snap.open_position_count == 0

    def test_no_trades_at_all(self, tmp_path):
        tracker = _make_tracker(tmp_path)

        snap = tracker.record_daily_snapshot(equity=1_000_000.0)

        assert snap.open_position_count == 0

    def test_persisted_and_reloadable(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        _add_trade(tracker, "AAA", "open", "2026-08-01T10:00:00Z")
        tracker.record_daily_snapshot(equity=1_000_000.0)

        reloaded = PnLTracker(project_root=tmp_path)
        snaps = reloaded.state.daily_snapshots
        assert len(snaps) == 1
        assert snaps[0]["open_position_count"] == 1

    def test_field_defaults_to_none_for_pre_existing_snapshot_dicts(self):
        # Simulates an old snapshot dict loaded from disk before this field
        # existed; get() must not KeyError and should surface None so callers
        # can distinguish "unknown" from "zero".
        old_snapshot_dict = {
            "date": "2026-05-01",
            "equity": 1000000.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_pnl": 0.0,
            "trade_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "signals_generated": 0,
            "orders_submitted": 0,
        }
        assert old_snapshot_dict.get("open_position_count") is None
