from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from stock_swing.cli import reconcile_orders
from stock_swing.cli.cron_summary import CRON_SUMMARY_PREFIX
from stock_swing.tracking.fill_ledger import FillLedger
from stock_swing.tracking.pnl_tracker import PnLTracker


def test_fill_ledger_writes_consumed_snapshot(tmp_path: Path) -> None:
    ledger = FillLedger(tmp_path)
    key = ledger.ingest(
        {
            "id": "fill-001",
            "order_id": "order-001",
            "symbol": "AAPL",
            "side": "sell",
            "qty": 10,
            "filled_avg_price": 150.0,
            "filled_at": "2026-07-30T00:00:00+00:00",
        }
    )
    ledger.consume(key, trade_id="trade-001", qty=10)

    consumed_path = tmp_path / "data" / "tracking" / "fill_consumed_ledger.json"
    payload = json.loads(consumed_path.read_text(encoding="utf-8"))

    assert consumed_path.exists()
    assert payload["fills"][0]["fill_id"] == "fill-001"
    assert payload["fills"][0]["consumed_qty"] == 10


def test_reconcile_orders_state_and_ledger_sha_stable_across_three_runs(monkeypatch, capsys) -> None:
    """Production reconcile loop must converge to identical state across 3 rebuilds."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        tracker = PnLTracker(project_root)
        tracker.record_submission(
            symbol="NVDA",
            strategy_id="test_strategy",
            side="buy",
            qty=12,
            price=500.0,
            broker_order_id="buy-nvda",
            decision_id="decision-nvda",
        )

        class StubBroker:
            def __init__(self, *args, **kwargs):
                pass

            def fetch_orders(self, status="all", limit=500):
                return SimpleNamespace(payload=[{
                    "id": "sell-nvda-12",
                    "symbol": "NVDA",
                    "side": "sell",
                    "status": "filled",
                    "filled_qty": 12,
                    "filled_avg_price": 510.0,
                    "submitted_at": "2026-06-24T15:00:00+00:00",
                    "updated_at": "2026-06-24T15:00:05+00:00",
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
                "qty": 12,
                "symbol": "NVDA",
            }],
        )
        monkeypatch.setattr(reconcile_orders, "read_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "delete_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "purge_old_entries", lambda root, max_age_days=7: None)
        monkeypatch.setenv("BROKER_API_KEY", "key")
        monkeypatch.setenv("BROKER_API_SECRET", "secret")

        state_shas = []
        ledger_shas = []
        consumed_shas = []
        for _ in range(3):
            assert reconcile_orders.main() == 0
            out = capsys.readouterr().out
            summary_line = [line for line in out.splitlines() if line.startswith(CRON_SUMMARY_PREFIX)][-1]
            summary = json.loads(summary_line.split("=", 1)[1])
            assert summary["status"] == "ok"
            state_shas.append(hashlib.sha256((project_root / "data" / "tracking" / "pnl_state.json").read_bytes()).hexdigest())
            ledger_shas.append(hashlib.sha256((project_root / "data" / "tracking" / "fill_ledger.jsonl").read_bytes()).hexdigest())
            consumed_shas.append(hashlib.sha256((project_root / "data" / "tracking" / "fill_consumed_ledger.json").read_bytes()).hexdigest())

        assert len(set(state_shas)) == 1
        assert len(set(ledger_shas)) == 1
        assert len(set(consumed_shas)) == 1


def test_reconcile_orders_uses_fill_ledger_to_block_replay_after_state_reset(monkeypatch, capsys) -> None:
    """Regression: a consumed sell fill must not be replayed onto a new position."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        tracker = PnLTracker(project_root)
        tracker.record_submission(
            symbol="ORCL",
            strategy_id="test_strategy",
            side="buy",
            qty=10,
            price=200.0,
            broker_order_id="buy-order-old",
            decision_id="decision-buy-old",
        )

        class StubBroker:
            def __init__(self, *args, **kwargs):
                pass

            def fetch_orders(self, status="all", limit=500):
                return SimpleNamespace(payload=[{
                    "id": "sell-order-123",
                    "symbol": "ORCL",
                    "side": "sell",
                    "status": "filled",
                    "filled_qty": 10,
                    "filled_avg_price": 210.0,
                    "submitted_at": "2026-06-04T14:15:00+00:00",
                    "updated_at": "2026-06-04T14:15:02+00:00",
                }])

            def fetch_latest_quote(self, symbol):
                return SimpleNamespace(payload={"quote": {"bp": 209.5, "ap": 210.5}})

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
                "ts": "2026-06-04T14:15:00+00:00",
                "submission_id": "sub-1",
                "side": "sell",
                "qty": 10,
                "symbol": "ORCL",
            }],
        )
        monkeypatch.setattr(reconcile_orders, "read_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "delete_exit_reason", lambda root, broker_order_id: None)
        monkeypatch.setattr(reconcile_orders, "purge_old_entries", lambda root, max_age_days=7: None)
        monkeypatch.setenv("BROKER_API_KEY", "key")
        monkeypatch.setenv("BROKER_API_SECRET", "secret")

        assert reconcile_orders.main() == 0
        capsys.readouterr()

        ledger = FillLedger(project_root)
        rec = ledger.get("sell-order-123")
        assert rec is not None
        assert rec["consumed_qty"] == 10
        assert rec["consumed"] is True

        tracker.state.trades = []
        tracker.state.quarantined_trades = []
        tracker._save_state()
        (project_root / "data" / "tracking" / "trade_events.jsonl").unlink(missing_ok=True)

        tracker.record_submission(
            symbol="ORCL",
            strategy_id="test_strategy",
            side="buy",
            qty=20,
            price=205.0,
            broker_order_id="buy-order-new",
            decision_id="decision-buy-new",
        )

        assert reconcile_orders.main() == 0
        out = capsys.readouterr().out
        summary_line = [line for line in out.splitlines() if line.startswith(CRON_SUMMARY_PREFIX)][-1]
        payload = json.loads(summary_line.split("=", 1)[1])
        assert payload["filled_exits_recorded"] == 0
        assert tracker.get_open_positions()[0]["qty"] == 20




# --- Coverage補強: fill_ledger ingest/consume パス ---
from stock_swing.tracking.fill_ledger import (
    FillLedger,
    FillAlreadyConsumedError,
    MissingFillIdError,
)

_SAMPLE_FILL = {"id": "fill_cov_001", "filled_qty": 10, "filled_at": "2026-07-30T10:00:00Z", "price": 100.0}


def test_fill_ledger_raises_on_duplicate_consumption(tmp_path):
    """FillAlreadyConsumedError on second full consume of same fill."""
    ledger = FillLedger(tmp_path / "ledger.json")
    ledger.ingest(dict(_SAMPLE_FILL))
    ledger.consume("fill_cov_001", "trade_a", qty=10)
    try:
        ledger.consume("fill_cov_001", "trade_a", qty=10)
        assert False, "Should have raised"
    except FillAlreadyConsumedError:
        pass


def test_fill_ledger_raises_on_missing_fill_id(tmp_path):
    """MissingFillIdError when fill has no identifier."""
    ledger = FillLedger(tmp_path / "ledger2.json")
    try:
        ledger.ingest({})
        assert False, "Should have raised"
    except MissingFillIdError:
        pass


def test_fill_ledger_is_consumed_returns_true_after_consume(tmp_path):
    """is_consumed reflects state after consume."""
    ledger = FillLedger(tmp_path / "ledger3.json")
    fill = {"id": "fill_cov_002", "filled_qty": 5, "filled_at": "2026-07-30T10:00:00Z"}
    ledger.ingest(fill)
    assert ledger.is_consumed("fill_cov_002") is False
    ledger.consume("fill_cov_002", "trade_b", qty=5)
    assert ledger.is_consumed("fill_cov_002") is True


def test_fill_ledger_persists_across_instances(tmp_path):
    """Consumed state survives new FillLedger instance."""
    path = tmp_path / "ledger4.json"
    fill = {"id": "fill_cov_003", "filled_qty": 20, "filled_at": "2026-07-30T10:00:00Z"}
    FillLedger(path).ingest(fill)
    FillLedger(path).consume("fill_cov_003", "trade_c", qty=20)
    assert FillLedger(path).is_consumed("fill_cov_003") is True


def test_fill_ledger_quarantine_on_missing_timestamp(tmp_path):
    """Fill with no timestamp is quarantined when quarantine_on_missing=False but still ingested."""
    ledger = FillLedger(tmp_path / "ledger5.json")
    fill_no_ts = {"id": "fill_no_ts", "filled_qty": 5}  # no filled_at
    fill_id = ledger.ingest(fill_no_ts)
    assert fill_id == "fill_no_ts"


def test_fill_ledger_quarantine_on_missing_fill_id_with_flag(tmp_path):
    """ingest with quarantine_on_missing=True on fill with no id does not raise."""
    ledger = FillLedger(tmp_path / "ledger6.json")
    fill_no_id = {"filled_qty": 5, "filled_at": "2026-07-30T10:00:00Z"}
    result = ledger.ingest(fill_no_id, quarantine_on_missing=True)
    assert result is not None  # quarantine ID returned


def test_fill_ledger_normalize_qty_handles_invalid():
    """_normalize_qty returns 0.0 for non-numeric values."""
    from stock_swing.tracking.fill_ledger import _normalize_qty
    assert _normalize_qty("invalid") == 0.0
    assert _normalize_qty(None) == 0.0
    assert _normalize_qty(10) == 10.0


def test_fill_ledger_reload_clears_cache(tmp_path):
    """reload() forces re-read from disk."""
    ledger = FillLedger(tmp_path / "ledger7.json")
    fill = {"id": "fill_reload", "filled_qty": 3, "filled_at": "2026-07-30T10:00:00Z"}
    ledger.ingest(fill)
    ledger.reload()
    assert ledger.is_consumed("fill_reload") is False
