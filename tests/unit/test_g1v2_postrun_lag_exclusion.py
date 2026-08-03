"""G1-v2 / G1-v2-b tests: post-run broker/tracker mismatch lag exclusion.

IMPORTANT: These tests import and call the *production module*
  stock_swing.guardrails.postrun_mismatch.apply_lag_exclusion()
which is also imported by paper_demo.py.

This means:
  - Any bug in apply_lag_exclusion() is caught by these tests.
  - Any regression that changes apply_lag_exclusion() behaviour breaks tests.
  - Tests cannot pass while paper_demo.py uses a different / broken implementation.

Root cause (recurring circuit-breaker false HALT at 09:35 ET market open):
  G1-v2   (2026-07-21): BUY lag — tracker records immediately, broker API lags
  G1-v2-b (2026-07-21): Qty-mismatch lag — partial SELL fill creates transient discrepancy
"""
from __future__ import annotations

import pytest
from stock_swing.guardrails.postrun_mismatch import apply_lag_exclusion, LagExclusionResult


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
    qty_mismatches: list[dict] | None = None,
) -> dict:
    """Minimal broker/tracker diff matching _build_broker_tracker_diff output."""
    broker_set = set(broker_symbols)
    tracker_set = set(tracker_symbols)
    broker_only = sorted(broker_set - tracker_set)
    tracker_only = sorted(tracker_set - broker_set)
    qty_mm = qty_mismatches or []
    mismatch_count = len(broker_only) + len(tracker_only) + len(qty_mm)
    return {
        "broker_count": len(broker_set),
        "tracker_count": len(tracker_set),
        "mismatch_count": mismatch_count,
        "broker_only": broker_only,
        "tracker_only": tracker_only,
        "qty_mismatches": qty_mm,
    }


# ── G1-v2: symbol-presence lag ─────────────────────────────────────────────

class TestBuyLag:
    """BUY submitted → tracker has it, broker doesn't yet → tracker_only."""

    def test_single_buy_lag_excluded(self):
        diff = _build_diff(["AAPL"], ["AAPL", "META"])
        assert diff["mismatch_count"] == 1

        result = apply_lag_exclusion(diff, [_FakeSub("META", "buy")])

        assert result.adjusted_mismatch_count == 0
        assert "META" in result.excused_presence

    def test_two_buy_lags_excluded(self):
        """Replicate exact 07-21 incident: META + HPQ both lag."""
        diff = _build_diff(["AAPL"], ["AAPL", "META", "HPQ"])
        assert diff["mismatch_count"] == 2

        result = apply_lag_exclusion(diff, [_FakeSub("META", "buy"), _FakeSub("HPQ", "buy")])

        assert result.adjusted_mismatch_count == 0
        assert {"META", "HPQ"} <= result.excused_presence

    def test_partial_buy_lag_only_submitted_excused(self):
        """MSFT is in tracker_only but was NOT submitted → not excused."""
        diff = _build_diff(["AAPL"], ["AAPL", "META", "MSFT"])
        assert diff["mismatch_count"] == 2

        result = apply_lag_exclusion(diff, [_FakeSub("META", "buy")])

        assert result.adjusted_mismatch_count == 1      # MSFT still counted
        assert "META" in result.excused_presence
        assert "MSFT" not in result.excused_presence


class TestSellLag:
    """SELL submitted → tracker closed it, broker still shows it → broker_only."""

    def test_single_sell_lag_excluded(self):
        """PANW sold → broker still shows it → broker_only → excused."""
        diff = _build_diff(["AAPL", "PANW"], ["AAPL"])
        assert diff["mismatch_count"] == 1

        result = apply_lag_exclusion(diff, [_FakeSub("PANW", "sell")])

        assert result.adjusted_mismatch_count == 0
        assert "PANW" in result.excused_presence

    def test_unsolicited_broker_only_not_excused(self):
        """PANW appears in broker_only but no sell was submitted → real mismatch."""
        diff = _build_diff(["AAPL", "PANW"], ["AAPL"])

        result = apply_lag_exclusion(diff, [])

        assert result.adjusted_mismatch_count == 1
        assert not result.excused_presence


class TestMixed:
    def test_buy_and_sell_lag_both_excused(self):
        """BUY META lags + SELL PANW lags → both excused."""
        diff = _build_diff(["AAPL", "PANW"], ["AAPL", "META"])
        assert diff["mismatch_count"] == 2

        result = apply_lag_exclusion(diff, [_FakeSub("META", "buy"), _FakeSub("PANW", "sell")])

        assert result.adjusted_mismatch_count == 0
        assert {"META", "PANW"} <= result.excused_presence

    def test_real_mismatch_not_excused_when_mixed(self):
        """MSFT (not submitted) still counted even when other lags are excused."""
        diff = _build_diff(["AAPL", "PANW"], ["AAPL", "META", "MSFT"])
        assert diff["mismatch_count"] == 3

        result = apply_lag_exclusion(diff, [_FakeSub("META", "buy"), _FakeSub("PANW", "sell")])

        assert result.adjusted_mismatch_count == 1       # MSFT
        assert {"META", "PANW"} <= result.excused_presence


class TestEdgeCases:
    def test_no_submissions_no_exclusion(self):
        diff = _build_diff(["AAPL"], ["AAPL", "META"])
        result = apply_lag_exclusion(diff, [])
        assert result.adjusted_mismatch_count == 1
        assert not result.excused_presence

    def test_zero_mismatch_unchanged(self):
        diff = _build_diff(["AAPL", "META"], ["AAPL", "META"])
        assert diff["mismatch_count"] == 0
        result = apply_lag_exclusion(diff, [_FakeSub("META", "buy")])
        assert result.adjusted_mismatch_count == 0

    def test_adjusted_never_negative(self):
        """Edge: more excused symbols than raw count → clamped to 0, not negative."""
        diff = _build_diff(["AAPL"], ["AAPL", "META"])  # mismatch=1
        # Two submissions for the same symbol (shouldn't happen, but handle gracefully)
        result = apply_lag_exclusion(diff, [_FakeSub("META", "buy"), _FakeSub("META", "buy")])
        assert result.adjusted_mismatch_count >= 0

    def test_result_type_is_lag_exclusion_result(self):
        """Returns the typed dataclass, not a raw tuple."""
        diff = _build_diff(["AAPL"], ["AAPL", "META"])
        result = apply_lag_exclusion(diff, [_FakeSub("META", "buy")])
        assert isinstance(result, LagExclusionResult)
        assert hasattr(result, "adjusted_mismatch_count")
        assert hasattr(result, "raw_mismatch_count")
        assert hasattr(result, "excused_presence")
        assert hasattr(result, "excused_qty")


# ── G1-v2-b: qty-mismatch lag ─────────────────────────────────────────────

class TestQtyMismatchLag:
    """G1-v2-b: qty mismatch on newly submitted SELL should be excused.

    Canonical case (2026-07-22): SELL 112 GOOGL → partial fill →
    broker shows 112, tracker shows 22 → qty_mismatch → would have halted.
    """

    def _diff_with_qty_mm(self, symbol: str, broker_qty: float, tracker_qty: float) -> dict:
        return _build_diff(
            [symbol, "AAPL"], [symbol, "AAPL"],
            qty_mismatches=[{"symbol": symbol, "broker_qty": broker_qty, "tracker_qty": tracker_qty}],
        )

    def test_partial_fill_qty_mismatch_excused(self):
        """Canonical G1-v2-b: GOOGL partial fill (broker=112, tracker=22) excused."""
        diff = self._diff_with_qty_mm("GOOGL", broker_qty=112, tracker_qty=22)
        assert diff["mismatch_count"] == 1

        result = apply_lag_exclusion(diff, [_FakeSub("GOOGL", "sell")])

        assert result.adjusted_mismatch_count == 0
        assert "GOOGL" in result.excused_qty

    def test_unsolicited_qty_mismatch_not_excused(self):
        """Qty mismatch on symbol NOT in this run's submissions → real issue."""
        diff = self._diff_with_qty_mm("GOOGL", broker_qty=112, tracker_qty=22)

        result = apply_lag_exclusion(diff, [])

        assert result.adjusted_mismatch_count == 1
        assert result.excused_qty == []

    def test_buy_symbol_qty_mismatch_broker_ahead_not_excused(self):
        """G1-v2-b (SELL-only) does not excuse BUY qty mismatches. Separately,
        G1-v2-d (added 2026-08-04, see TestG1V2dBuyAddToExistingPositionQtyLag)
        excuses BUY qty mismatches ONLY when tracker is ahead of broker
        (tracker_qty > broker_qty, the known submission-lag direction). Here
        broker is ahead (10 < 32 reversed: broker=32 > tracker=10), which is
        NOT the lag direction G1-v2-d covers, so it must remain a real
        mismatch."""
        diff = self._diff_with_qty_mm("META", broker_qty=32, tracker_qty=10)

        result = apply_lag_exclusion(diff, [_FakeSub("META", "buy")])

        assert result.adjusted_mismatch_count == 1      # not excused
        assert result.excused_qty == []

    def test_presence_and_qty_mismatches_combined(self):
        """BUY HPQ presence lag + SELL GOOGL qty lag → both excused."""
        diff = {
            "broker_count": 3,
            "tracker_count": 3,
            "mismatch_count": 2,
            "broker_only": [],
            "tracker_only": ["HPQ"],
            "qty_mismatches": [{"symbol": "GOOGL", "broker_qty": 112, "tracker_qty": 22}],
        }

        result = apply_lag_exclusion(diff, [_FakeSub("HPQ", "buy"), _FakeSub("GOOGL", "sell")])

        assert result.adjusted_mismatch_count == 0
        assert "HPQ" in result.excused_presence
        assert "GOOGL" in result.excused_qty


# ── Acceptance: paper_demo.py uses the canonical module ────────────────────

class TestG1V2cFastFillSellPhantom:
    """G1-v2-c: tracker_only ∩ new_sell_symbols (fast-fill SELL phantom lag).

    Regression: 2026-07-24 circuit-breaker false HALT (SKYY phantom).
    Root cause: SKYY SELL submitted at 19:55 ET on 07-22, broker filled
    immediately and removed position.  record_exit() not yet called in tracker
    (broker returned 'submitted' status, not 'filled', within 1.6 seconds).
    SKYY became tracker_only — not lag-excused by G1-v2 — mismatch_count=1 → HALT.
    Commit: see docs/daily_logs/2026-07-25.md
    """

    def test_regression_skyy_phantom_07_24(self):
        """
        Regression: 2026-07-24 22:35 JST HALT (SKYY fast-fill phantom).
        Replicates exact conditions: SKYY in tracker (open), not in broker
        (filled and removed), sell submitted this run.
        """
        # SKYY in tracker (open), not in broker (already filled/removed)
        diff = _build_diff(
            broker_symbols=["META", "ANET", "HPQ"],  # no SKYY
            tracker_symbols=["META", "ANET", "HPQ", "SKYY"],  # SKYY still open
        )
        assert diff["mismatch_count"] == 1  # SKYY is tracker_only

        # SKYY sell was submitted this run
        result = apply_lag_exclusion(diff, [_FakeSub("SKYY", "sell")])

        assert result.adjusted_mismatch_count == 0, (
            "SKYY tracker_only + just-sold should be lag-excused (G1-v2-c)"
        )
        assert "SKYY" in result.excused_presence

    def test_fast_fill_sell_tracker_only_excused(self):
        """tracker_only ∩ new_sell_symbols is excused (G1-v2-c)."""
        diff = _build_diff(
            broker_symbols=["AAPL"],
            tracker_symbols=["AAPL", "TSLA"],  # TSLA tracker_only
        )
        result = apply_lag_exclusion(diff, [_FakeSub("TSLA", "sell")])
        assert result.adjusted_mismatch_count == 0
        assert "TSLA" in result.excused_presence

    def test_tracker_only_without_sell_not_excused(self):
        """tracker_only symbol NOT submitted as sell this run → real phantom, not excused."""
        diff = _build_diff(
            broker_symbols=["AAPL"],
            tracker_symbols=["AAPL", "TSLA"],  # TSLA tracker_only
        )
        result = apply_lag_exclusion(diff, [])  # no submissions this run
        assert result.adjusted_mismatch_count == 1, (
            "tracker_only with no sell submission must remain as real mismatch"
        )
        assert "TSLA" not in result.excused_presence

    def test_fast_fill_and_buy_lag_simultaneously(self):
        """Both G1-v2 (BUY lag) and G1-v2-c (fast-fill SELL) excused in same run."""
        diff = _build_diff(
            broker_symbols=["AAPL"],  # broker has only AAPL
            tracker_symbols=["AAPL", "META", "SKYY"],  # META=new BUY, SKYY=fast-fill SELL
        )
        result = apply_lag_exclusion(
            diff,
            [_FakeSub("META", "buy"), _FakeSub("SKYY", "sell")],
        )
        assert result.adjusted_mismatch_count == 0
        assert {"META", "SKYY"} <= result.excused_presence

    def test_tracker_only_sell_submitted_different_symbol_not_excused(self):
        """SELL submitted for TSLA; phantom is SKYY → SKYY not excused."""
        diff = _build_diff(
            broker_symbols=["AAPL"],
            tracker_symbols=["AAPL", "SKYY"],  # SKYY tracker_only phantom
        )
        result = apply_lag_exclusion(diff, [_FakeSub("TSLA", "sell")])
        assert result.adjusted_mismatch_count == 1, (
            "SKYY phantom must NOT be excused by TSLA sell submission"
        )
        assert "SKYY" not in result.excused_presence

    def test_broker_only_sell_and_tracker_only_sell_both_excused(self):
        """Both lag directions for the same SELL symbol are handled."""
        # broker_only SELL: broker still shows position (slow fill confirmation)
        # tracker_only SELL: broker removed position (fast fill)
        # Both should be excused for their respective symbols.
        diff = _build_diff(
            broker_symbols=["AAPL", "GOOG"],  # GOOG = broker_only (slow-fill lag)
            tracker_symbols=["AAPL", "SKYY"],  # SKYY = tracker_only (fast-fill lag)
        )
        # GOOG sell submitted (slow fill) + SKYY sell submitted (fast fill)
        result = apply_lag_exclusion(
            diff,
            [_FakeSub("GOOG", "sell"), _FakeSub("SKYY", "sell")],
        )
        assert result.adjusted_mismatch_count == 0
        assert {"GOOG", "SKYY"} <= result.excused_presence


class TestG1V2dBuyAddToExistingPositionQtyLag:
    """G1-v2-d: qty-mismatch lag on BUY that adds to an EXISTING open position.

    Regression: 2026-08-04 circuit-breaker false HALT (SNOW).
    Root cause: SNOW already had an open 116-share tracker position. A second
    BUY for 116 more shares was submitted; the tracker summed the new lot's
    qty to 232 immediately on submission, but broker qty only reflected the
    fill (116) several seconds later (fill confirmation + API propagation lag).
    postrun check ran during that window: broker_qty=116, tracker_qty=232 →
    qty_mismatch → mismatch_count=1 → HALT, even though the position was
    correct moments later. See docs/daily_logs/2026-08-04.md.

    This differs from G1-v2-b (SELL qty lag): here the SUBMISSION side is BUY,
    and the direction of the lag is opposite (tracker ahead of broker, not
    broker ahead of tracker as in a SELL partial fill).
    """

    def _diff_with_qty_mm(self, symbol: str, broker_qty: float, tracker_qty: float) -> dict:
        return _build_diff(
            [symbol, "AAPL"], [symbol, "AAPL"],
            qty_mismatches=[{"symbol": symbol, "broker_qty": broker_qty, "tracker_qty": tracker_qty}],
        )

    def test_regression_snow_add_to_existing_position_08_04(self):
        """
        Regression: 2026-08-03 19:55 JST HALT (SNOW add-to-existing BUY).
        Replicates exact conditions: existing 116-share position + new
        116-share BUY → tracker=232, broker still shows 116 momentarily.
        """
        diff = self._diff_with_qty_mm("SNOW", broker_qty=116, tracker_qty=232)
        assert diff["mismatch_count"] == 1

        result = apply_lag_exclusion(diff, [_FakeSub("SNOW", "buy")])

        assert result.adjusted_mismatch_count == 0, (
            "SNOW qty lag from adding to an existing position via BUY must be "
            "excused (G1-v2-d)"
        )
        assert "SNOW" in result.excused_qty

    def test_buy_qty_mismatch_excused_only_when_tracker_ahead(self):
        """Tracker ahead of broker (tracker_qty > broker_qty) on a BUY → excused."""
        diff = self._diff_with_qty_mm("MSFT", broker_qty=50, tracker_qty=100)
        result = apply_lag_exclusion(diff, [_FakeSub("MSFT", "buy")])
        assert result.adjusted_mismatch_count == 0
        assert "MSFT" in result.excused_qty

    def test_buy_qty_mismatch_not_excused_when_broker_ahead(self):
        """Broker ahead of tracker (broker_qty > tracker_qty) on a BUY is a
        DIFFERENT, real issue (e.g. tracker under-counted a fill) and must
        NOT be excused by G1-v2-d — only the tracker-ahead direction is a
        known submission-lag artifact."""
        diff = self._diff_with_qty_mm("MSFT", broker_qty=200, tracker_qty=100)
        result = apply_lag_exclusion(diff, [_FakeSub("MSFT", "buy")])
        assert result.adjusted_mismatch_count == 1, (
            "broker_qty > tracker_qty on a BUY symbol must remain a real "
            "mismatch, not be excused"
        )
        assert "MSFT" not in result.excused_qty

    def test_buy_qty_mismatch_unsolicited_not_excused(self):
        """Qty mismatch on a symbol NOT submitted this run → real issue."""
        diff = self._diff_with_qty_mm("SNOW", broker_qty=116, tracker_qty=232)
        result = apply_lag_exclusion(diff, [])
        assert result.adjusted_mismatch_count == 1
        assert result.excused_qty == []

    def test_sell_symbol_buy_direction_qty_mismatch_not_excused_by_g1v2d(self):
        """A qty mismatch on a symbol submitted as SELL (not BUY) must be
        evaluated by G1-v2-b's rule, not accidentally pass G1-v2-d's tracker-
        ahead check when the submission list also happens to contain a BUY
        for a different symbol."""
        diff = self._diff_with_qty_mm("GOOGL", broker_qty=232, tracker_qty=116)
        # GOOGL submitted as BUY, but broker is AHEAD of tracker (232 > 116)
        # — not the expected BUY-lag direction, so must not be excused.
        result = apply_lag_exclusion(diff, [_FakeSub("GOOGL", "buy")])
        assert result.adjusted_mismatch_count == 1
        assert "GOOGL" not in result.excused_qty

    def test_buy_add_to_existing_and_sell_partial_fill_combined(self):
        """G1-v2-d (BUY add-to-existing) and G1-v2-b (SELL partial fill) both
        excused in the same run, for different symbols."""
        diff = {
            "broker_count": 2,
            "tracker_count": 2,
            "mismatch_count": 2,
            "broker_only": [],
            "tracker_only": [],
            "qty_mismatches": [
                {"symbol": "SNOW", "broker_qty": 116, "tracker_qty": 232},
                {"symbol": "GOOGL", "broker_qty": 112, "tracker_qty": 22},
            ],
        }
        result = apply_lag_exclusion(
            diff,
            [_FakeSub("SNOW", "buy"), _FakeSub("GOOGL", "sell")],
        )
        assert result.adjusted_mismatch_count == 0
        assert {"SNOW", "GOOGL"} <= set(result.excused_qty)


class TestPaperDemoUsesCanonicalModule:
    """Verify paper_demo.py actually imports and uses postrun_mismatch.apply_lag_exclusion.

    This test inspects the production source to catch the class of bug where:
      - The logic module is correct
      - But paper_demo.py uses an inline copy / different variable
    """

    def test_paper_demo_imports_apply_lag_exclusion(self):
        """paper_demo.py must import apply_lag_exclusion from the canonical module."""
        from pathlib import Path
        src = Path("src/stock_swing/cli/paper_demo.py").read_text()
        assert "from stock_swing.guardrails.postrun_mismatch import apply_lag_exclusion" in src, \
            "paper_demo.py must import apply_lag_exclusion from postrun_mismatch module"

    def test_paper_demo_passes_adjusted_count_to_guardrail(self):
        """R0-v2-C: _postrun_snapshot (RiskSnapshot) must be built with _adjusted_mismatch.

        Updated from dict-literal check (pre-R0-v2-C) to RiskSnapshot pattern.
        The old _post_metrics dict was replaced by build_risk_snapshot(...) in R0-v2-C.
        Verify that _adjusted_mismatch is passed to broker_tracker_mismatch_count.
        """
        from pathlib import Path
        src = Path("src/stock_swing/cli/paper_demo.py").read_text()

        # R0-v2-C pattern: build_risk_snapshot(..., broker_tracker_mismatch_count=_adjusted_mismatch, ...)
        assert "broker_tracker_mismatch_count=_adjusted_mismatch" in src, (
            "paper_demo.py must pass _adjusted_mismatch to build_risk_snapshot() "
            "as broker_tracker_mismatch_count (R0-v2-C requirement)"
        )
