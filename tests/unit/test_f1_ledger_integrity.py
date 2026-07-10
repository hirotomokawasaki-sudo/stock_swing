"""F1 tests: closed-trade ledger integrity — negative holding_days quarantine."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stock_swing.tracking.pnl_tracker import PnLTracker, _compute_holding_days


# ── Helper: synthetic holding_days computation ─────────────────────────────

def test_compute_holding_days_positive():
    entry = "2026-06-01T09:30:00+00:00"
    exit_ = "2026-06-03T16:00:00+00:00"
    hd = _compute_holding_days(entry, exit_)
    assert hd is not None and hd > 0


def test_compute_holding_days_negative():
    entry = "2026-06-05T09:30:00+00:00"
    exit_ = "2026-06-01T16:00:00+00:00"   # exit before entry
    hd = _compute_holding_days(entry, exit_)
    assert hd is not None and hd < 0


def test_compute_holding_days_none():
    assert _compute_holding_days(None, "2026-06-01T00:00:00+00:00") is None
    assert _compute_holding_days("2026-06-01T00:00:00+00:00", None) is None


# ── Tracker integration: quarantine on negative holding_days ───────────────

def _make_tracker(tmp_path: Path) -> PnLTracker:
    return PnLTracker(project_root=tmp_path)


def _submit_buy(tracker: PnLTracker, symbol: str = "AAPL", entry_time: str | None = None) -> str:
    """Record a buy and optionally backdating entry_time for test setup."""
    trade_id = tracker.record_submission(
        symbol=symbol,
        strategy_id="test",
        side="buy",
        qty=10,
        price=100.0,
        broker_order_id=f"ord-{symbol}",
        decision_id="dec-00000001",
    )
    if entry_time:
        # Patch entry_time to simulate reconstructed trade with stale timestamp
        for t in tracker.state.trades:
            if t.get("trade_id") == trade_id:
                t["entry_time"] = entry_time
    return trade_id


def test_valid_close_not_quarantined(tmp_path):
    tracker = _make_tracker(tmp_path)
    _submit_buy(tracker, "AAPL")
    import time; time.sleep(0.01)
    tracker.record_exit("AAPL", exit_price=110.0, exit_reason="trailing_stop")

    clean = tracker.get_clean_closed_trades()
    quarantined = tracker.get_quarantined_trades()
    assert len(clean) == 1, "valid close must land in clean trades"
    assert len(quarantined) == 0, "no quarantine for valid trade"
    assert clean[0]["holding_days"] is not None and clean[0]["holding_days"] >= 0


def test_negative_holding_days_quarantined(tmp_path):
    """Simulate a broker-reconstructed trade where entry_time > exit_time."""
    tracker = _make_tracker(tmp_path)
    # Submit buy with future entry_time (bad reconstruction)
    future_entry = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    _submit_buy(tracker, "DELL", entry_time=future_entry)
    tracker.record_exit("DELL", exit_price=95.0, exit_reason="stop_loss")

    clean = tracker.get_clean_closed_trades()
    quarantined = tracker.get_quarantined_trades()
    assert len(clean) == 0, "invalid trade must NOT be in clean trades"
    assert len(quarantined) == 1, "invalid trade must be quarantined"
    assert quarantined[0]["holding_days"] < 0
    assert "negative_holding_days" in (quarantined[0].get("quarantine_reason") or "")


def test_quarantine_does_not_affect_pnl_stats(tmp_path):
    """Quarantined trade PnL must not be counted in realized PnL."""
    tracker = _make_tracker(tmp_path)
    future_entry = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    _submit_buy(tracker, "DELL", entry_time=future_entry)
    tracker.record_exit("DELL", exit_price=80.0, exit_reason="stop_loss")

    # cumulative_realized_pnl should NOT include the quarantined trade
    summary = tracker.get_summary()
    assert summary["closed_trades"] == 0  # quarantined trade not counted as closed


def test_ledger_quality_report(tmp_path):
    tracker = _make_tracker(tmp_path)
    # Valid trade
    _submit_buy(tracker, "AAPL")
    import time; time.sleep(0.01)
    tracker.record_exit("AAPL", exit_price=105.0, exit_reason="trailing_stop")
    # Invalid (quarantined) trade
    future_entry = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    _submit_buy(tracker, "DELL", entry_time=future_entry)
    tracker.record_exit("DELL", exit_price=95.0, exit_reason="stop_loss")

    report = tracker.get_ledger_quality_report()
    assert report["clean_closed"] == 1
    assert report["quarantined"] == 1
    assert report["total_closed"] == 1
    assert report["negative_holding_days_in_clean"] == 0


def test_quarantined_trades_persisted(tmp_path):
    """Quarantined trades survive a state reload."""
    tracker = _make_tracker(tmp_path)
    future_entry = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    _submit_buy(tracker, "DELL", entry_time=future_entry)
    tracker.record_exit("DELL", exit_price=95.0, exit_reason="stop_loss")

    # Reload
    tracker2 = _make_tracker(tmp_path)
    quarantined = tracker2.get_quarantined_trades()
    assert len(quarantined) == 1
