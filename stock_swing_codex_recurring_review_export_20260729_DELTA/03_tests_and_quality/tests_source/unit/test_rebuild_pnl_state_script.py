from argparse import Namespace

from scripts.rebuild_pnl_state_from_broker import match_buy_sell_orders, resolve_tracking_metadata


def test_resolve_tracking_metadata_prefers_cli_over_existing_state():
    args = Namespace(
        baseline_equity=1000000.0,
        baseline_date='2026-05-12',
        created_at='2026-05-12T00:17:00+00:00',
        tracking_label='alpaca_account_epoch_2026-05-12',
        performance_scope='current_account_since_baseline',
        archive_path='data/archive/account_old',
        migration_note_path='docs/account_migration_2026-05-12.md',
    )
    existing = {
        'created_at': '2026-05-14T00:23:58+00:00',
        'baseline_date': '2026-05-14',
        'baseline_equity': 999999.0,
        'tracking_label': 'broker_rebuilt_20260514_002358',
        'performance_scope': 'broker_order_history',
        'archive_path': None,
        'migration_note_path': None,
        'archived_from_account_id': 'old-account',
    }

    resolved = resolve_tracking_metadata(args, existing, '2026-05-15T00:00:00+00:00')

    assert resolved['created_at'] == '2026-05-12T00:17:00+00:00'
    assert resolved['baseline_date'] == '2026-05-12'
    assert resolved['baseline_equity'] == 1000000.0
    assert resolved['tracking_label'] == 'alpaca_account_epoch_2026-05-12'
    assert resolved['performance_scope'] == 'current_account_since_baseline'
    assert resolved['archive_path'] == 'data/archive/account_old'
    assert resolved['migration_note_path'] == 'docs/account_migration_2026-05-12.md'
    assert resolved['archived_from_account_id'] == 'old-account'


def test_resolve_tracking_metadata_falls_back_to_existing_state():
    args = Namespace(
        baseline_equity=None,
        baseline_date=None,
        created_at=None,
        tracking_label=None,
        performance_scope=None,
        archive_path=None,
        migration_note_path=None,
    )
    existing = {
        'created_at': '2026-05-12T00:17:00+00:00',
        'baseline_date': '2026-05-12',
        'baseline_equity': 1000000.0,
        'tracking_label': 'alpaca_account_epoch_2026-05-12',
        'performance_scope': 'current_account_since_baseline',
        'archive_path': 'data/archive/account_old',
        'migration_note_path': 'docs/account_migration_2026-05-12.md',
        'archived_from_account_id': 'old-account',
    }

    resolved = resolve_tracking_metadata(args, existing, '2026-05-15T00:00:00+00:00')

    assert resolved == existing


def test_match_buy_sell_orders_preserves_buy_and_sell_order_ids():
    filled_orders = [
        {
            'id': 'buy-order-1',
            'symbol': 'ORCL',
            'side': 'buy',
            'status': 'filled',
            'filled_qty': 18,
            'filled_avg_price': 181.35,
            'filled_at': '2026-06-04T13:00:00+00:00',
        },
        {
            'id': 'sell-order-1',
            'symbol': 'ORCL',
            'side': 'sell',
            'status': 'filled',
            'filled_qty': 18,
            'filled_avg_price': 228.92,
            'filled_at': '2026-06-04T14:15:00+00:00',
        },
    ]

    trades, open_positions = match_buy_sell_orders(filled_orders)

    assert open_positions == []
    assert len(trades) == 1
    assert trades[0]['broker_order_id'] == 'buy-order-1'
    assert trades[0]['exit_broker_order_id'] == 'sell-order-1'


# ── 2026-07-17: --preserve-attribution テスト ──────────────────────────────

import json
import tempfile
from pathlib import Path

from scripts.rebuild_pnl_state_from_broker import (
    load_existing_attribution,
    apply_attribution,
)


def _make_state(trades: list, quarantined: list | None = None) -> dict:
    return {
        "trades": trades,
        "quarantined_trades": quarantined or [],
    }


def _closed(symbol, exit_reason, exit_broker_order_id="eid-1", exit_time="2026-06-01T17:00:00", pnl=100.0):
    return {
        "symbol": symbol,
        "status": "closed",
        "exit_reason": exit_reason,
        "exit_broker_order_id": exit_broker_order_id,
        "exit_time": exit_time,
        "pnl": pnl,
    }


def _write_state(tmp_dir: str, state: dict) -> Path:
    p = Path(tmp_dir) / "pnl_state.json"
    p.write_text(json.dumps(state), encoding="utf-8")
    return p


class TestLoadExistingAttribution:
    def test_indexes_non_broker_fill_by_exit_order_id(self, tmp_path):
        state = _make_state([
            _closed("NVDA", "trailing_stop", exit_broker_order_id="eid-ts"),
            _closed("AMD",  "stop_loss",     exit_broker_order_id="eid-sl"),
            _closed("INTC", "broker_fill",   exit_broker_order_id="eid-bf"),
        ])
        f = _write_state(str(tmp_path), state)
        attr = load_existing_attribution(f)
        assert attr["by_exit_order_id"]["eid-ts"] == "trailing_stop"
        assert attr["by_exit_order_id"]["eid-sl"] == "stop_loss"
        assert "eid-bf" not in attr["by_exit_order_id"]

    def test_indexes_by_key_fallback(self, tmp_path):
        state = _make_state([
            _closed("NVDA", "trailing_stop", exit_broker_order_id="",
                    exit_time="2026-06-01T17:00:00", pnl=500.0),
        ])
        f = _write_state(str(tmp_path), state)
        attr = load_existing_attribution(f)
        assert ("NVDA", "2026-06-01T17:00:00", 500) in attr["by_key"]

    def test_removes_ambiguous_key_collisions(self, tmp_path):
        """Same (sym, exit_time, pnl) with different exit_reasons → neither kept."""
        state = _make_state([
            _closed("AMZN", "trailing_stop", exit_broker_order_id="",
                    exit_time="2026-06-01T10:00:00", pnl=200.0),
            _closed("AMZN", "stop_loss",     exit_broker_order_id="",
                    exit_time="2026-06-01T10:00:00", pnl=200.0),
        ])
        f = _write_state(str(tmp_path), state)
        attr = load_existing_attribution(f)
        assert ("AMZN", "2026-06-01T10:00:00", 200) not in attr["by_key"]

    def test_preserves_quarantined_trades(self, tmp_path):
        quarantined = [{"trade_id": "q-1", "symbol": "FOO"}]
        state = _make_state([], quarantined=quarantined)
        f = _write_state(str(tmp_path), state)
        attr = load_existing_attribution(f)
        assert attr["quarantined_trades"] == quarantined

    def test_returns_empty_for_missing_file(self, tmp_path):
        f = tmp_path / "nonexistent.json"
        attr = load_existing_attribution(f)
        assert attr["by_exit_order_id"] == {}
        assert attr["by_key"] == {}
        assert attr["quarantined_trades"] == []


class TestApplyAttribution:
    def test_restores_by_exit_order_id(self):
        pnl_state = _make_state([
            _closed("NVDA", "broker_fill", exit_broker_order_id="eid-ts"),
        ])
        attribution = {
            "by_exit_order_id": {"eid-ts": "trailing_stop"},
            "by_key": {},
            "quarantined_trades": [],
        }
        stats = apply_attribution(pnl_state, attribution)
        assert pnl_state["trades"][0]["exit_reason"] == "trailing_stop"
        assert stats["by_exit_order"] == 1
        assert stats["by_key"] == 0
        assert stats["kept_broker_fill"] == 0

    def test_fallback_to_key(self):
        pnl_state = _make_state([
            _closed("AMD", "broker_fill", exit_broker_order_id="no-match",
                    exit_time="2026-06-02T10:00:00", pnl=300.0),
        ])
        attribution = {
            "by_exit_order_id": {},
            "by_key": {("AMD", "2026-06-02T10:00:00", 300): "stop_loss"},
            "quarantined_trades": [],
        }
        stats = apply_attribution(pnl_state, attribution)
        assert pnl_state["trades"][0]["exit_reason"] == "stop_loss"
        assert stats["by_key"] == 1

    def test_exit_order_id_wins_over_key(self):
        """exit_broker_order_id match takes priority over (sym,et,pnl) key."""
        pnl_state = _make_state([
            _closed("MSFT", "broker_fill", exit_broker_order_id="eid-x",
                    exit_time="2026-06-03T10:00:00", pnl=100.0),
        ])
        attribution = {
            "by_exit_order_id": {"eid-x": "trailing_stop"},
            "by_key": {("MSFT", "2026-06-03T10:00:00", 100): "stop_loss"},
            "quarantined_trades": [],
        }
        apply_attribution(pnl_state, attribution)
        assert pnl_state["trades"][0]["exit_reason"] == "trailing_stop"

    def test_keeps_broker_fill_when_no_match(self):
        pnl_state = _make_state([
            _closed("TSLA", "broker_fill", exit_broker_order_id="unknown-id"),
        ])
        attribution = {"by_exit_order_id": {}, "by_key": {}, "quarantined_trades": []}
        stats = apply_attribution(pnl_state, attribution)
        assert pnl_state["trades"][0]["exit_reason"] == "broker_fill"
        assert stats["kept_broker_fill"] == 1

    def test_restores_quarantined_trades(self):
        pnl_state = _make_state([])
        quarantined = [{"trade_id": "q-1", "symbol": "BAR", "exit_reason": "broker_fill"}]
        attribution = {"by_exit_order_id": {}, "by_key": {}, "quarantined_trades": quarantined}
        apply_attribution(pnl_state, attribution)
        assert pnl_state["quarantined_trades"] == quarantined

    def test_does_not_touch_already_attributed_trades(self):
        """Trades that already have a non-broker_fill reason are left unchanged."""
        pnl_state = _make_state([
            _closed("CRWD", "trailing_stop", exit_broker_order_id="eid-ts"),
        ])
        attribution = {
            "by_exit_order_id": {"eid-ts": "stop_loss"},  # would overwrite if applied
            "by_key": {},
            "quarantined_trades": [],
        }
        apply_attribution(pnl_state, attribution)
        # existing attribution unchanged because exit_reason != broker_fill
        assert pnl_state["trades"][0]["exit_reason"] == "trailing_stop"

    def test_skips_open_positions(self):
        pnl_state = {
            "trades": [{"symbol": "OPEN", "status": "open", "exit_reason": None}],
            "quarantined_trades": [],
        }
        attribution = {"by_exit_order_id": {}, "by_key": {}, "quarantined_trades": []}
        stats = apply_attribution(pnl_state, attribution)
        assert stats["by_exit_order"] == 0
        assert stats["by_key"] == 0
        assert stats["kept_broker_fill"] == 0

    def test_roundtrip_load_and_apply(self, tmp_path):
        """Full roundtrip: save state with attribution, load it, apply to fresh state."""
        original = _make_state(
            trades=[
                _closed("NVDA", "trailing_stop", exit_broker_order_id="eid-1",
                        exit_time="2026-06-01T15:00:00", pnl=800.0),
                _closed("AMD",  "stop_loss",     exit_broker_order_id="eid-2",
                        exit_time="2026-06-02T15:00:00", pnl=-400.0),
                _closed("INTC", "broker_fill",   exit_broker_order_id="eid-3",
                        exit_time="2026-06-03T15:00:00", pnl=-200.0),
            ],
            quarantined=[{"trade_id": "q-1", "symbol": "INTC"}],
        )
        f = _write_state(str(tmp_path), original)
        attr = load_existing_attribution(f)

        # Simulate rebuild: all broker_fill, no quarantine
        rebuilt = _make_state([
            _closed("NVDA", "broker_fill", exit_broker_order_id="eid-1",
                    exit_time="2026-06-01T15:00:00", pnl=800.0),
            _closed("AMD",  "broker_fill", exit_broker_order_id="eid-2",
                    exit_time="2026-06-02T15:00:00", pnl=-400.0),
            _closed("INTC", "broker_fill", exit_broker_order_id="eid-3",
                    exit_time="2026-06-03T15:00:00", pnl=-200.0),
        ])

        stats = apply_attribution(rebuilt, attr)

        assert rebuilt["trades"][0]["exit_reason"] == "trailing_stop"
        assert rebuilt["trades"][1]["exit_reason"] == "stop_loss"
        assert rebuilt["trades"][2]["exit_reason"] == "broker_fill"   # was broker_fill in original
        assert rebuilt["quarantined_trades"] == [{"trade_id": "q-1", "symbol": "INTC"}]
        assert stats["by_exit_order"] == 2   # NVDA + AMD
        assert stats["kept_broker_fill"] == 1  # INTC
