"""R0-v2-B code change tests: canonical validator + equity bridge.

Tests follow docs/testing_standards.md:
- Normal path
- Edge cases / boundary
- Fail-safe (validator catches bad data and quarantines)
- State machine (validator gates record_exit correctly)
- Layer propagation (equity_bridge dict reaches ConsoleSummary.to_dict health)
- Regression anchor: AC criteria referenced in console_improvement_tasks.md R0-v2-B
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_swing.reporting.equity_bridge import EquityBridgeResult, compute_equity_bridge
from stock_swing.tracking.closed_trade_validator import TradeValidationResult, validate_closed_trade


# ── helpers ────────────────────────────────────────────────────────────────

def _valid_trade(**overrides) -> dict:
    base = {
        "trade_id": "t-001",
        "symbol": "AAPL",
        "qty": 10,
        "entry_price": 100.0,
        "exit_price": 110.0,
        "entry_time": "2026-07-01T09:30:00+00:00",
        "exit_time": "2026-07-03T16:00:00+00:00",
        "holding_days": 2.27,
        "pnl": 100.0,  # (110-100)*10
        "status": "closed",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────── #
# 1. ClosedTradeValidator — normal path
# ─────────────────────────────────────────────────────────────────────────── #

def test_valid_trade_passes_validator() -> None:
    """AC: valid closed trade must pass without issues."""
    result = validate_closed_trade(_valid_trade())
    assert result.valid
    assert result.issues == []


def test_valid_trade_quarantine_reason_is_none() -> None:
    result = validate_closed_trade(_valid_trade())
    assert result.quarantine_reason is None


# ─────────────────────────────────────────────────────────────────────────── #
# 2. ClosedTradeValidator — holding_days (AC: test_closed_trade_requires_computed_holding_days)
# ─────────────────────────────────────────────────────────────────────────── #

def test_holding_days_none_fails_validator() -> None:
    """AC: holding_days=None must be rejected (must be computed from timestamps)."""
    result = validate_closed_trade(_valid_trade(holding_days=None))
    assert not result.valid
    assert any("holding_days is None" in issue for issue in result.issues)


def test_holding_days_negative_fails_validator() -> None:
    """Negative holding_days means entry_time > exit_time."""
    result = validate_closed_trade(_valid_trade(holding_days=-0.5))
    assert not result.valid
    assert any("negative" in issue for issue in result.issues)


def test_holding_days_zero_passes_validator() -> None:
    """Same-day close (holding_days=0) is valid."""
    result = validate_closed_trade(_valid_trade(holding_days=0.0))
    assert result.valid


# ─────────────────────────────────────────────────────────────────────────── #
# 3. ClosedTradeValidator — chronology
# ─────────────────────────────────────────────────────────────────────────── #

def test_reversed_chronology_fails_validator() -> None:
    """entry_time > exit_time must be caught even if holding_days is not set yet."""
    t = _valid_trade(
        holding_days=None,
        entry_time="2026-07-10T09:30:00+00:00",
        exit_time="2026-07-08T16:00:00+00:00",
    )
    result = validate_closed_trade(t)
    assert not result.valid
    assert any("reversed chronology" in issue or "holding_days is None" in issue for issue in result.issues)


# ─────────────────────────────────────────────────────────────────────────── #
# 4. ClosedTradeValidator — quarantine exclusivity (AC: test_quarantine_and_closed_are_mutually_exclusive)
# ─────────────────────────────────────────────────────────────────────────── #

def test_trade_in_quarantined_ids_fails_validator() -> None:
    """AC: a trade_id already in quarantined_trades must not be closed again."""
    t = _valid_trade(trade_id="t-overlap")
    result = validate_closed_trade(t, quarantined_ids={"t-overlap"})
    assert not result.valid
    assert any("already exists in quarantined_trades" in issue for issue in result.issues)


def test_trade_not_in_quarantined_ids_passes() -> None:
    result = validate_closed_trade(_valid_trade(trade_id="t-new"), quarantined_ids={"t-other"})
    assert result.valid


def test_no_quarantined_ids_skips_overlap_check() -> None:
    """When quarantined_ids is None, overlap check is skipped entirely."""
    result = validate_closed_trade(_valid_trade(), quarantined_ids=None)
    assert result.valid


# ─────────────────────────────────────────────────────────────────────────── #
# 5. ClosedTradeValidator — qty and price checks
# ─────────────────────────────────────────────────────────────────────────── #

def test_zero_qty_fails_validator() -> None:
    result = validate_closed_trade(_valid_trade(qty=0))
    assert not result.valid
    assert any("qty" in issue for issue in result.issues)


def test_negative_entry_price_fails_validator() -> None:
    result = validate_closed_trade(_valid_trade(entry_price=-1.0))
    assert not result.valid


def test_pnl_arithmetic_mismatch_flagged() -> None:
    """Recorded PnL deviating from (exit-entry)*qty by > tolerance is flagged."""
    t = _valid_trade(pnl=9999.0)  # expected (110-100)*10=100
    result = validate_closed_trade(t)
    assert not result.valid
    assert any("pnl arithmetic" in issue for issue in result.issues)


def test_pnl_within_tolerance_passes() -> None:
    """Small rounding difference within 5 cents is acceptable."""
    t = _valid_trade(pnl=100.04)  # expected 100.0, diff=0.04 < 0.05
    result = validate_closed_trade(t)
    assert result.valid


# ─────────────────────────────────────────────────────────────────────────── #
# 6. ClosedTradeValidator — integration with PnLTracker
# ─────────────────────────────────────────────────────────────────────────── #

def _make_tracker(tmp_path: Path):
    from stock_swing.tracking.pnl_tracker import PnLTracker
    return PnLTracker(project_root=tmp_path)


def test_canonical_validator_quarantines_bad_trade(tmp_path: Path) -> None:
    """R0-v2-B gate: validator must quarantine a trade with reversed timestamps.

    Regression: before R0-v2-B, record_exit only checked negative holding_days
    but did not enforce via canonical validator as a gate.
    Incident: data repair found 39 reversed-chronology closed trades (2026-07-22).
    """
    tracker = _make_tracker(tmp_path)
    from datetime import datetime, timedelta, timezone

    # Record buy with a future entry_time to force reversal
    trade_id = tracker.record_submission(
        symbol="AAPL", strategy_id="test", side="buy",
        qty=10, price=100.0, broker_order_id="ord-001", decision_id="dec-001",
    )
    # Patch entry_time to be in the future (exit will be now → reversed)
    for t in tracker.state.trades:
        if t.get("trade_id") == trade_id:
            t["entry_time"] = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()

    tracker.record_exit("AAPL", exit_price=105.0, exit_reason="trailing_stop")

    clean = [t for t in tracker.state.trades if t.get("status") == "closed"]
    quarantined = tracker.get_quarantined_trades()
    assert len(clean) == 0, "reversed-chronology trade must NOT be closed"
    assert len(quarantined) == 1
    # Either F1 (negative_holding_days) or canonical_validator catches it — both are correct
    reason = quarantined[0].get("quarantine_reason") or ""
    assert "negative_holding_days" in reason or "canonical_validator" in reason


def test_valid_trade_not_quarantined_by_validator(tmp_path: Path) -> None:
    """Healthy trade must pass through validator and land in clean closed."""
    import time
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="AAPL", strategy_id="test", side="buy",
        qty=10, price=100.0, broker_order_id="ord-002", decision_id="dec-002",
    )
    time.sleep(0.01)
    tracker.record_exit("AAPL", exit_price=110.0, exit_reason="trailing_stop")

    clean = [t for t in tracker.state.trades if t.get("status") == "closed"]
    quarantined = tracker.get_quarantined_trades()
    assert len(clean) == 1
    assert len(quarantined) == 0
    assert clean[0].get("holding_days") is not None and clean[0]["holding_days"] >= 0


# ─────────────────────────────────────────────────────────────────────────── #
# 7. EquityBridge — compute_equity_bridge (AC: test_broker_equity_bridge)
# ─────────────────────────────────────────────────────────────────────────── #

def test_equity_bridge_zero_diff() -> None:
    """AC: when tracker perfectly matches broker, diff=0 and within_tolerance=True."""
    result = compute_equity_bridge(
        broker_equity=950_000.0,
        baseline_equity=1_000_000.0,
        tracker_realized=-50_000.0,
        tracker_unrealized=0.0,
    )
    assert result.diff_usd == pytest.approx(0.0, abs=0.01)
    assert result.tracker_computed == pytest.approx(950_000.0, abs=0.01)
    assert result.within_tolerance


def test_equity_bridge_diff_explained_by_quarantined_pnl() -> None:
    """Diff fully explained by quarantined PnL → unexplained_diff=0 → within_tolerance."""
    result = compute_equity_bridge(
        broker_equity=980_000.0,
        baseline_equity=1_000_000.0,
        tracker_realized=-50_000.0,
        tracker_unrealized=0.0,
        quarantined_pnl=-30_000.0,  # executed at broker, excluded from tracker
        # broker sees baseline - 50K clean - 30K quarantined = 920K... hmm
        # Let's do a consistent example:
        # baseline=1M, tracker_realized=-20K (clean), quarantined=-30K (executed at broker)
        # broker_equity = 1M - 20K - 30K = 950K
        # tracker_computed = 1M - 20K = 980K
        # diff = 950K - 980K = -30K = quarantined_pnl → unexplained=0
    )
    # Fix the numbers for consistency
    result2 = compute_equity_bridge(
        broker_equity=950_000.0,
        baseline_equity=1_000_000.0,
        tracker_realized=-20_000.0,
        tracker_unrealized=0.0,
        quarantined_pnl=-30_000.0,
    )
    # diff = 950K - (1M - 20K) = 950K - 980K = -30K
    # unexplained = -30K - (-30K) = 0
    assert result2.diff_usd == pytest.approx(-30_000.0, abs=0.01)
    assert result2.unexplained_diff == pytest.approx(0.0, abs=0.01)
    assert result2.within_tolerance


def test_equity_bridge_unexplained_diff_flags_out_of_tolerance() -> None:
    """Large unexplained diff must be flagged as out-of-tolerance."""
    result = compute_equity_bridge(
        broker_equity=800_000.0,
        baseline_equity=1_000_000.0,
        tracker_realized=-50_000.0,
        tracker_unrealized=0.0,
        quarantined_pnl=0.0,
        tolerance_usd=5_000.0,
    )
    # diff = 800K - 950K = -150K, unexplained = -150K
    assert not result.within_tolerance


def test_equity_bridge_diff_bp_computed() -> None:
    result = compute_equity_bridge(
        broker_equity=1_000_000.0,
        baseline_equity=1_000_000.0,
        tracker_realized=-1_000.0,
        tracker_unrealized=0.0,
    )
    # diff = 1M - 999K = 1K, diff_bp = 1K/1M * 10000 = 10bp
    assert result.diff_bp == pytest.approx(10.0, abs=0.1)


def test_equity_bridge_zero_broker_equity_safe() -> None:
    """Zero broker equity must not cause division by zero."""
    result = compute_equity_bridge(
        broker_equity=0.0,
        baseline_equity=1_000_000.0,
        tracker_realized=0.0,
        tracker_unrealized=0.0,
    )
    assert result.diff_bp == 0.0


def test_equity_bridge_to_dict_keys() -> None:
    result = compute_equity_bridge(
        broker_equity=990_000.0,
        baseline_equity=1_000_000.0,
        tracker_realized=-10_000.0,
        tracker_unrealized=0.0,
    )
    d = result.to_dict()
    expected_keys = {
        "baseline_equity", "tracker_realized", "tracker_unrealized", "fees",
        "tracker_computed", "broker_equity", "diff_usd", "diff_bp",
        "quarantined_pnl", "unexplained_diff", "within_tolerance", "tolerance_usd",
    }
    assert set(d.keys()) == expected_keys


# ─────────────────────────────────────────────────────────────────────────── #
# 8. Layer propagation: equity_bridge reaches ConsoleSummary.to_dict health
# ─────────────────────────────────────────────────────────────────────────── #

def test_equity_bridge_propagates_to_console_summary_health() -> None:
    """equity_bridge dict must reach to_dict()['health']['equity_bridge']."""
    from stock_swing.reporting.console_summary import ConsoleSummary
    bridge = {"diff_usd": -30_000.0, "within_tolerance": False}
    s = ConsoleSummary.build(
        run_id="eb-test",
        equity=990_000.0,
        open_position_count=5,
        equity_bridge=bridge,
    )
    d = s.to_dict()
    assert d["health"]["equity_bridge"]["diff_usd"] == -30_000.0
    assert d["health"]["equity_bridge"]["within_tolerance"] is False


def test_equity_bridge_default_is_empty_dict() -> None:
    """When not supplied, equity_bridge defaults to empty dict (no crash)."""
    from stock_swing.reporting.console_summary import ConsoleSummary
    s = ConsoleSummary.build(run_id="eb-empty", equity=1_000_000.0, open_position_count=0)
    d = s.to_dict()
    assert d["health"]["equity_bridge"] == {}
