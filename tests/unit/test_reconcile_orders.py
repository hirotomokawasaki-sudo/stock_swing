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
