from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from stock_swing.cli import reconcile_orders
from stock_swing.cli.paper_demo import _save_decisions
from stock_swing.core.path_manager import PathManager
from stock_swing.decision_engine.decision_engine import DecisionRecord, PositionSizingSnapshot, ProposedOrder
from stock_swing.storage.stage_store import StageStore
from stock_swing.tracking.pnl_tracker import PnLTracker


def _decision() -> DecisionRecord:
    return DecisionRecord(
        decision_id="dec-aapl-001",
        schema_version="v1",
        generated_at=datetime.now(timezone.utc),
        mode="paper",
        strategy_id="breakout_momentum_v1",
        strategy_version_id="breakout_momentum_v1",
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        signal_strength=0.8,
        risk_state="pass",
        deny_reasons=[],
        requires_operator_approval=False,
        time_horizon="3d",
        evidence={"notes": ["integration p6"]},
        proposed_order=ProposedOrder(
            symbol="AAPL",
            side="buy",
            order_type="market",
            qty=10,
            time_in_force="day",
            limit_price=100.0,
        ),
        sizing=PositionSizingSnapshot(final_shares=10, current_price=100.0),
        run_id="run-001",
        experiment_id="exp-001",
        config_hash="cfg-001",
        prompt_version="prompt-v1",
    )


def test_decision_to_fill_to_closed_trade_preserves_join_metadata(monkeypatch) -> None:
    """
    End-to-end P6 regression:
    decision save -> submission/open trade -> broker sell fill -> closed trade.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        store = StageStore(PathManager(project_root))
        decision = _decision()
        _save_decisions([decision], store, "20260730T000000Z", run_id="run-001", experiment_id="exp-001", config_hash="cfg-001")

        tracker = PnLTracker(project_root)
        tracker.record_submission(
            symbol="AAPL",
            strategy_id=decision.strategy_version_id,
            side="buy",
            qty=10,
            price=100.0,
            broker_order_id="buy-aapl-001",
            decision_id=decision.decision_id,
            original_strategy_id=decision.strategy_id,
            strategy_version_id=decision.strategy_version_id,
            run_id=decision.run_id,
            experiment_id=decision.experiment_id,
            prompt_version=decision.prompt_version,
            config_hash=decision.config_hash,
        )

        class StubBroker:
            def __init__(self, *args, **kwargs):
                pass

            def fetch_orders(self, status="all", limit=500):
                return SimpleNamespace(payload=[{
                    "id": "sell-aapl-001",
                    "symbol": "AAPL",
                    "side": "sell",
                    "status": "filled",
                    "filled_qty": 10,
                    "filled_avg_price": 110.0,
                    "submitted_at": "2026-07-30T15:00:00+00:00",
                    "updated_at": "2026-07-30T15:00:05+00:00",
                }])

            def fetch_latest_quote(self, symbol):
                return SimpleNamespace(payload={"quote": {"bp": 109.5, "ap": 110.5}})

        monkeypatch.setattr(reconcile_orders, "project_root", project_root)
        monkeypatch.setattr(reconcile_orders, "_load_env", lambda path: None)
        monkeypatch.setattr(reconcile_orders, "BrokerClient", StubBroker)
        monkeypatch.setattr(reconcile_orders, "PnLTracker", lambda root: tracker)
        monkeypatch.setattr(reconcile_orders, "cancel_stale_buy_orders", lambda broker: [])
        monkeypatch.setattr(reconcile_orders, "cancel_stale_sell_orders", lambda broker, root, **kw: [])
        monkeypatch.setattr(reconcile_orders, "reconcile_filled_buys", lambda broker, tracker, recently_sold_symbols: 0)
        monkeypatch.setattr(
            reconcile_orders,
            "load_recent_submissions",
            lambda audits_dir, limit=100: [{
                "ts": "2026-07-30T15:00:00+00:00",
                "submission_id": "sub-aapl-001",
                "side": "sell",
                "qty": 10,
                "symbol": "AAPL",
            }],
        )
        monkeypatch.setattr(reconcile_orders, "read_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "delete_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "purge_old_entries", lambda root, max_age_days=7: None)
        monkeypatch.setenv("BROKER_API_KEY", "key")
        monkeypatch.setenv("BROKER_API_SECRET", "secret")

        assert reconcile_orders.main() == 0

        saved_decision = next((project_root / "data" / "decisions").glob("decision_*.json"))
        decision_payload = json.loads(saved_decision.read_text(encoding="utf-8"))
        closed = [t for t in tracker.state.trades if t.get("status") == "closed"]
        assert len(closed) == 1

        trade = closed[0]
        assert decision_payload["run_id"] == "run-001"
        assert decision_payload["experiment_id"] == "exp-001"
        assert decision_payload["config_hash"] == "cfg-001"
        assert trade["run_id"] == "run-001"
        assert trade["experiment_id"] == "exp-001"
        assert trade["config_hash"] == "cfg-001"
        assert trade["decision_id"] == "dec-aapl-001"
        assert trade["exit_broker_order_id"] == "sell-aapl-001"
        assert trade["exit_fill_id"] == "sell-aapl-001"
