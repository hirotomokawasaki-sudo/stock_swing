"""Post-run broker/tracker mismatch lag exclusion logic.

Extracted from paper_demo.py so that:
  1. Tests import and call *this* module (not inline copies).
  2. paper_demo.py imports from here — single source of truth.
  3. Any divergence between test expectations and production code is caught.

History:
  G1-v2   (2026-07-21): exclude symbol-presence lag (BUY / SELL)
  G1-v2-b (2026-07-21): also exclude qty-mismatch lag on newly submitted SELLs
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

    G1-v2-b (qty-mismatch lag):
      - qty_mismatches whose symbol ∈ new_sell_symbols
        → partial fill creates transient qty discrepancy; not a real integrity issue

    Real mismatches (symbol/qty not linked to this run's submissions) still count.
    """
    new_buy_symbols: set[str] = {
        s.symbol for s in new_submissions if getattr(s, "side", "") == "buy"
    }
    new_sell_symbols: set[str] = {
        s.symbol for s in new_submissions if getattr(s, "side", "") == "sell"
    }

    # G1-v2: presence lag
    excused_presence: frozenset[str] = frozenset(
        (set(bt_diff.get("tracker_only", [])) & new_buy_symbols)
        | (set(bt_diff.get("broker_only", [])) & new_sell_symbols)
    )

    # G1-v2-b: qty-mismatch lag on SELL submissions only
    excused_qty: list[str] = [
        q["symbol"]
        for q in bt_diff.get("qty_mismatches", [])
        if q["symbol"] in new_sell_symbols
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
