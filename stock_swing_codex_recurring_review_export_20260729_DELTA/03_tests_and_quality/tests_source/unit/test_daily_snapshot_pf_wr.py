"""Tests for cumulative PF/WR in DailySnapshot (record_daily_snapshot + _compute_cumulative_pf_wr)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from stock_swing.tracking.pnl_tracker import PnLTracker, _compute_cumulative_pf_wr


# ── helper ────────────────────────────────────────────────────────────────────

def _make_tracker(tmp_path: Path) -> PnLTracker:
    return PnLTracker(project_root=tmp_path)


def _add_closed_trade(tracker: PnLTracker, symbol: str, pnl: float, exit_date: str) -> None:
    """Directly inject a closed trade into tracker state for testing."""
    tracker.state.trades.append({
        "trade_id": f"{symbol}-{exit_date}-{pnl}",
        "symbol": symbol,
        "status": "closed",
        "qty": 10,
        "entry_price": 100.0,
        "exit_price": 100.0 + pnl / 10,
        "pnl": pnl,
        "entry_time": f"{exit_date}T10:00:00Z",
        "exit_time": f"{exit_date}T15:00:00Z",
        "strategy_id": "test",
    })


# ── _compute_cumulative_pf_wr ─────────────────────────────────────────────────

class TestComputeCumulativePfWr:
    def test_empty_trades(self):
        pf, wr, cnt = _compute_cumulative_pf_wr([], as_of_date="2026-01-01")
        assert pf is None
        assert wr is None
        assert cnt == 0

    def test_only_wins(self):
        trades = [
            {"status": "closed", "pnl": 100.0, "exit_time": "2026-01-01T15:00:00Z"},
            {"status": "closed", "pnl": 200.0, "exit_time": "2026-01-02T15:00:00Z"},
        ]
        pf, wr, cnt = _compute_cumulative_pf_wr(trades, as_of_date="2026-01-02")
        assert pf is None   # infinite PF (no losses)
        assert wr == 1.0
        assert cnt == 2

    def test_only_losses(self):
        trades = [
            {"status": "closed", "pnl": -100.0, "exit_time": "2026-01-01T15:00:00Z"},
        ]
        pf, wr, cnt = _compute_cumulative_pf_wr(trades, as_of_date="2026-01-01")
        assert pf == 0.0
        assert wr == 0.0
        assert cnt == 1

    def test_mixed(self):
        trades = [
            {"status": "closed", "pnl": 300.0, "exit_time": "2026-01-01T15:00:00Z"},
            {"status": "closed", "pnl": -100.0, "exit_time": "2026-01-02T15:00:00Z"},
            {"status": "closed", "pnl": -100.0, "exit_time": "2026-01-03T15:00:00Z"},
        ]
        pf, wr, cnt = _compute_cumulative_pf_wr(trades, as_of_date="2026-01-03")
        assert pf == pytest.approx(300.0 / 200.0, rel=1e-3)
        assert wr == pytest.approx(1 / 3, rel=1e-3)
        assert cnt == 3

    def test_as_of_date_cutoff(self):
        """Trades after as_of_date must be excluded."""
        trades = [
            {"status": "closed", "pnl": 100.0, "exit_time": "2026-01-01T15:00:00Z"},
            {"status": "closed", "pnl": -500.0, "exit_time": "2026-01-10T15:00:00Z"},  # future
        ]
        pf, wr, cnt = _compute_cumulative_pf_wr(trades, as_of_date="2026-01-01")
        assert pf is None   # only wins up to 01-01
        assert wr == 1.0
        assert cnt == 1

    def test_open_trades_excluded(self):
        trades = [
            {"status": "open", "pnl": None, "exit_time": None},
            {"status": "closed", "pnl": 100.0, "exit_time": "2026-01-01T15:00:00Z"},
        ]
        pf, wr, cnt = _compute_cumulative_pf_wr(trades, as_of_date="2026-01-01")
        assert cnt == 1

    def test_pnl_none_excluded(self):
        """Trades with pnl=None (e.g. incomplete closes) must be excluded."""
        trades = [
            {"status": "closed", "pnl": None, "exit_time": "2026-01-01T15:00:00Z"},
            {"status": "closed", "pnl": 200.0, "exit_time": "2026-01-01T15:00:00Z"},
        ]
        pf, wr, cnt = _compute_cumulative_pf_wr(trades, as_of_date="2026-01-01")
        assert cnt == 1
        assert wr == 1.0


# ── record_daily_snapshot integration ─────────────────────────────────────────

class TestRecordDailySnapshotPfWr:
    def test_pf_wr_saved_to_snapshot(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        _add_closed_trade(tracker, "AAPL", 300.0, "2026-06-01")
        _add_closed_trade(tracker, "MSFT", -100.0, "2026-06-01")

        snap = tracker.record_daily_snapshot(equity=101000.0)

        assert snap.cumulative_profit_factor == pytest.approx(3.0, rel=1e-3)
        assert snap.cumulative_win_rate == pytest.approx(0.5, rel=1e-3)
        assert snap.cumulative_closed_trades == 2

    def test_pf_wr_persisted_in_state(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        _add_closed_trade(tracker, "TSLA", 200.0, "2026-06-01")
        _add_closed_trade(tracker, "NVDA", -100.0, "2026-06-02")

        tracker.record_daily_snapshot(equity=100500.0)

        state = json.loads((tmp_path / "data/tracking/pnl_state.json").read_text())
        saved = state["daily_snapshots"][-1]
        assert "cumulative_profit_factor" in saved
        assert "cumulative_win_rate" in saved
        assert "cumulative_closed_trades" in saved

    def test_no_closed_trades_gives_none(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        snap = tracker.record_daily_snapshot(equity=100000.0)

        assert snap.cumulative_profit_factor is None
        assert snap.cumulative_win_rate is None
        assert snap.cumulative_closed_trades == 0

    def test_pf_improves_over_time(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        # Day 1: one loss → PF=0
        _add_closed_trade(tracker, "A", -100.0, "2026-06-01")
        snap1 = tracker.record_daily_snapshot(equity=99900.0)
        assert snap1.cumulative_profit_factor == 0.0

        # Day 2: bigger win → PF > 1
        _add_closed_trade(tracker, "B", 300.0, "2026-06-02")
        snap2 = tracker.record_daily_snapshot(equity=100200.0)
        assert snap2.cumulative_profit_factor == pytest.approx(3.0, rel=1e-3)
        assert snap2.cumulative_win_rate == pytest.approx(0.5, rel=1e-3)
        assert snap2.cumulative_closed_trades == 2
