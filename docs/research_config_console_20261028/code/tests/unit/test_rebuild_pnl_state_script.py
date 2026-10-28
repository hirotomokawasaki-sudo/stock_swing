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


# ── 2026-08-23: provenance preservation regression tests ────────────────────────────
# Background: a rebuild run on 2026-08-23 silently overwrote strategy_id/
# original_strategy_id/decision_id/run_id/experiment_id on ALL closed trades
# with the rebuild's 'broker_reconstructed' placeholder -- including 49
# trades that had REAL strategy attribution (submitted live by PaperExecutor
# with a real decision_id). This turned attributable_count 49 -> 0, caught
# only by tests/unit/test_r8v2_ml_readiness.py's real-data sanity check.
# Restored from backup; apply_attribution()/load_existing_attribution() were
# then extended to also preserve PROVENANCE_FIELDS. These tests guard against
# that regression recurring.

def _closed_with_provenance(
    symbol, exit_reason, strategy_id, original_strategy_id,
    exit_broker_order_id="eid-1", exit_time="2026-06-01T17:00:00", pnl=100.0,
    decision_id=None, run_id=None, experiment_id=None,
):
    trade = _closed(symbol, exit_reason, exit_broker_order_id, exit_time, pnl)
    trade["strategy_id"] = strategy_id
    trade["original_strategy_id"] = original_strategy_id
    if decision_id is not None:
        trade["decision_id"] = decision_id
    if run_id is not None:
        trade["run_id"] = run_id
    if experiment_id is not None:
        trade["experiment_id"] = experiment_id
    return trade


class TestProvenancePreservation:
    def test_load_existing_attribution_indexes_real_provenance_by_exit_order_id(self, tmp_path):
        state = _make_state([
            _closed_with_provenance(
                "AMZN", "stop_loss", "breakout_momentum_v1", "breakout_momentum_v1",
                exit_broker_order_id="eid-real", decision_id="dec-123", run_id="run-456",
            ),
        ])
        f = _write_state(str(tmp_path), state)
        attr = load_existing_attribution(f)
        prov = attr["provenance_by_exit_order_id"]["eid-real"]
        assert prov["strategy_id"] == "breakout_momentum_v1"
        assert prov["original_strategy_id"] == "breakout_momentum_v1"
        assert prov["decision_id"] == "dec-123"
        assert prov["run_id"] == "run-456"

    def test_load_existing_attribution_does_not_index_rebuild_synthesized_origin(self, tmp_path):
        """A trade whose origin IS the rebuild placeholder must not be
        indexed as 'real provenance' -- it has nothing meaningful to
        restore, and indexing it would just re-apply the placeholder,
        which is a no-op at best and a footgun if the placeholder logic
        ever changes."""
        state = _make_state([
            _closed_with_provenance(
                "IBM", "broker_fill", "broker_reconstructed", "broker_reconstructed",
                exit_broker_order_id="eid-synth",
            ),
        ])
        f = _write_state(str(tmp_path), state)
        attr = load_existing_attribution(f)
        assert "eid-synth" not in attr["provenance_by_exit_order_id"]

    def test_load_existing_attribution_indexes_real_provenance_even_with_broker_fill_exit_reason(self, tmp_path):
        """A real-strategy-origin trade whose EXIT was never specifically
        attributed (exit_reason=='broker_fill') must still have its
        provenance indexed -- provenance and exit_reason are independent."""
        state = _make_state([
            _closed_with_provenance(
                "NVDA", "broker_fill", "event_swing_v1", "event_swing_v1",
                exit_broker_order_id="eid-partial",
            ),
        ])
        f = _write_state(str(tmp_path), state)
        attr = load_existing_attribution(f)
        assert "eid-partial" in attr["provenance_by_exit_order_id"]

    def test_apply_attribution_restores_provenance_fields_onto_rebuilt_trade(self):
        """THE core regression test: a freshly-rebuilt trade (strategy_id=
        'broker_reconstructed', as match_buy_sell_orders() always produces)
        must have its REAL provenance restored when the pre-rebuild state
        had it, exactly reproducing the 2026-08-23 incident scenario."""
        pnl_state = _make_state([
            _closed_with_provenance(
                "AMZN", "stop_loss", "broker_reconstructed", "broker_reconstructed",
                exit_broker_order_id="eid-real", exit_time="2026-08-03T13:36:00", pnl=-5262.92,
            ),
        ])
        attribution = {
            "by_exit_order_id": {},
            "by_key": {},
            "quarantined_trades": [],
            "provenance_by_exit_order_id": {
                "eid-real": {
                    "strategy_id": "breakout_momentum_v2_threshold_tuned",
                    "original_strategy_id": "breakout_momentum_v1",
                    "decision_id": "fced5063-1321-710b-972c-6e431534f337",
                    "run_id": "paper_demo-20260803T133503Z-0e593286",
                },
            },
            "provenance_by_key": {},
        }
        stats = apply_attribution(pnl_state, attribution)
        trade = pnl_state["trades"][0]
        assert trade["strategy_id"] == "breakout_momentum_v2_threshold_tuned"
        assert trade["original_strategy_id"] == "breakout_momentum_v1"
        assert trade["decision_id"] == "fced5063-1321-710b-972c-6e431534f337"
        assert trade["run_id"] == "paper_demo-20260803T133503Z-0e593286"
        assert stats["provenance_restored"] == 1

    def test_apply_attribution_falls_back_to_key_when_exit_order_id_not_indexed(self):
        pnl_state = _make_state([
            _closed_with_provenance(
                "MSFT", "trailing_stop", "broker_reconstructed", "broker_reconstructed",
                exit_broker_order_id="no-match-id", exit_time="2026-08-12T16:00:00", pnl=1011.71,
            ),
        ])
        attribution = {
            "by_exit_order_id": {},
            "by_key": {},
            "quarantined_trades": [],
            "provenance_by_exit_order_id": {},
            "provenance_by_key": {
                ("MSFT", "2026-08-12T16:00:00", 1012): {"strategy_id": "breakout_momentum_v1"},
            },
        }
        stats = apply_attribution(pnl_state, attribution)
        assert pnl_state["trades"][0]["strategy_id"] == "breakout_momentum_v1"
        assert stats["provenance_restored"] == 1

    def test_apply_attribution_does_not_touch_trades_with_no_saved_provenance(self):
        """A genuinely rebuild-only trade (no matching provenance entry)
        must be left as 'broker_reconstructed' -- this is correct, not a
        bug: it really has no known strategy origin."""
        pnl_state = _make_state([
            _closed_with_provenance(
                "IBM", "broker_fill", "broker_reconstructed", "broker_reconstructed",
                exit_broker_order_id="eid-truly-unknown",
            ),
        ])
        attribution = {
            "by_exit_order_id": {}, "by_key": {}, "quarantined_trades": [],
            "provenance_by_exit_order_id": {}, "provenance_by_key": {},
        }
        stats = apply_attribution(pnl_state, attribution)
        assert pnl_state["trades"][0]["strategy_id"] == "broker_reconstructed"
        assert stats["provenance_restored"] == 0

    def test_full_roundtrip_load_and_apply_preserves_provenance_across_simulated_rebuild(self, tmp_path):
        """End-to-end reproduction of the 2026-08-23 incident: save a state
        with real provenance, load its attribution, apply it to a
        freshly-'rebuilt' state (all fields reset to broker_reconstructed,
        as a real rebuild would produce), and confirm provenance survives.
        """
        original = _make_state([
            _closed_with_provenance(
                "AMZN", "stop_loss", "breakout_momentum_v2_threshold_tuned",
                "breakout_momentum_v1", exit_broker_order_id="eid-1",
                exit_time="2026-08-03T13:36:00", pnl=-5262.92,
                decision_id="dec-amzn", run_id="run-amzn", experiment_id="exp-amzn",
            ),
            _closed_with_provenance(
                "IBM", "broker_fill", "broker_reconstructed", "broker_reconstructed",
                exit_broker_order_id="eid-2", exit_time="2026-06-01T10:00:00", pnl=-500.0,
            ),
        ])
        f = _write_state(str(tmp_path), original)
        attr = load_existing_attribution(f)

        # Simulate what a real rebuild produces: strategy_id/original_
        # strategy_id RESET to the placeholder for every trade, regardless
        # of prior real attribution (this is exactly what match_buy_sell_
        # orders() does -- it has no way to know a trade was previously
        # attributed).
        rebuilt = _make_state([
            _closed_with_provenance(
                "AMZN", "broker_fill", "broker_reconstructed", "broker_reconstructed",
                exit_broker_order_id="eid-1", exit_time="2026-08-03T13:36:00", pnl=-5262.92,
            ),
            _closed_with_provenance(
                "IBM", "broker_fill", "broker_reconstructed", "broker_reconstructed",
                exit_broker_order_id="eid-2", exit_time="2026-06-01T10:00:00", pnl=-500.0,
            ),
        ])

        stats = apply_attribution(rebuilt, attr)

        amzn_trade = rebuilt["trades"][0]
        ibm_trade = rebuilt["trades"][1]
        assert amzn_trade["strategy_id"] == "breakout_momentum_v2_threshold_tuned"
        assert amzn_trade["original_strategy_id"] == "breakout_momentum_v1"
        assert amzn_trade["decision_id"] == "dec-amzn"
        assert amzn_trade["exit_reason"] == "stop_loss"  # also restored via existing mechanism
        # IBM had no real provenance before rebuild -- must remain rebuild-synthesized.
        assert ibm_trade["strategy_id"] == "broker_reconstructed"
        assert stats["provenance_restored"] == 1
