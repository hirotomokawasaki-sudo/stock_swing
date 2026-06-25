from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

massive_stub = types.ModuleType("massive")
massive_stub.RESTClient = object
sys.modules.setdefault("massive", massive_stub)

from stock_swing.cli import reconcile_orders
from stock_swing.cli.cron_summary import CRON_SUMMARY_PREFIX
from stock_swing.tracking.pnl_tracker import PnLTracker


def test_reconcile_orders_skips_sell_fill_already_persisted(monkeypatch, capsys):
    """A sell fill already saved on a closed trade must not be replayed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        tracker = PnLTracker(project_root)

        tracker.record_submission(
            symbol="ORCL",
            strategy_id="test_strategy",
            side="buy",
            qty=18,
            price=200.0,
            broker_order_id="buy-order-old",
            decision_id="decision-buy-old",
        )
        tracker.record_exit(
            symbol="ORCL",
            exit_price=210.0,
            exit_qty=18,
            broker_order_id="sell-order-123",
            exit_reason="trailing_stop",
        )

        tracker.record_submission(
            symbol="ORCL",
            strategy_id="test_strategy",
            side="buy",
            qty=244,
            price=205.0,
            broker_order_id="buy-order-new",
            decision_id="decision-buy-new",
        )

        class StubBroker:
            def __init__(self, *args, **kwargs):
                pass

            def fetch_orders(self, status="all", limit=500):
                return SimpleNamespace(payload=[
                    {
                        "id": "sell-order-123",
                        "symbol": "ORCL",
                        "side": "sell",
                        "status": "filled",
                        "filled_qty": 18,
                        "filled_avg_price": 210.0,
                        "submitted_at": "2026-06-04T14:15:00+00:00",
                    }
                ])

            def fetch_latest_quote(self, symbol):
                return SimpleNamespace(payload={"quote": {"bp": 209.5, "ap": 210.5}})

        monkeypatch.setattr(reconcile_orders, "project_root", project_root)
        monkeypatch.setattr(reconcile_orders, "_load_env", lambda path: None)
        monkeypatch.setattr(reconcile_orders, "BrokerClient", StubBroker)
        monkeypatch.setattr(reconcile_orders, "PnLTracker", lambda root: tracker)
        monkeypatch.setattr(reconcile_orders, "cancel_stale_buy_orders", lambda broker: [])
        monkeypatch.setattr(reconcile_orders, "reconcile_filled_buys", lambda broker, tracker, recently_sold_symbols: 0)
        monkeypatch.setattr(
            reconcile_orders,
            "load_recent_submissions",
            lambda audits_dir, limit=100: [
                {
                    "ts": "2026-06-04T14:15:04+00:00",
                    "submission_id": "sub-1",
                    "side": "sell",
                    "qty": 18,
                    "symbol": "ORCL",
                }
            ],
        )
        monkeypatch.setattr(reconcile_orders, "read_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "delete_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "purge_old_entries", lambda root, max_age_days=7: None)

        monkeypatch.setenv("BROKER_API_KEY", "key")
        monkeypatch.setenv("BROKER_API_SECRET", "secret")

        assert reconcile_orders.main() == 0
        out = capsys.readouterr().out
        summary_line = [line for line in out.splitlines() if line.startswith(CRON_SUMMARY_PREFIX)][-1]
        payload = json.loads(summary_line.split("=", 1)[1])
        assert payload["job"] == "reconcile_orders"
        assert payload["status"] == "ok"
        assert payload["filled_exits_recorded"] == 0

        open_positions = tracker.get_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0]["symbol"] == "ORCL"
        assert open_positions[0]["qty"] == 244

        closed_trades = [t for t in tracker.state.trades if t["status"] == "closed"]
        assert len(closed_trades) == 1
        assert closed_trades[0]["exit_broker_order_id"] == "sell-order-123"


def test_partial_fill_completion_records_remaining_qty(monkeypatch, capsys):
    """When a sell order was partially filled and the partial was already recorded,
    the cron reconciler must complete the recording of the remaining shares.

    Scenario (mirrors the 2026-06-24 CRDO incident):
      - 3 open lots totalling 254 shares
      - Inline paper_demo reconciler recorded 51 shares at the time of initial partial fill
      - Broker subsequently filled all 254 shares under the same order ID
      - Cron reconciler should detect and record the remaining 203 shares
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        tracker = PnLTracker(project_root)

        # Set up 3 open lots (86 + 84 + 84 = 254 shares)
        tracker.record_submission(
            symbol="CRDO", strategy_id="test_strategy", side="buy",
            qty=86, price=273.98, broker_order_id="buy-1", decision_id="d-1",
        )
        tracker.record_submission(
            symbol="CRDO", strategy_id="test_strategy", side="buy",
            qty=84, price=273.50, broker_order_id="buy-2", decision_id="d-2",
        )
        tracker.record_submission(
            symbol="CRDO", strategy_id="test_strategy", side="buy",
            qty=84, price=272.83, broker_order_id="buy-3", decision_id="d-3",
        )

        # Inline reconciler already recorded a partial fill of 51 shares
        tracker.record_exit(
            symbol="CRDO",
            exit_price=271.56,
            exit_qty=51,
            broker_order_id="sell-order-254",
            exit_reason="breakeven_stop",
        )

        # After partial close: 35 + 84 + 84 = 203 shares remain open
        open_before = sum(
            t["qty"] for t in tracker.state.trades
            if t["status"] == "open" and t["symbol"] == "CRDO"
        )
        assert open_before == 203

        class StubBroker:
            def __init__(self, *args, **kwargs):
                pass

            def fetch_orders(self, status="all", limit=500):
                return SimpleNamespace(payload=[{
                    "id": "sell-order-254",
                    "symbol": "CRDO",
                    "side": "sell",
                    "status": "filled",
                    "filled_qty": 254,     # broker shows full fill
                    "filled_avg_price": 271.56,
                    "submitted_at": "2026-06-24T16:00:20+00:00",
                }])

            def fetch_latest_quote(self, symbol):
                return SimpleNamespace(payload={"quote": {"bp": 270.0, "ap": 272.0}})

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
                "ts": "2026-06-24T16:00:20+00:00",
                "submission_id": "sub-1",
                "side": "sell",
                "qty": 254,
                "symbol": "CRDO",
            }],
        )
        monkeypatch.setattr(reconcile_orders, "read_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "delete_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "purge_old_entries", lambda root, max_age_days=7: None)

        monkeypatch.setenv("BROKER_API_KEY", "key")
        monkeypatch.setenv("BROKER_API_SECRET", "secret")

        assert reconcile_orders.main() == 0
        out = capsys.readouterr().out
        summary_line = [ln for ln in out.splitlines() if ln.startswith(CRON_SUMMARY_PREFIX)][-1]
        payload = json.loads(summary_line.split("=", 1)[1])
        assert payload["status"] == "ok"
        assert payload["filled_exits_recorded"] == 1

        # All 254 shares must now be closed
        open_after = sum(
            t["qty"] for t in tracker.state.trades
            if t["status"] == "open" and t["symbol"] == "CRDO"
        )
        assert open_after == 0, f"Expected 0 open shares, got {open_after}"

        # All 3 lots plus the 51-share partial close should be recorded as closed
        closed = [t for t in tracker.state.trades if t["status"] == "closed" and t["symbol"] == "CRDO"]
        closed_qty = sum(t["qty"] for t in closed)
        assert closed_qty == 254, f"Expected 254 closed shares, got {closed_qty}"


def test_partial_fill_already_complete_is_not_replayed(monkeypatch, capsys):
    """If the broker fill was already fully recorded (partial-fill completion done),
    a subsequent reconcile run must not replay it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        tracker = PnLTracker(project_root)

        # Open 100 shares, then record a full exit of 100 shares
        tracker.record_submission(
            symbol="NVDA", strategy_id="test_strategy", side="buy",
            qty=100, price=500.0, broker_order_id="buy-nvda", decision_id="d-nvda",
        )
        tracker.record_exit(
            symbol="NVDA",
            exit_price=510.0,
            exit_qty=100,
            broker_order_id="sell-nvda-100",
            exit_reason="trailing_stop",
        )

        class StubBroker:
            def __init__(self, *args, **kwargs):
                pass

            def fetch_orders(self, status="all", limit=500):
                return SimpleNamespace(payload=[{
                    "id": "sell-nvda-100",
                    "symbol": "NVDA",
                    "side": "sell",
                    "status": "filled",
                    "filled_qty": 100,
                    "filled_avg_price": 510.0,
                    "submitted_at": "2026-06-24T15:00:00+00:00",
                }])

            def fetch_latest_quote(self, symbol):
                return SimpleNamespace(payload={"quote": {"bp": 509.0, "ap": 511.0}})

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
                "ts": "2026-06-24T15:00:00+00:00",
                "submission_id": "sub-nvda",
                "side": "sell",
                "qty": 100,
                "symbol": "NVDA",
            }],
        )
        monkeypatch.setattr(reconcile_orders, "read_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "delete_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "purge_old_entries", lambda root, max_age_days=7: None)

        monkeypatch.setenv("BROKER_API_KEY", "key")
        monkeypatch.setenv("BROKER_API_SECRET", "secret")

        assert reconcile_orders.main() == 0
        out = capsys.readouterr().out
        summary_line = [ln for ln in out.splitlines() if ln.startswith(CRON_SUMMARY_PREFIX)][-1]
        payload = json.loads(summary_line.split("=", 1)[1])
        assert payload["filled_exits_recorded"] == 0  # nothing new to record

        closed = [t for t in tracker.state.trades if t["status"] == "closed" and t["symbol"] == "NVDA"]
        assert len(closed) == 1
        assert closed[0]["qty"] == 100


def test_cancel_stale_sell_orders_cancels_non_catastrophic_offhours_exit():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        store_path = project_root / "data" / "tracking" / "pending_exit_reasons.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "sell-order-1": {
                        "symbol": "AMD",
                        "exit_reason": "breakeven_stop",
                        "return_pct": -0.0762,
                    }
                }
            ),
            encoding="utf-8",
        )

        class StubBroker:
            def __init__(self):
                self.cancelled = []

            def fetch_orders(self, status="open", limit=500):
                return SimpleNamespace(
                    payload=[
                        {
                            "id": "sell-order-1",
                            "symbol": "AMD",
                            "side": "sell",
                            "status": "accepted",
                            "time_in_force": "day",
                            "filled_qty": 0,
                            "submitted_at": "2026-06-07T01:34:06+00:00",
                        }
                    ]
                )

            def cancel_order(self, order_id):
                self.cancelled.append(order_id)

        broker = StubBroker()
        cancelled = reconcile_orders.cancel_stale_sell_orders(broker, project_root)

        assert cancelled == [
            {
                "order_id": "sell-order-1",
                "symbol": "AMD",
                "submitted_at": "2026-06-07T01:34:06+00:00",
                "reason": "offhours_moderate_sell",
            }
        ]
        assert broker.cancelled == ["sell-order-1"]
        assert json.loads(store_path.read_text(encoding="utf-8")) == {}


def test_cancel_stale_sell_orders_keeps_catastrophic_offhours_exit():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        store_path = project_root / "data" / "tracking" / "pending_exit_reasons.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "sell-order-1": {
                        "symbol": "MU",
                        "exit_reason": "breakeven_stop",
                        "return_pct": -0.1225,
                    }
                }
            ),
            encoding="utf-8",
        )

        class StubBroker:
            def __init__(self):
                self.cancelled = []

            def fetch_orders(self, status="open", limit=500):
                return SimpleNamespace(
                    payload=[
                        {
                            "id": "sell-order-1",
                            "symbol": "MU",
                            "side": "sell",
                            "status": "accepted",
                            "time_in_force": "day",
                            "filled_qty": 0,
                            "submitted_at": "2026-06-07T01:34:06+00:00",
                        }
                    ]
                )

            def cancel_order(self, order_id):
                self.cancelled.append(order_id)

        broker = StubBroker()
        cancelled = reconcile_orders.cancel_stale_sell_orders(broker, project_root)

        assert cancelled == []
        assert broker.cancelled == []
        assert "sell-order-1" in json.loads(store_path.read_text(encoding="utf-8"))
