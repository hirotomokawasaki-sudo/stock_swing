"""F4 tests: TradeEntry stores durable decision metadata."""
from __future__ import annotations

from pathlib import Path

from stock_swing.tracking.pnl_tracker import PnLTracker


def _make_tracker(tmp_path: Path) -> PnLTracker:
    return PnLTracker(project_root=tmp_path)


def test_record_submission_stores_decision_id(tmp_path):
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="AAPL",
        strategy_id="momentum_v1",
        side="buy",
        qty=10,
        price=100.0,
        broker_order_id="ord-001",
        decision_id="dec-abcdef01",
        run_id="run-xyz",
        experiment_id="exp-001",
        prompt_version="v2.1",
        config_hash="abc123",
    )
    open_pos = tracker.get_open_positions()
    assert len(open_pos) == 1
    t = open_pos[0]
    assert t["decision_id"] == "dec-abcdef01"
    assert t["run_id"] == "run-xyz"
    assert t["experiment_id"] == "exp-001"
    assert t["prompt_version"] == "v2.1"
    assert t["config_hash"] == "abc123"


def test_metadata_survives_reload(tmp_path):
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="NVDA",
        strategy_id="momentum_v1",
        side="buy",
        qty=5,
        price=200.0,
        broker_order_id="ord-002",
        decision_id="dec-99999999",
        run_id="run-abc",
        experiment_id="exp-beta",
    )
    # Reload tracker
    tracker2 = _make_tracker(tmp_path)
    t = tracker2.get_open_positions()[0]
    assert t["decision_id"] == "dec-99999999"
    assert t["run_id"] == "run-abc"
    assert t["experiment_id"] == "exp-beta"


def test_metadata_preserved_through_exit(tmp_path):
    import time
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="MU",
        strategy_id="momentum_v1",
        side="buy",
        qty=10,
        price=100.0,
        broker_order_id="ord-003",
        decision_id="dec-aabbccdd",
        run_id="run-r3",
        experiment_id="exp-clean",
    )
    time.sleep(0.01)
    closed = tracker.record_exit("MU", exit_price=110.0, exit_reason="trailing_stop")
    assert closed is not None
    assert closed.decision_id == "dec-aabbccdd"
    assert closed.run_id == "run-r3"
    assert closed.experiment_id == "exp-clean"


def test_backward_compat_no_metadata_fields(tmp_path):
    """Existing state without metadata fields should load without error."""
    import json
    import os
    from datetime import datetime, timezone

    state_path = tmp_path / "data" / "tracking" / "pnl_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # Write a minimal legacy state without decision_id etc.
    legacy_state = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "trades": [
            {
                "trade_id": "AAPL-legacyxxx",
                "symbol": "AAPL",
                "strategy_id": "momentum_v1",
                "side": "buy",
                "qty": 10,
                "entry_price": 100.0,
                "exit_price": None,
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "exit_time": None,
                "pnl": None,
                "return_pct": None,
                "status": "open",
            }
        ],
    }
    state_path.write_text(json.dumps(legacy_state), encoding="utf-8")

    # Should not raise
    tracker = PnLTracker(project_root=tmp_path)
    pos = tracker.get_open_positions()
    assert len(pos) == 1
    # decision_id defaults to None
    assert pos[0].get("decision_id") is None
