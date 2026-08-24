"""Regression tests for two 2026-08-24 bugs found while executing a real
rebuild + quarantine migration:

1. scripts/rebuild_pnl_state_from_broker.py's apply_tombstone_filter() only
   recomputed total_trades/cumulative_realized_pnl after removing
   tombstone-matched trades, but NOT winning_trades/losing_trades. Live
   symptom: a 5-trade tombstone filter left winning_trades=164/
   losing_trades=176 (summing to the PRE-filter 341-trade closed count)
   while the actual post-filter closed list (336 trades: 163 wins / 172
   losses / 1 zero-pnl trade) had different true counts.

2. scripts/migrate_quarantine_invalid_trades.py moved trades out of
   state.trades (closed) into quarantined_trades but never adjusted
   cumulative_realized_pnl/winning_trades/losing_trades to compensate,
   so a single -$900 CRWD quarantine left cumulative_realized_pnl
   diverging from sum(closed.pnl) by exactly $900 (caught by
   verify_rebuild_integrity.py's check_pnl_consistency()).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from rebuild_pnl_state_from_broker import apply_tombstone_filter  # noqa: E402


def _trade(trade_id, symbol, pnl, status="closed", broker_order_id="", exit_broker_order_id=""):
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "status": status,
        "pnl": pnl,
        "broker_order_id": broker_order_id,
        "exit_broker_order_id": exit_broker_order_id,
    }


class TestApplyTombstoneFilterRecomputesWinLossCounts:
    def test_removing_a_winning_trade_decrements_winning_trades_count(self):
        pnl_state = {
            "trades": [
                _trade("t1", "AAA", pnl=100.0, broker_order_id="e1", exit_broker_order_id="x1"),
                _trade("t2", "BBB", pnl=-50.0, broker_order_id="e2", exit_broker_order_id="x2"),
            ],
            "winning_trades": 1,  # pre-filter count (as calculate_summary() would compute)
            "losing_trades": 1,
        }
        # Tombstone matches t1 (a winning trade) by its order-ID pair.
        quarantined_trades = [{"broker_order_id": "e1", "exit_broker_order_id": "x1"}]

        removed = apply_tombstone_filter(pnl_state, quarantined_trades)

        assert removed == 1
        assert pnl_state["winning_trades"] == 0, (
            "removing the tombstoned winning trade must decrement winning_trades"
        )
        assert pnl_state["losing_trades"] == 1

    def test_removing_a_losing_trade_decrements_losing_trades_count(self):
        pnl_state = {
            "trades": [
                _trade("t1", "AAA", pnl=100.0, broker_order_id="e1", exit_broker_order_id="x1"),
                _trade("t2", "BBB", pnl=-50.0, broker_order_id="e2", exit_broker_order_id="x2"),
            ],
            "winning_trades": 1,
            "losing_trades": 1,
        }
        quarantined_trades = [{"broker_order_id": "e2", "exit_broker_order_id": "x2"}]

        apply_tombstone_filter(pnl_state, quarantined_trades)

        assert pnl_state["winning_trades"] == 1
        assert pnl_state["losing_trades"] == 0

    def test_recomputed_counts_match_actual_kept_trades_not_arithmetic_subtraction(self):
        """Regression (matches the live incident's exact shape): recompute
        from the KEPT trade list directly, not by decrementing the old
        (already-correct-looking but coincidentally wrong) counters --
        this guards against a future edit reintroducing an off-by-N drift
        if calculate_summary()'s pre-filter counts were ever themselves
        wrong for an unrelated reason.
        """
        pnl_state = {
            "trades": [
                _trade("t1", "AAA", pnl=100.0, broker_order_id="e1", exit_broker_order_id="x1"),
                _trade("t2", "BBB", pnl=-50.0, broker_order_id="e2", exit_broker_order_id="x2"),
                _trade("t3", "CCC", pnl=200.0, broker_order_id="e3", exit_broker_order_id="x3"),
                _trade("t4", "DDD", pnl=0.0, broker_order_id="e4", exit_broker_order_id="x4"),
            ],
            # Deliberately WRONG pre-filter counters (simulating any upstream
            # drift) -- the fix must derive counts from the post-filter
            # `kept` list, not trust these inputs.
            "winning_trades": 999,
            "losing_trades": 999,
        }
        quarantined_trades = [{"broker_order_id": "e1", "exit_broker_order_id": "x1"}]

        apply_tombstone_filter(pnl_state, quarantined_trades)

        remaining_closed = pnl_state["trades"]
        assert len(remaining_closed) == 3
        assert pnl_state["winning_trades"] == 1  # only t3 remains a winner
        assert pnl_state["losing_trades"] == 1   # only t2 remains a loser

    def test_no_tombstone_hits_leaves_counts_untouched(self):
        pnl_state = {
            "trades": [_trade("t1", "AAA", pnl=100.0, broker_order_id="e1", exit_broker_order_id="x1")],
            "winning_trades": 1,
            "losing_trades": 0,
        }
        removed = apply_tombstone_filter(pnl_state, quarantined_trades=[])
        assert removed == 0
        # Counts must be left exactly as-is when nothing was removed.
        assert pnl_state["winning_trades"] == 1
        assert pnl_state["losing_trades"] == 0

    def test_recomputed_cumulative_pnl_and_win_loss_counts_stay_mutually_consistent(self):
        """After a tombstone removal, sum(closed.pnl) must equal
        cumulative_realized_pnl AND winning+losing (+zero-pnl trades not
        counted in either) must equal len(closed) -- the exact pair of
        invariants verify_rebuild_integrity.py's check_pnl_consistency()
        and (implicitly) win-rate reporting depend on.
        """
        pnl_state = {
            "trades": [
                _trade("t1", "AAA", pnl=100.0, broker_order_id="e1", exit_broker_order_id="x1"),
                _trade("t2", "BBB", pnl=-50.0, broker_order_id="e2", exit_broker_order_id="x2"),
                _trade("t3", "CCC", pnl=200.0, broker_order_id="e3", exit_broker_order_id="x3"),
            ],
            "winning_trades": 2,
            "losing_trades": 1,
        }
        quarantined_trades = [{"broker_order_id": "e1", "exit_broker_order_id": "x1"}]

        apply_tombstone_filter(pnl_state, quarantined_trades)

        closed = [t for t in pnl_state["trades"] if t.get("status") == "closed"]
        assert pnl_state["cumulative_realized_pnl"] == pytest.approx(sum(t["pnl"] for t in closed))
        assert pnl_state["winning_trades"] + pnl_state["losing_trades"] == len(closed)


class TestMigrateQuarantineUpdatesAggregates:
    """These tests exercise scripts/migrate_quarantine_invalid_trades.py's
    main() via a subprocess-free, direct-import approach is not practical
    (the script is structured as a CLI script with argparse in main()), so
    this test drives it through its actual file-based interface using
    tmp_path, mirroring how the live incident was reproduced.
    """

    def _run_migration(self, tmp_path, state: dict) -> dict:
        import subprocess

        state_dir = tmp_path / "data" / "tracking"
        state_dir.mkdir(parents=True)
        state_path = state_dir / "pnl_state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        # The script resolves paths via `project_root = Path(__file__).
        # resolve().parents[1]`, i.e. relative to its own location, not an
        # injectable root -- so we monkeypatch its module-level
        # `project_root`/state path resolution instead of relying on cwd.
        script_path = PROJECT_ROOT / "scripts" / "migrate_quarantine_invalid_trades.py"
        # Simplest robust approach: import the module and monkeypatch its
        # global `project_root`, then call main() in-process.
        import importlib.util
        spec = importlib.util.spec_from_file_location("migrate_quarantine_invalid_trades_test", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.project_root = tmp_path

        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ["migrate_quarantine_invalid_trades.py", "--backup"]
        try:
            module.main()
        finally:
            _sys.argv = old_argv

        return json.loads(state_path.read_text(encoding="utf-8"))

    def test_quarantining_a_negative_trade_reduces_cumulative_realized_pnl(self, tmp_path):
        state = {
            "trades": [
                {
                    "trade_id": "t1", "symbol": "CRWD", "status": "closed",
                    "entry_time": "2026-08-11T13:35:36Z", "exit_time": "2026-07-15T16:00:50Z",
                    "pnl": -900.0,
                },
                {
                    "trade_id": "t2", "symbol": "AAA", "status": "closed",
                    "entry_time": "2026-01-01T00:00:00Z", "exit_time": "2026-01-02T00:00:00Z",
                    "pnl": 500.0,
                },
            ],
            "quarantined_trades": [],
            "cumulative_realized_pnl": -400.0,  # -900 + 500
            "winning_trades": 1,
            "losing_trades": 1,
        }
        result = self._run_migration(tmp_path, state)

        remaining_closed = [t for t in result["trades"] if t.get("status") == "closed"]
        assert len(remaining_closed) == 1
        assert result["cumulative_realized_pnl"] == pytest.approx(500.0), (
            "quarantining the -$900 CRWD trade must reduce cumulative_realized_pnl "
            "by exactly its pnl, matching sum(remaining closed.pnl)"
        )
        assert sum(t["pnl"] for t in remaining_closed) == pytest.approx(result["cumulative_realized_pnl"])

    def test_quarantining_a_losing_trade_decrements_losing_trades_count(self, tmp_path):
        state = {
            "trades": [
                {
                    "trade_id": "t1", "symbol": "CRWD", "status": "closed",
                    "entry_time": "2026-08-11T13:35:36Z", "exit_time": "2026-07-15T16:00:50Z",
                    "pnl": -900.0,
                },
            ],
            "quarantined_trades": [],
            "cumulative_realized_pnl": -900.0,
            "winning_trades": 0,
            "losing_trades": 1,
        }
        result = self._run_migration(tmp_path, state)

        assert result["losing_trades"] == 0
        assert result["winning_trades"] == 0

    def test_quarantining_a_winning_trade_decrements_winning_trades_count(self, tmp_path):
        state = {
            "trades": [
                {
                    "trade_id": "t1", "symbol": "XYZ", "status": "closed",
                    "entry_time": "2026-08-11T13:35:36Z", "exit_time": "2026-07-15T16:00:50Z",
                    "pnl": 900.0,  # positive pnl, still reversed chronology
                },
            ],
            "quarantined_trades": [],
            "cumulative_realized_pnl": 900.0,
            "winning_trades": 1,
            "losing_trades": 0,
        }
        result = self._run_migration(tmp_path, state)

        assert result["winning_trades"] == 0
        assert result["losing_trades"] == 0

    def test_no_invalid_trades_leaves_aggregates_unchanged(self, tmp_path):
        state = {
            "trades": [
                {
                    "trade_id": "t1", "symbol": "AAA", "status": "closed",
                    "entry_time": "2026-01-01T00:00:00Z", "exit_time": "2026-01-02T00:00:00Z",
                    "pnl": 500.0,
                },
            ],
            "quarantined_trades": [],
            "cumulative_realized_pnl": 500.0,
            "winning_trades": 1,
            "losing_trades": 0,
        }
        result = self._run_migration(tmp_path, state)

        assert result["cumulative_realized_pnl"] == pytest.approx(500.0)
        assert result["winning_trades"] == 1
        assert result["losing_trades"] == 0
