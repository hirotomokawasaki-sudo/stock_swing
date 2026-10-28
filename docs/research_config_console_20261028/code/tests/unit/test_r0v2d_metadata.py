"""R0-v2-D: Durable Metadata & Experiment Join tests.

Validates that record_submission() accepts and persists run_id / experiment_id /
config_hash, and that these fields survive into the closed trade record.

Acceptance criteria (console_improvement_tasks.md R0-v2-D):
- deployment 後の decision → order → fill → trade join ≥99%
- run_id / experiment_id / config_hash coverage ≥99%
- deny_reason coverage = 100%

testing_standards.md checklist:
  [x] Normal path
  [x] Boundary (missing metadata → stored as None, no crash)
  [x] Propagation: record_submission → closed trade
  [x] Regression: was 0/259 join before R0-v2-D
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


def _make_tracker(tmp_path: Path):
    from stock_swing.tracking.pnl_tracker import PnLTracker
    return PnLTracker(project_root=tmp_path)


# ─────────────────────────────────────────────────────────────────────────── #
# 1. record_submission accepts run_id / experiment_id / config_hash
# ─────────────────────────────────────────────────────────────────────────── #

def test_record_submission_stores_run_id(tmp_path: Path) -> None:
    """run_id passed to record_submission must appear in the open trade dict."""
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="AAPL", strategy_id="test", side="buy",
        qty=10, price=100.0, broker_order_id="ord-1", decision_id="dec-1",
        run_id="run-abc123",
    )
    open_trades = [t for t in tracker.state.trades if t.get("symbol") == "AAPL"]
    assert len(open_trades) == 1
    assert open_trades[0].get("run_id") == "run-abc123"


def test_record_submission_stores_experiment_id(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="MSFT", strategy_id="test", side="buy",
        qty=5, price=200.0, broker_order_id="ord-2", decision_id="dec-2",
        experiment_id="exp-xyz789",
    )
    open_trades = [t for t in tracker.state.trades if t.get("symbol") == "MSFT"]
    assert open_trades[0].get("experiment_id") == "exp-xyz789"


def test_record_submission_stores_config_hash(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="GOOGL", strategy_id="test", side="buy",
        qty=3, price=150.0, broker_order_id="ord-3", decision_id="dec-3",
        config_hash="sha256:abcdef",
    )
    open_trades = [t for t in tracker.state.trades if t.get("symbol") == "GOOGL"]
    assert open_trades[0].get("config_hash") == "sha256:abcdef"


def test_record_submission_missing_metadata_is_none_not_crash(tmp_path: Path) -> None:
    """Omitting run_id/experiment_id/config_hash must store None, not crash."""
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="AMZN", strategy_id="test", side="buy",
        qty=2, price=180.0, broker_order_id="ord-4", decision_id="dec-4",
        # intentionally no run_id / experiment_id / config_hash
    )
    trade = next(t for t in tracker.state.trades if t.get("symbol") == "AMZN")
    assert trade.get("run_id") is None
    assert trade.get("experiment_id") is None
    assert trade.get("config_hash") is None


# ─────────────────────────────────────────────────────────────────────────── #
# 2. Metadata propagates from open → closed trade (join survives record_exit)
# ─────────────────────────────────────────────────────────────────────────── #

def test_run_id_survives_to_closed_trade(tmp_path: Path) -> None:
    """run_id set on open trade must appear in the closed trade after record_exit.

    Regression: before R0-v2-D, record_submission() in paper_demo.py did not
    pass run_id → all 259 closed trades had run_id=None → join coverage=0%.
    """
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="NVDA", strategy_id="test", side="buy",
        qty=10, price=100.0, broker_order_id="ord-5", decision_id="dec-5",
        run_id="run-test-001",
        experiment_id="exp-test-001",
        config_hash="sha256:test",
    )
    time.sleep(0.01)
    tracker.record_exit("NVDA", exit_price=110.0, exit_reason="trailing_stop")

    closed = [t for t in tracker.state.trades if t.get("status") == "closed"]
    assert len(closed) == 1
    assert closed[0].get("run_id") == "run-test-001", (
        "run_id must propagate from open → closed trade (R0-v2-D join fix)"
    )
    assert closed[0].get("experiment_id") == "exp-test-001"
    assert closed[0].get("config_hash") == "sha256:test"


def test_metadata_persists_across_reload(tmp_path: Path) -> None:
    """Metadata fields survive pnl_state.json save and reload."""
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="AMD", strategy_id="test", side="buy",
        qty=5, price=120.0, broker_order_id="ord-6", decision_id="dec-6",
        run_id="run-persist-test",
    )
    # Reload
    from stock_swing.tracking.pnl_tracker import PnLTracker
    tracker2 = PnLTracker(project_root=tmp_path)
    trade = next(t for t in tracker2.state.trades if t.get("symbol") == "AMD")
    assert trade.get("run_id") == "run-persist-test"


# ─────────────────────────────────────────────────────────────────────────── #
# 3. All-metadata join coverage metric
# ─────────────────────────────────────────────────────────────────────────── #

def test_join_coverage_with_all_metadata(tmp_path: Path) -> None:
    """When all metadata is supplied, join coverage for new trades is 100%."""
    tracker = _make_tracker(tmp_path)
    for i in range(5):
        tracker.record_submission(
            symbol=f"SYM{i}", strategy_id="test", side="buy",
            qty=1, price=100.0, broker_order_id=f"ord-{i}", decision_id=f"dec-{i}",
            run_id=f"run-{i}",
            experiment_id=f"exp-{i}",
            config_hash=f"hash-{i}",
        )
        time.sleep(0.005)
        tracker.record_exit(f"SYM{i}", exit_price=105.0, exit_reason="trailing_stop")

    closed = [t for t in tracker.state.trades if t.get("status") == "closed"]
    with_run_id = [t for t in closed if t.get("run_id")]
    coverage = len(with_run_id) / len(closed) * 100 if closed else 0
    assert coverage == pytest.approx(100.0), (
        f"run_id coverage should be 100% for newly created trades; got {coverage:.1f}%"
    )


def test_join_coverage_without_metadata_is_zero(tmp_path: Path) -> None:
    """Old-style trades (no metadata) have 0% join coverage — expected baseline."""
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="OLD", strategy_id="test", side="buy",
        qty=1, price=100.0, broker_order_id="ord-old", decision_id="dec-old",
        # no run_id / experiment_id / config_hash
    )
    time.sleep(0.005)
    tracker.record_exit("OLD", exit_price=105.0, exit_reason="trailing_stop")

    closed = [t for t in tracker.state.trades if t.get("status") == "closed"]
    with_run_id = [t for t in closed if t.get("run_id")]
    coverage = len(with_run_id) / len(closed) * 100 if closed else 0
    assert coverage == pytest.approx(0.0)
