"""Post-run broker/tracker mismatch lag exclusion logic.

Extracted from paper_demo.py so that:
  1. Tests import and call *this* module (not inline copies).
  2. paper_demo.py imports from here — single source of truth.
  3. Any divergence between test expectations and production code is caught.

History:
  G1-v2   (2026-07-21): exclude symbol-presence lag (BUY / SELL)
  G1-v2-b (2026-07-21): also exclude qty-mismatch lag on newly submitted SELLs
  G1-v2-c (2026-07-25): exclude tracker_only ∩ SELL lag (fast-fill SELL phantom)
    Root cause: when a SELL fills immediately, broker removes the position before
    record_exit() is called in tracker.  The position becomes tracker_only, which
    was not previously lag-excused.  This triggered a false HALT on 2026-07-24
    (SKYY phantom; see docs/daily_logs/2026-07-25.md).  The reconcile_orders cron
    fixes the tracker within minutes, so this is always a transient condition.
  G1-v2-d (2026-08-04): exclude qty-mismatch lag on BUY that adds to an EXISTING
    open position (as opposed to a brand-new position, which is already handled
    by the tracker_only presence-lag rule above).
    Root cause: when a BUY is submitted for a symbol that already has an open
    tracker position (e.g. adding a second lot), the tracker records the new
    entry the instant the order is submitted, summing qty across both lots
    immediately.  The broker position qty only reflects the fill once Alpaca's
    fill confirmation + API propagation completes (observed lag: several
    seconds).  During that window broker_qty < tracker_qty for the symbol,
    which the pre-existing qty_mismatches check flags as a real integrity
    issue and HALTs the circuit breaker.
    Incident: 2026-08-03 19:55 JST SNOW false HALT (existing 116-share position
    + new 116-share BUY; postrun check ran ~4s before the second fill
    propagated; broker=116 vs tracker=232). See docs/daily_logs/2026-08-04.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LagExclusionResult:
    """Outcome of apply_lag_exclusion()."""
    adjusted_mismatch_count: int
    raw_mismatch_count: int
    excused_presence: frozenset[str]   # tracker_only BUY lag + broker_only SELL lag
    excused_qty: list[str]             # qty-mismatch SELL lag (G1-v2-b)

    @property
    def any_excused(self) -> bool:
        return bool(self.excused_presence) or bool(self.excused_qty)


def apply_lag_exclusion(
    bt_diff: dict[str, Any],
    new_submissions: list[Any],   # OrderSubmission or duck-typed
) -> LagExclusionResult:
    """Compute adjusted mismatch count by excluding submission-lag false positives.

    Rules
    -----
    G1-v2 (symbol-presence lag):
      - tracker_only ∩ new_buy_symbols  → BUY just submitted; broker API lag
      - broker_only  ∩ new_sell_symbols → SELL just submitted; broker still shows position

    G1-v2-b (qty-mismatch lag, SELL):
      - qty_mismatches whose symbol ∈ new_sell_symbols
        → partial fill creates transient qty discrepancy; not a real integrity issue

    G1-v2-d (qty-mismatch lag, BUY add-to-existing-position):
      - qty_mismatches whose symbol ∈ new_buy_symbols AND tracker_qty > broker_qty
        → BUY submitted for a symbol that already has an open position; tracker
          sums the new lot's qty immediately on submission, but broker qty only
          catches up once the fill is confirmed + propagated (several seconds).
          Only excused when tracker is *ahead* of broker (the expected direction
          for this lag); if broker_qty > tracker_qty for a BUY symbol that is a
          different, real issue and is NOT excused.

    G1-v2-c (fast-fill SELL phantom lag):
      - tracker_only ∩ new_sell_symbols
        → SELL just submitted AND broker filled it immediately (position removed from
          broker positions before record_exit() was called in tracker).  The tracker
          position appears tracker_only for a brief window until reconcile_orders or
          the next paper_demo run calls record_exit().  This is a transient condition
          that resolves within minutes — not a real mismatch.
        Incident: 2026-07-24 SKYY false HALT (see docs/daily_logs/2026-07-25.md).

    Real mismatches (symbol/qty not linked to this run's submissions) still count.
    """
    new_buy_symbols: set[str] = {
        s.symbol for s in new_submissions if getattr(s, "side", "") == "buy"
    }
    new_sell_symbols: set[str] = {
        s.symbol for s in new_submissions if getattr(s, "side", "") == "sell"
    }

    # G1-v2: presence lag
    # G1-v2-c: also excuse tracker_only ∩ new_sell_symbols (fast-fill SELL phantom)
    #   Scenario: SELL submitted this run, broker filled immediately and removed
    #   the position, but record_exit() hasn't been called in the tracker yet.
    #   This makes the symbol appear tracker_only — a false phantom.
    #   reconcile_orders fixes this within the next cron cycle.
    excused_presence: frozenset[str] = frozenset(
        (set(bt_diff.get("tracker_only", [])) & new_buy_symbols)
        | (set(bt_diff.get("broker_only", [])) & new_sell_symbols)
        | (set(bt_diff.get("tracker_only", [])) & new_sell_symbols)  # G1-v2-c
    )

    # G1-v2-b: qty-mismatch lag on SELL submissions only
    # G1-v2-d: qty-mismatch lag on BUY submissions that add to an existing
    #   open position, only when tracker is ahead of broker (tracker_qty >
    #   broker_qty) — the expected direction for this specific lag. A BUY
    #   symbol where broker_qty > tracker_qty is a different, real issue and
    #   must NOT be excused here.
    excused_qty: list[str] = [
        q["symbol"]
        for q in bt_diff.get("qty_mismatches", [])
        if q["symbol"] in new_sell_symbols
        or (
            q["symbol"] in new_buy_symbols
            and float(q.get("tracker_qty", 0)) > float(q.get("broker_qty", 0))
        )
    ]

    raw = bt_diff.get("mismatch_count", 0)
    adjusted = raw - len(excused_presence) - len(excused_qty)

    result = LagExclusionResult(
        adjusted_mismatch_count=max(adjusted, 0),
        raw_mismatch_count=raw,
        excused_presence=excused_presence,
        excused_qty=excused_qty,
    )

    if result.any_excused:
        logger.info(
            "post_run_mismatch: excused presence=%s qty=%s "
            "(broker API lag after submission); raw=%d adjusted=%d",
            sorted(excused_presence),
            excused_qty,
            raw,
            result.adjusted_mismatch_count,
        )

    return result
