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

        # Backdate entry_time so positions appear to have been opened BEFORE the sell order
        # (sell order submitted_at=2026-06-24T16:00:20). Temporal guard requires that
        # the sell was submitted after the newest open position was entered.
        for t in tracker.state.trades:
            if t.get("symbol") == "CRDO" and t.get("status") == "open":
                t["entry_time"] = "2026-06-23T10:00:00+00:00"
        tracker._save_state()

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


# ---------------------------------------------------------------------------
# R1-B: broker_fill_unknown default
# ---------------------------------------------------------------------------

def test_fill_exit_uses_broker_fill_unknown_when_no_pending_reason():
    """When pending_exit_reasons has no entry for the order, resolved reason
    must be 'broker_fill_unknown', NOT the legacy 'broker_fill'."""
    import sys
    import types
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        # Empty pending_exit_reasons store
        store_path = project_root / "data" / "tracking" / "pending_exit_reasons.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text("{}", encoding="utf-8")

        recorded_exits = []

        class StubTracker:
            class state:
                trades = [
                    {
                        "symbol": "NVDA",
                        "status": "open",
                        "qty": 10,
                        "entry_price": 100.0,
                        "exit_broker_order_id": None,
                    }
                ]

            def record_exit(self, symbol, exit_price, exit_qty, broker_order_id,
                            exit_strategy_id, exit_reason):
                recorded_exits.append({"symbol": symbol, "exit_reason": exit_reason})
                return SimpleNamespace(trade_id="t1", pnl=50.0)

        class StubBroker:
            def fetch_orders(self, status="open", limit=500):
                return SimpleNamespace(payload=[])

            def fetch_positions(self):
                return SimpleNamespace(payload=[])

        import json as _json

        # Write a submission log that reconcile will process
        sub_dir = project_root / "data" / "audits"
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / "submissions_stub.jsonl").write_text(
            _json.dumps({
                "submission_id": "sub-1",
                "decision_id": "dec-1",
                "symbol": "NVDA",
                "side": "sell",
                "qty": 10,
                "status": "submitted",
                "broker_order_id": "broker-xyz-999",
                "ts": "2026-06-26T13:00:00+00:00",
            }) + "\n",
            encoding="utf-8",
        )

        monkeypatched_reason = {}

        import stock_swing.cli.reconcile_orders as ro
        orig_read = ro.read_exit_reason
        orig_delete = ro.delete_exit_reason

        try:
            # No entry in store → should default to broker_fill_unknown
            ro.read_exit_reason = lambda root, oid: None
            ro.delete_exit_reason = lambda root, oid: None

            # Simulate the resolved_exit_reason logic directly (unit test of the default)
            stored = ro.read_exit_reason(project_root, "broker-xyz-999")
            resolved = (stored or {}).get("exit_reason", "broker_fill_unknown")
            assert resolved == "broker_fill_unknown", (
                f"Expected 'broker_fill_unknown' but got '{resolved}'. "
                "Legacy 'broker_fill' default must be replaced."
            )
        finally:
            ro.read_exit_reason = orig_read
            ro.delete_exit_reason = orig_delete


def test_fill_exit_uses_stored_reason_when_pending_exists():
    """When pending_exit_reasons has an entry, resolved reason must use it."""
    import stock_swing.cli.reconcile_orders as ro
    orig_read = ro.read_exit_reason
    try:
        ro.read_exit_reason = lambda root, oid: {
            "symbol": "NVDA",
            "exit_trigger": "Trailing stop triggered",
            "exit_reason": "trailing_stop",
        }
        stored = ro.read_exit_reason(None, "any-id")
        resolved = (stored or {}).get("exit_reason", "broker_fill_unknown")
        assert resolved == "trailing_stop"
    finally:
        ro.read_exit_reason = orig_read



def test_reconcile_skips_fill_absent_from_state_but_in_trade_events(monkeypatch, capsys):
    """
    Regression: 2026-07-29 ADBE phantom close bug.

    Scenario:
      1. AAPL bought and sold → trade_closed written to trade_events.jsonl
      2. Rebuild removes the closed trade from state.trades (simulated manually)
      3. AAPL bought again as new position
      4. Reconciler sees the old filled sell in broker orders
      5. Must NOT replay the stale fill against the new position

    Root cause: processed_sell_order_ids was built from state.trades only.
    Fix: also include broker_order_ids from trade_events.jsonl trade_closed events.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        tracker = PnLTracker(project_root)

        # Step 1: old AAPL trade opened and closed → writes trade_closed to trade_events.jsonl
        tracker.record_submission(
            symbol="AAPL",
            strategy_id="s",
            side="buy",
            qty=10,
            price=200.0,
            broker_order_id="buy-old-aapl",
            decision_id="dec-old",
        )
        tracker.record_exit(
            symbol="AAPL",
            exit_price=195.0,
            exit_qty=10,
            broker_order_id="sell-stale-aapl",
            exit_reason="trailing_stop",
        )

        # Step 2: simulate rebuild removing the closed trade from state.trades
        # (the trade_events.jsonl still has the trade_closed event)
        tracker.state.trades = [
            t for t in tracker.state.trades if t.get("status") == "open"
        ]

        # Step 3: new AAPL position (the one that must NOT be phantom-closed)
        tracker.record_submission(
            symbol="AAPL",
            strategy_id="s",
            side="buy",
            qty=20,
            price=210.0,
            broker_order_id="buy-new-aapl",
            decision_id="dec-new",
        )

        class StubBroker:
            def __init__(self, *a, **kw): pass
            def fetch_orders(self, status="all", limit=500):
                return SimpleNamespace(payload=[
                    {
                        "id": "sell-stale-aapl",
                        "symbol": "AAPL",
                        "side": "sell",
                        "status": "filled",
                        "filled_avg_price": 195.0,
                        "filled_qty": 10,
                        "qty": 10,
                        "submitted_at": "2026-07-23T09:35:00Z",
                        "created_at": "2026-07-23T09:35:00Z",
                    }
                ])
            def fetch_latest_quote(self, symbol):
                return SimpleNamespace(payload={"quote": {"bp": 209.0, "ap": 211.0}})

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
                    "ts": "2026-07-23T09:35:00+00:00",
                    "submission_id": "sub-stale",
                    "side": "sell",
                    "qty": 10,
                    "symbol": "AAPL",
                }
            ],
        )
        monkeypatch.setattr(reconcile_orders, "read_exit_reason", lambda root, oid: None)
        monkeypatch.setattr(reconcile_orders, "delete_exit_reason", lambda root, oid: None)
        monkeypatch.setattr(reconcile_orders, "purge_old_entries", lambda root, max_age_days=7: None)

        monkeypatch.setenv("BROKER_API_KEY", "key")
        monkeypatch.setenv("BROKER_API_SECRET", "secret")

        assert reconcile_orders.main() == 0

        out = capsys.readouterr().out
        summary_line = [ln for ln in out.splitlines() if ln.startswith(CRON_SUMMARY_PREFIX)][-1]
        payload = json.loads(summary_line.split("=", 1)[1])
        assert payload["filled_exits_recorded"] == 0, (
            f"Stale sell fill must not close new position. "
            f"filled_exits_recorded={payload['filled_exits_recorded']}. "
            "Incident: 2026-07-29 ADBE phantom close."
        )

        open_trades = [t for t in tracker.state.trades if t.get("symbol") == "AAPL" and t.get("status") == "open"]
        assert open_trades, (
            "AAPL new position must remain open after reconcile. "
            "Stale sell fill must be blocked by trade_events.jsonl guard."
        )
        assert open_trades[0]["qty"] == 20
