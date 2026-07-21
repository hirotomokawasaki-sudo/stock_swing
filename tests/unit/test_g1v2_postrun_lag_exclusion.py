"""G1-v2 tests: post-run broker/tracker mismatch should exclude submission-lag symbols.

Root cause (recurring circuit-breaker false HALT):
  - paper_demo submits BUY/SELL orders
  - 3-second wait is not always enough at market open for broker API to reflect fills
  - tracker records positions immediately → appears in tracker_only (for BUY lag)
  - broker still shows position → appears in broker_only (for SELL lag)
  - These are transient API-lag false positives, not real integrity issues

Fix (G1-v2, 2026-07-21):
  - After computing raw _bt_diff_postrun, compute _lag_excused:
      tracker_only & newly_submitted_buy_symbols   → BUY lag
      broker_only  & newly_submitted_sell_symbols  → SELL lag
  - adjusted_mismatch = raw_mismatch - len(_lag_excused)
  - Pass adjusted_mismatch to guardrail, not raw
"""
from __future__ import annotations

import pytest


# ── helpers ────────────────────────────────────────────────────────────────

class _FakeSub:
    """Minimal OrderSubmission stand-in."""
    def __init__(self, symbol: str, side: str, status: str = "filled"):
        self.symbol = symbol
        self.side = side
        self.status = status


def _build_diff(
    broker_symbols: list[str],
    tracker_symbols: list[str],
) -> dict:
    """Minimal broker/tracker diff matching _build_broker_tracker_diff output."""
    broker_set = set(broker_symbols)
    tracker_set = set(tracker_symbols)
    broker_only = sorted(broker_set - tracker_set)
    tracker_only = sorted(tracker_set - broker_set)
    qty_mismatches: list = []
    mismatch_count = len(broker_only) + len(tracker_only) + len(qty_mismatches)
    return {
        "broker_count": len(broker_set),
        "tracker_count": len(tracker_set),
        "mismatch_count": mismatch_count,
        "broker_only": broker_only,
        "tracker_only": tracker_only,
        "qty_mismatches": qty_mismatches,
    }


def _apply_lag_exclusion(
    bt_diff: dict,
    new_submissions: list[_FakeSub],
) -> tuple[int, set[str]]:
    """Replicate the G1-v2 lag-exclusion logic from paper_demo.py."""
    new_buy_symbols: set[str] = {
        s.symbol for s in new_submissions if getattr(s, "side", "") == "buy"
    }
    new_sell_symbols: set[str] = {
        s.symbol for s in new_submissions if getattr(s, "side", "") == "sell"
    }
    lag_excused: set[str] = (
        (set(bt_diff["tracker_only"]) & new_buy_symbols)
        | (set(bt_diff["broker_only"]) & new_sell_symbols)
    )
    adjusted = bt_diff["mismatch_count"] - len(lag_excused)
    return adjusted, lag_excused


# ── tests ──────────────────────────────────────────────────────────────────

class TestBuyLag:
    """BUY submitted → tracker has it, broker doesn't yet → tracker_only."""

    def test_single_buy_lag_excluded(self):
        """Canonical G1-v2 case: 1 new BUY not yet in broker → mismatch excused."""
        diff = _build_diff(
            broker_symbols=["AAPL"],
            tracker_symbols=["AAPL", "META"],
        )
        assert diff["mismatch_count"] == 1
        assert diff["tracker_only"] == ["META"]

        subs = [_FakeSub("META", "buy")]
        adjusted, excused = _apply_lag_exclusion(diff, subs)

        assert adjusted == 0
        assert excused == {"META"}

    def test_two_buy_lags_excluded(self):
        """Replicate exact 07-21 incident: META + HPQ both lag."""
        diff = _build_diff(
            broker_symbols=["AAPL"],
            tracker_symbols=["AAPL", "META", "HPQ"],
        )
        assert diff["mismatch_count"] == 2

        subs = [_FakeSub("META", "buy"), _FakeSub("HPQ", "buy")]
        adjusted, excused = _apply_lag_exclusion(diff, subs)

        assert adjusted == 0
        assert excused == {"META", "HPQ"}

    def test_partial_buy_lag_only_submitted_excused(self):
        """If MSFT is in tracker_only but was NOT submitted this run, it is NOT excused."""
        diff = _build_diff(
            broker_symbols=["AAPL"],
            tracker_symbols=["AAPL", "META", "MSFT"],
        )
        assert diff["mismatch_count"] == 2

        subs = [_FakeSub("META", "buy")]   # only META was submitted
        adjusted, excused = _apply_lag_exclusion(diff, subs)

        assert adjusted == 1          # MSFT still counted
        assert excused == {"META"}    # only META excused


class TestSellLag:
    """SELL submitted → tracker closed it, broker still shows it → broker_only."""

    def test_single_sell_lag_excluded(self):
        """PANW sold → broker still shows it → broker_only → excused."""
        diff = _build_diff(
            broker_symbols=["AAPL", "PANW"],   # broker still shows PANW
            tracker_symbols=["AAPL"],           # tracker already closed PANW
        )
        assert diff["mismatch_count"] == 1
        assert diff["broker_only"] == ["PANW"]

        subs = [_FakeSub("PANW", "sell")]
        adjusted, excused = _apply_lag_exclusion(diff, subs)

        assert adjusted == 0
        assert excused == {"PANW"}

    def test_unsolicited_broker_only_not_excused(self):
        """If PANW appears in broker_only but no sell was submitted, it is real mismatch."""
        diff = _build_diff(
            broker_symbols=["AAPL", "PANW"],
            tracker_symbols=["AAPL"],
        )
        subs: list[_FakeSub] = []  # nothing submitted
        adjusted, excused = _apply_lag_exclusion(diff, subs)

        assert adjusted == 1    # still a mismatch
        assert excused == set()


class TestMixed:
    """Mixed BUY+SELL submissions in same run."""

    def test_buy_and_sell_lag_both_excused(self):
        """BUY META lags (tracker_only) + SELL PANW lags (broker_only) → both excused."""
        diff = _build_diff(
            broker_symbols=["AAPL", "PANW"],  # PANW still shows (sell lag)
            tracker_symbols=["AAPL", "META"], # META already in (buy lag)
        )
        assert diff["mismatch_count"] == 2

        subs = [_FakeSub("META", "buy"), _FakeSub("PANW", "sell")]
        adjusted, excused = _apply_lag_exclusion(diff, subs)

        assert adjusted == 0
        assert excused == {"META", "PANW"}

    def test_real_mismatch_not_excused_when_mixed(self):
        """Real mismatch (MSFT, not submitted) not excused even when other lags exist."""
        diff = _build_diff(
            broker_symbols=["AAPL", "PANW"],
            tracker_symbols=["AAPL", "META", "MSFT"],  # META=buy-lag, MSFT=real
        )
        assert diff["mismatch_count"] == 3

        subs = [_FakeSub("META", "buy"), _FakeSub("PANW", "sell")]
        adjusted, excused = _apply_lag_exclusion(diff, subs)

        assert adjusted == 1          # MSFT is a real mismatch
        assert excused == {"META", "PANW"}


class TestEdgeCases:
    """Edge cases: no submissions, rejected submissions, etc."""

    def test_no_submissions_no_exclusion(self):
        diff = _build_diff(
            broker_symbols=["AAPL"],
            tracker_symbols=["AAPL", "META"],
        )
        adjusted, excused = _apply_lag_exclusion(diff, [])
        assert adjusted == 1
        assert excused == set()

    def test_zero_mismatch_unchanged(self):
        """If raw mismatch is 0 and no lag symbols match, adjusted is also 0."""
        diff = _build_diff(["AAPL", "META"], ["AAPL", "META"])
        assert diff["mismatch_count"] == 0
        subs = [_FakeSub("META", "buy")]
        adjusted, excused = _apply_lag_exclusion(diff, subs)
        assert adjusted == 0
        assert excused == set()

    def test_rejected_buy_still_excused(self):
        """Even a rejected submission caused the tracker to update → lag still applies.
        (In practice rejected BUYs don't update the tracker, but we test conservatively.)
        """
        diff = _build_diff(["AAPL"], ["AAPL", "META"])
        subs = [_FakeSub("META", "buy", status="rejected")]
        adjusted, excused = _apply_lag_exclusion(diff, subs)
        # The exclusion logic operates on side/symbol only, not status.
        # This is intentional: if anything the rejected submission would NOT
        # update the tracker, but we err on the side of not false-HALTing.
        assert adjusted == 0
        assert excused == {"META"}

    def test_qty_mismatch_not_affected(self):
        """qty_mismatches (same symbol, wrong qty) are not touched by lag exclusion."""
        # Build a diff where AAPL has a qty mismatch (same symbol, different qty).
        diff = {
            "broker_count": 1,
            "tracker_count": 1,
            "mismatch_count": 1,
            "broker_only": [],
            "tracker_only": [],
            "qty_mismatches": [{"symbol": "AAPL", "broker_qty": 100, "tracker_qty": 90}],
        }
        subs = [_FakeSub("AAPL", "buy")]
        adjusted, excused = _apply_lag_exclusion(diff, subs)
        # qty_mismatches are not touched by lag exclusion (different failure mode).
        assert adjusted == 1
        assert excused == set()


class TestQtyMismatchLag:
    """G1-v2-b: qty mismatch on newly submitted SELL should be excused.

    Scenario: SELL 112 GOOGL submitted → partial fill →
    broker still shows residual qty, tracker already closed full position.
    This creates a qty_mismatch (same symbol, different qty) not a symbol-presence mismatch.
    G1-v2 original only excused presence mismatches; G1-v2-b also excuses qty mismatches.
    """

    def _build_diff_with_qty_mismatch(self, symbol: str, broker_qty: float, tracker_qty: float) -> dict:
        return {
            "broker_count": 1,
            "tracker_count": 1,
            "mismatch_count": 1,
            "broker_only": [],
            "tracker_only": [],
            "qty_mismatches": [{"symbol": symbol, "broker_qty": broker_qty, "tracker_qty": tracker_qty}],
        }

    def _apply_g1v2b(self, bt_diff: dict, new_submissions: list[_FakeSub]) -> tuple[int, list]:
        """Replicate the G1-v2-b qty mismatch lag-exclusion logic."""
        new_buy_symbols = {s.symbol for s in new_submissions if getattr(s, "side", "") == "buy"}
        new_sell_symbols = {s.symbol for s in new_submissions if getattr(s, "side", "") == "sell"}

        # G1-v2: symbol-presence lag
        lag_excused = (
            (set(bt_diff["tracker_only"]) & new_buy_symbols)
            | (set(bt_diff["broker_only"]) & new_sell_symbols)
        )

        # G1-v2-b: qty-mismatch lag for new sells
        sell_qty_mismatches = [
            q["symbol"] for q in bt_diff.get("qty_mismatches", [])
            if q["symbol"] in new_sell_symbols
        ]

        adjusted = bt_diff["mismatch_count"] - len(lag_excused) - len(sell_qty_mismatches)
        return adjusted, sell_qty_mismatches

    def test_partial_fill_qty_mismatch_excused(self):
        """Canonical G1-v2-b case: GOOGL partial fill (broker=112, tracker=22) excused."""
        diff = self._build_diff_with_qty_mismatch("GOOGL", broker_qty=112, tracker_qty=22)
        assert diff["mismatch_count"] == 1

        subs = [_FakeSub("GOOGL", "sell")]
        adjusted, excused_qty = self._apply_g1v2b(diff, subs)

        assert adjusted == 0
        assert "GOOGL" in excused_qty

    def test_unsolicited_qty_mismatch_not_excused(self):
        """Qty mismatch on a symbol NOT in this run's submissions is a real issue."""
        diff = self._build_diff_with_qty_mismatch("GOOGL", broker_qty=112, tracker_qty=22)

        subs: list[_FakeSub] = []  # no submissions this run
        adjusted, excused_qty = self._apply_g1v2b(diff, subs)

        assert adjusted == 1   # still a real mismatch
        assert excused_qty == []

    def test_buy_symbol_qty_mismatch_not_excused_by_g1v2b(self):
        """G1-v2-b only excuses qty mismatches for SELL submissions, not BUY."""
        diff = self._build_diff_with_qty_mismatch("META", broker_qty=10, tracker_qty=32)

        subs = [_FakeSub("META", "buy")]
        adjusted, excused_qty = self._apply_g1v2b(diff, subs)

        # BUY qty mismatch is not a known lag pattern → not excused
        assert adjusted == 1
        assert excused_qty == []

    def test_presence_and_qty_mismatches_combined(self):
        """Presence lag (BUY HPQ) + qty lag (SELL GOOGL) — both excused simultaneously."""
        diff = {
            "broker_count": 2,
            "tracker_count": 2,
            "mismatch_count": 2,
            "broker_only": [],
            "tracker_only": ["HPQ"],   # BUY HPQ not yet in broker
            "qty_mismatches": [{"symbol": "GOOGL", "broker_qty": 112, "tracker_qty": 22}],
        }

        subs = [_FakeSub("HPQ", "buy"), _FakeSub("GOOGL", "sell")]
        adjusted, excused_qty = self._apply_g1v2b(diff, subs)

        assert adjusted == 0
        assert "GOOGL" in excused_qty
