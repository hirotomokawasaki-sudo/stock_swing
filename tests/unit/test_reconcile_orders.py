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
