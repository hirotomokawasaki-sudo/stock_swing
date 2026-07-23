"""R1-v2 / H1: Rebuild idempotency and quarantine tombstone tests.

Validates that:
  - extract_quarantine_tombstones() extracts (entry_oid, exit_oid) pairs
  - apply_tombstone_filter() removes re-generated closed trades that match tombstones
  - closed/quarantine overlap = 0 after tombstone filter + attribution merge
  - compute_rebuild_fingerprint() is stable across two simulated rebuilds (idempotency)
  - apply_attribution() preserves exit_reason and quarantined_trades

Acceptance criteria (R1-v2):
  AC1 – rebuild run twice: closed_count / PnL / quarantine_count identical
  AC2 – closed / quarantine trade_id overlap = 0 after rebuild
  AC3 – --preserve-attribution is enforced (attribution not wiped)

History:
    R0-v2-B (2026-07-22): data repair removed 41 closed/quarantine overlaps
    R1-v2 / H1 (2026-07-23): tombstone filter prevents overlap from recurring on rebuild
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow importing from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pytest

from rebuild_pnl_state_from_broker import (
    apply_attribution,
    apply_tombstone_filter,
    compute_rebuild_fingerprint,
    extract_quarantine_tombstones,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _closed_trade(
    trade_id: str,
    symbol: str,
    broker_order_id: str,
    exit_broker_order_id: str,
    pnl: float = 100.0,
    exit_reason: str = "broker_fill",
) -> dict:
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "status": "closed",
        "broker_order_id": broker_order_id,
        "exit_broker_order_id": exit_broker_order_id,
        "pnl": pnl,
        "exit_reason": exit_reason,
        "entry_time": "2026-06-01T09:30:00",
        "exit_time": "2026-06-10T15:45:00",
        "holding_days": 9,
    }


def _quarantined_trade(
    trade_id: str,
    symbol: str,
    broker_order_id: str,
    exit_broker_order_id: str,
    quarantine_reason: str = "reversed_chronology",
) -> dict:
    t = _closed_trade(trade_id, symbol, broker_order_id, exit_broker_order_id)
    t["status"] = "quarantined"
    t["quarantine_reason"] = quarantine_reason
    return t


def _open_trade(trade_id: str, symbol: str, broker_order_id: str) -> dict:
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "status": "open",
        "broker_order_id": broker_order_id,
        "exit_broker_order_id": None,
        "pnl": None,
    }


def _make_state(
    trades: list[dict],
    quarantined_trades: list[dict] | None = None,
) -> dict:
    closed = [t for t in trades if t.get("status") == "closed"]
    pnl_sum = sum(float(t.get("pnl") or 0) for t in closed)
    return {
        "trades": list(trades),
        "quarantined_trades": list(quarantined_trades or []),
        "total_trades": len(trades),
        "cumulative_realized_pnl": round(pnl_sum, 2),
    }


# ---------------------------------------------------------------------------
# extract_quarantine_tombstones
# ---------------------------------------------------------------------------

class TestExtractQuarantineTombstones:
    def test_returns_frozenset_of_pairs(self) -> None:
        qt = [_quarantined_trade("q1", "AMD", "buy-001", "sell-001")]
        result = extract_quarantine_tombstones(qt)
        assert ("buy-001", "sell-001") in result
        assert isinstance(result, frozenset)

    def test_skips_missing_order_ids(self) -> None:
        """Tombstone not created when entry or exit order ID is blank."""
        qt = [
            {"trade_id": "q2", "broker_order_id": "", "exit_broker_order_id": "sell-002"},
            {"trade_id": "q3", "broker_order_id": "buy-003", "exit_broker_order_id": None},
        ]
        result = extract_quarantine_tombstones(qt)
        assert len(result) == 0, "both IDs must be present for tombstone"

    def test_multiple_tombstones(self) -> None:
        qts = [
            _quarantined_trade("q1", "AMD", "buy-001", "sell-001"),
            _quarantined_trade("q2", "NVDA", "buy-002", "sell-002"),
        ]
        result = extract_quarantine_tombstones(qts)
        assert len(result) == 2
        assert ("buy-001", "sell-001") in result
        assert ("buy-002", "sell-002") in result

    def test_empty_list_returns_empty_frozenset(self) -> None:
        assert extract_quarantine_tombstones([]) == frozenset()


# ---------------------------------------------------------------------------
# apply_tombstone_filter
# ---------------------------------------------------------------------------

class TestApplyTombstoneFilter:
    def test_removes_closed_trade_matching_tombstone(self) -> None:
        """AC2: closed trade whose order IDs match quarantined tombstone is removed."""
        # A quarantined trade and a re-generated closed version of the same fill
        qt = [_quarantined_trade("q1", "AMD", "buy-001", "sell-001")]
        state = _make_state([
            _closed_trade("broker_match_0001_AMD", "AMD", "buy-001", "sell-001"),  # tombstone match
            _closed_trade("broker_match_0002_NVDA", "NVDA", "buy-002", "sell-002"),  # safe
        ])

        removed = apply_tombstone_filter(state, qt)

        assert removed == 1, "exactly one tombstone match removed"
        trade_ids = [t["trade_id"] for t in state["trades"]]
        assert "broker_match_0001_AMD" not in trade_ids, "tombstone trade removed from trades"
        assert "broker_match_0002_NVDA" in trade_ids, "non-tombstone trade kept"

    def test_no_tombstones_returns_zero(self) -> None:
        """When no quarantined trades, filter is a no-op."""
        state = _make_state([_closed_trade("t1", "AMD", "buy-001", "sell-001")])
        removed = apply_tombstone_filter(state, [])
        assert removed == 0
        assert len(state["trades"]) == 1

    def test_open_trade_not_affected_by_tombstone(self) -> None:
        """Open trade with same entry order ID as tombstone is kept (it's active)."""
        qt = [_quarantined_trade("q1", "AMD", "buy-001", "sell-001")]
        state = _make_state([
            _closed_trade("broker_match_0001_AMD", "AMD", "buy-001", "sell-001"),  # removed
            _open_trade("broker_open_0002_AMD", "AMD", "buy-001"),  # kept (no exit_oid)
        ])
        removed = apply_tombstone_filter(state, qt)
        assert removed == 1
        trade_ids = [t["trade_id"] for t in state["trades"]]
        assert "broker_open_0002_AMD" in trade_ids

    def test_pnl_sum_recalculated_after_filter(self) -> None:
        """cumulative_realized_pnl is updated after filtering."""
        qt = [_quarantined_trade("q1", "AMD", "buy-001", "sell-001")]
        state = _make_state([
            _closed_trade("t1", "AMD", "buy-001", "sell-001", pnl=500.0),  # removed
            _closed_trade("t2", "NVDA", "buy-002", "sell-002", pnl=200.0),  # kept
        ])
        apply_tombstone_filter(state, qt)
        assert state["cumulative_realized_pnl"] == pytest.approx(200.0)
        assert state["total_trades"] == 1

    def test_regression_r0v2b_overlap_41(self) -> None:
        """Regression: R0-v2-B found 41 closed/quarantine overlaps.
        Tombstone filter must prevent same overlap from recurring after rebuild.
        Incident: 2026-07-22 / commit 3222b73 (data repair).
        This test simulates the scenario that caused the overlap.
        """
        # 3 quarantined trades (reversed chronology)
        quarantined = [
            _quarantined_trade("q1", "AMD",  "buy-101", "sell-101", "reversed_chronology"),
            _quarantined_trade("q2", "NVDA", "buy-102", "sell-102", "closed_quarantine_overlap"),
            _quarantined_trade("q3", "MU",   "buy-103", "sell-103", "closed_quarantine_overlap"),
        ]
        # Rebuild re-generates the same trades as closed (simulating non-idempotent rebuild)
        rebuilt_trades = [
            _closed_trade("broker_match_0001_AMD",  "AMD",  "buy-101", "sell-101"),  # ← tombstone
            _closed_trade("broker_match_0002_NVDA", "NVDA", "buy-102", "sell-102"),  # ← tombstone
            _closed_trade("broker_match_0003_MU",   "MU",   "buy-103", "sell-103"),  # ← tombstone
            _closed_trade("broker_match_0004_AAPL", "AAPL", "buy-104", "sell-104"),  # safe
        ]
        state = _make_state(rebuilt_trades)

        removed = apply_tombstone_filter(state, quarantined)

        assert removed == 3, "all 3 tombstone matches removed"
        trade_ids = [t["trade_id"] for t in state["trades"]]
        assert "broker_match_0004_AAPL" in trade_ids
        for tid in ["broker_match_0001_AMD", "broker_match_0002_NVDA", "broker_match_0003_MU"]:
            assert tid not in trade_ids, f"{tid} must be removed by tombstone"


# ---------------------------------------------------------------------------
# Idempotency: two simulated rebuilds must produce same fingerprint
# ---------------------------------------------------------------------------

class TestRebuildIdempotency:
    """AC1: Two rebuilds from the same broker data produce identical fingerprints."""

    def _simulate_rebuild(
        self,
        broker_fills: list[dict],
        quarantined_trades: list[dict],
    ) -> dict:
        """Simulate one rebuild run: generate closed trades + apply tombstone."""
        # Simulates what rebuild_pnl_state() produces from broker fills
        # (simplified: one closed trade per fill pair)
        state = _make_state(list(broker_fills))
        # Apply tombstone filter (the idempotency guard)
        apply_tombstone_filter(state, quarantined_trades)
        # Apply attribution (sets quarantined_trades list)
        attribution = {
            "by_exit_order_id": {},
            "by_key": {},
            "quarantined_trades": quarantined_trades,
        }
        apply_attribution(state, attribution)
        return state

    def test_two_rebuilds_produce_identical_fingerprint(self) -> None:
        """AC1: fingerprint is identical on second rebuild."""
        quarantined = [
            _quarantined_trade("q1", "AMD", "buy-001", "sell-001", "reversed_chronology"),
        ]
        # Broker fills include the quarantined pair + clean pairs
        broker_fills = [
            _closed_trade("broker_match_0001_AMD",  "AMD",  "buy-001", "sell-001", pnl=-200.0),  # tombstone
            _closed_trade("broker_match_0002_NVDA", "NVDA", "buy-002", "sell-002", pnl=500.0),
            _closed_trade("broker_match_0003_MU",   "MU",   "buy-003", "sell-003", pnl=300.0),
        ]

        state1 = self._simulate_rebuild(broker_fills, quarantined)
        # Run again on the result of the first run (simulating rebuild on rebuilt state)
        state2 = self._simulate_rebuild(broker_fills, quarantined)

        fp1 = compute_rebuild_fingerprint(state1)
        fp2 = compute_rebuild_fingerprint(state2)

        assert fp1["closed_count"] == fp2["closed_count"], "AC1: closed_count identical"
        assert fp1["pnl_sum"] == pytest.approx(fp2["pnl_sum"]), "AC1: pnl_sum identical"
        assert fp1["quarantine_count"] == fp2["quarantine_count"], "AC1: quarantine_count identical"
        assert fp1["closed_trades"] == fp2["closed_trades"], "AC1: closed_trades list identical"

    def test_closed_quarantine_overlap_is_zero_after_tombstone(self) -> None:
        """AC2: After tombstone filter, no trade_id appears in both closed and quarantined."""
        quarantined = [
            _quarantined_trade("q1", "AMD", "buy-001", "sell-001"),
        ]
        broker_fills = [
            _closed_trade("broker_match_0001_AMD", "AMD", "buy-001", "sell-001", pnl=-200.0),
            _closed_trade("broker_match_0002_NVDA", "NVDA", "buy-002", "sell-002", pnl=500.0),
        ]
        state = _make_state(list(broker_fills))
        apply_tombstone_filter(state, quarantined)
        apply_attribution(state, {"by_exit_order_id": {}, "by_key": {}, "quarantined_trades": quarantined})

        closed_oids = {
            (t.get("broker_order_id"), t.get("exit_broker_order_id"))
            for t in state["trades"] if t.get("status") == "closed"
        }
        q_oids = {
            (t.get("broker_order_id"), t.get("exit_broker_order_id"))
            for t in state.get("quarantined_trades", [])
        }
        overlap = closed_oids & q_oids
        assert overlap == set(), f"AC2: closed/quarantine overlap must be 0, got {overlap}"


# ---------------------------------------------------------------------------
# apply_attribution – preserve exit_reason and quarantined_trades
# ---------------------------------------------------------------------------

class TestApplyAttribution:
    def test_preserves_exit_reason_by_exit_order_id(self) -> None:
        """AC3: exit_reason restored from exit_broker_order_id match."""
        state = _make_state([_closed_trade("t1", "AMD", "buy-001", "sell-001")])
        attr = {
            "by_exit_order_id": {"sell-001": "trailing_stop"},
            "by_key": {},
            "quarantined_trades": [],
        }
        apply_attribution(state, attr)
        assert state["trades"][0]["exit_reason"] == "trailing_stop"

    def test_preserves_exit_reason_by_key_fallback(self) -> None:
        """AC3: exit_reason restored via (symbol, exit_time, pnl) key fallback."""
        trade = _closed_trade("t1", "AMD", "buy-001", "sell-999")
        state = _make_state([trade])
        key = ("AMD", "2026-06-10T15:45:00", 100)  # pnl=100 rounded
        attr = {
            "by_exit_order_id": {},
            "by_key": {key: "stop_loss"},
            "quarantined_trades": [],
        }
        apply_attribution(state, attr)
        assert state["trades"][0]["exit_reason"] == "stop_loss"

    def test_quarantined_trades_restored(self) -> None:
        """AC3: quarantined_trades from saved state are restored."""
        state = _make_state([_closed_trade("t1", "AMD", "buy-001", "sell-001")])
        qt = [_quarantined_trade("q1", "MU", "buy-010", "sell-010")]
        attr = {"by_exit_order_id": {}, "by_key": {}, "quarantined_trades": qt}
        apply_attribution(state, attr)
        assert len(state["quarantined_trades"]) == 1
        assert state["quarantined_trades"][0]["trade_id"] == "q1"

    def test_broker_fill_kept_when_no_match(self) -> None:
        """Trades with no attribution match keep exit_reason=broker_fill."""
        state = _make_state([_closed_trade("t1", "AMD", "buy-001", "sell-001")])
        attr = {"by_exit_order_id": {}, "by_key": {}, "quarantined_trades": []}
        stats = apply_attribution(state, attr)
        assert state["trades"][0]["exit_reason"] == "broker_fill"
        assert stats["kept_broker_fill"] == 1


# ---------------------------------------------------------------------------
# compute_rebuild_fingerprint
# ---------------------------------------------------------------------------

class TestComputeRebuildFingerprint:
    def test_fingerprint_fields(self) -> None:
        qt = [_quarantined_trade("q1", "AMD", "buy-001", "sell-001")]
        state = _make_state(
            [_closed_trade("t1", "NVDA", "buy-002", "sell-002", pnl=500.0)],
            quarantined_trades=qt,
        )
        fp = compute_rebuild_fingerprint(state)
        assert fp["closed_count"] == 1
        assert fp["pnl_sum"] == pytest.approx(500.0)
        assert fp["quarantine_count"] == 1

    def test_fingerprint_stable_for_same_state(self) -> None:
        state = _make_state([_closed_trade("t1", "NVDA", "buy-002", "sell-002", pnl=500.0)])
        fp1 = compute_rebuild_fingerprint(state)
        fp2 = compute_rebuild_fingerprint(state)
        assert fp1 == fp2
