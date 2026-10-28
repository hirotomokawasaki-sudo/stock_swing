"""Per-lot time_based (max hold) exit qty planning (2026-09-02).

Background -- materialized incident this module fixes
-----------------------------------------------------
``SimpleExitV2Strategy.generate()`` computes ``hold_days`` from the symbol's
EARLIEST open-lot entry time (``PnLTracker.get_open_position_context_by_
symbol()`` aggregates ``created_at`` as the minimum across lots). When the
oldest lot crosses ``max_hold_days``, the resulting time_based sell signal
liquidates the symbol's ENTIRE position -- including much younger lots whose
own clocks are nowhere near expiry.

On 2026-09-01T19:55Z (the first market_close run after the lot-level shadow
diagnostic landed), this stopped being hypothetical:

    NOW : old lot 15 sh (2026-08-12, day 20)  -> time_based fired
          new lot 385 sh (2026-08-31, day 1!) -> dragged out at -$2,333
    ORCL: old lot 13 sh (2026-08-12, day 20)  -> time_based fired
          newer lot 340 sh (2026-08-17, day 15) -> dragged out at -$2,768
    PLTR: same shape; the younger lot happened to be profitable (+$1,334)

Net effect: roughly -$5,100 of realized loss on lots that had not reached
their own max-hold and were not individually eligible for any exit trigger
(the shadow log ``data/lot_level_exit_shadow_log.jsonl`` recorded all three
as ``aggregate_exit_lot_disagreement`` the same run).

What this module does
---------------------
Given the tracker's open lots for a symbol, it computes how many shares
actually belong to EXPIRED lots (per-lot ``hold_days >= max_hold_days``,
using the same calendar-day ``.days`` truncation ``generate()`` uses). The
caller (paper_demo, behind the ``per_lot_time_based_exit_enabled`` config
flag, default OFF) uses this to convert a full-position time_based sell into
a partial sell of just the expired shares. Because ``PnLTracker.
record_exit()`` closes lots in FIFO order, selling exactly the expired
share count closes exactly the expired (oldest) lots and leaves younger
lots open with their own clocks/protections intact.

Fail-closed rule: if ANY open lot for the symbol has a missing or
unparseable entry_time, planning returns ``is_partial=False`` and the
caller falls back to today's production behavior (full-position exit).
Unknown lot ages must never silently shrink a risk-reducing exit.

Scope guard: this module only plans quantities for the time_based branch.
Trailing/breakeven/stop_loss remain symbol-level aggregates (monitored by
``lot_level_exit_diagnostic``; promoting those to per-lot execution is a
separate, larger design reviewed on 2026-09-08).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PerLotTimeBasedExitPlan:
    """Result of planning a per-lot time_based exit for one symbol."""

    symbol: str
    total_open_qty: int
    expired_qty: int
    expired_lot_ids: list[str] = field(default_factory=list)
    kept_lot_ids: list[str] = field(default_factory=list)
    # True only when a partial exit is both meaningful and safe:
    # 0 < expired_qty < total_open_qty and every lot's age was parseable.
    is_partial: bool = False
    # Why is_partial is False when it is (for logging/observability):
    # "all_expired" | "none_expired" | "unparseable_entry_time" | "no_lots" | "partial"
    reason: str = "no_lots"


def plan_time_based_partial_exit(
    *,
    symbol: str,
    open_trades: list[dict[str, Any]],
    max_hold_days: int,
    now: datetime | None = None,
) -> PerLotTimeBasedExitPlan:
    """Plan the expired-lot share count for a time_based exit on *symbol*.

    Args:
        symbol: Symbol whose aggregate time_based exit fired.
        open_trades: ``PnLTracker.get_open_positions()`` output (all symbols
            accepted; filtered here by symbol, case-insensitive).
        max_hold_days: The SAME value ``SimpleExitV2Strategy`` used
            (``exit_strat.max_hold_days``), so per-lot expiry can never
            disagree with the aggregate trigger's threshold.
        now: Override current time for testing.

    Returns:
        PerLotTimeBasedExitPlan. Callers must only act on plans with
        ``is_partial=True``; every other outcome means "keep today's
        full-position behavior".
    """
    now_dt = now or datetime.now(timezone.utc)
    sym_upper = (symbol or "").upper()

    lots = [
        t for t in open_trades
        if str(t.get("symbol") or "").upper() == sym_upper
        and int(float(t.get("qty") or 0)) > 0
    ]
    if not lots:
        return PerLotTimeBasedExitPlan(
            symbol=sym_upper, total_open_qty=0, expired_qty=0, reason="no_lots",
        )

    total_qty = 0
    expired_qty = 0
    expired_ids: list[str] = []
    kept_ids: list[str] = []

    for lot in lots:
        qty = int(float(lot.get("qty") or 0))
        total_qty += qty
        lot_id = str(lot.get("trade_id") or "")

        entry_time_str = lot.get("entry_time")
        if not entry_time_str:
            logger.warning(
                "per_lot_time_based_exit: %s lot %s has no entry_time -- "
                "falling back to full-position exit (fail-closed)",
                sym_upper, lot_id,
            )
            return PerLotTimeBasedExitPlan(
                symbol=sym_upper, total_open_qty=total_qty, expired_qty=0,
                reason="unparseable_entry_time",
            )
        try:
            entry_dt = datetime.fromisoformat(str(entry_time_str).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.warning(
                "per_lot_time_based_exit: %s lot %s entry_time %r unparseable -- "
                "falling back to full-position exit (fail-closed)",
                sym_upper, lot_id, entry_time_str,
            )
            return PerLotTimeBasedExitPlan(
                symbol=sym_upper, total_open_qty=total_qty, expired_qty=0,
                reason="unparseable_entry_time",
            )

        # Same calendar-day truncation semantics as generate()'s hold_days.
        hold_days = (now_dt - entry_dt).days
        if hold_days >= max_hold_days:
            expired_qty += qty
            expired_ids.append(lot_id)
        else:
            kept_ids.append(lot_id)

    if expired_qty <= 0:
        # Aggregate said max-hold reached but no individual lot is expired.
        # (Possible when the aggregate created_at came from broker-side
        # created_at rather than tracker entry_time.) Fail closed: keep the
        # aggregate full-exit behavior rather than suppressing a
        # risk-reducing exit.
        return PerLotTimeBasedExitPlan(
            symbol=sym_upper, total_open_qty=total_qty, expired_qty=0,
            expired_lot_ids=[], kept_lot_ids=kept_ids, reason="none_expired",
        )

    if expired_qty >= total_qty:
        return PerLotTimeBasedExitPlan(
            symbol=sym_upper, total_open_qty=total_qty, expired_qty=total_qty,
            expired_lot_ids=expired_ids, kept_lot_ids=[], reason="all_expired",
        )

    return PerLotTimeBasedExitPlan(
        symbol=sym_upper, total_open_qty=total_qty, expired_qty=expired_qty,
        expired_lot_ids=expired_ids, kept_lot_ids=kept_ids,
        is_partial=True, reason="partial",
    )
