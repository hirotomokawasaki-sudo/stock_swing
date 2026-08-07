"""Same-symbol buy cooldown guard.

Motivation (2026-08-07, NBIS incident review):
Between 2026-08-04 16:00 UTC and 2026-08-06 04:55 UTC (~37 hours) the
strategy submitted three separate BUY orders for NBIS ($224.32, $225.99,
$221.59 -- all within a $5 band near a post-drop bounce), building a 227-
share position. All three lots were closed in a single stop_loss event on
2026-08-06 19:55 UTC at $189.40, for a combined loss of -$7,774. NBIS is an
extreme-volatility name (3-month annualized return std ~130%, already down
>25% from its 52-week high at the time of entry): the "strong bullish
momentum" signal that fired three times in a row was very plausibly the
same post-drop dead-cat bounce being re-detected, not three independent
opportunities.

None of the existing guardrails (volume/ADR/rolling-PF entry filter, ETF
guardrail, risk budget, correlation cluster cap, position-size cap) are
designed to catch "we already hold this symbol and just bought more of it
a few hours ago" -- the correlation cluster cap and position-size cap only
look at *notional* exposure, not *recency* of the last buy into the same
symbol. This module adds that missing check: block (or, in shadow mode,
just log) a BUY into any symbol that already has an open tracker position
opened (or added to) within the configured cooldown window.

This is intentionally a narrow, local guard (Plan A from the 2026-08-07
review) -- it does not touch volatility scoring or momentum/signal-strength
calculation (see same_symbol_cooldown.py siblings volatility_gate.py and
distance_from_high_feature.py, planned as Plan B/C, which are broader and
require paper A/B verification before being wired into the live strategy).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DEFAULT_COOLDOWN_HOURS = 24.0


@dataclass
class SameSymbolCooldownConfig:
    """Threshold configuration for the same-symbol buy cooldown guard."""

    cooldown_hours: float = DEFAULT_COOLDOWN_HOURS
    disabled: bool = False

    @classmethod
    def from_env(cls) -> "SameSymbolCooldownConfig":
        return cls(
            cooldown_hours=float(
                os.environ.get("SAME_SYMBOL_COOLDOWN_HOURS", DEFAULT_COOLDOWN_HOURS)
            ),
            disabled=os.environ.get("SAME_SYMBOL_COOLDOWN_DISABLED", "").lower()
            in ("1", "true", "yes"),
        )


def _parse_iso(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _most_recent_open_entry_by_symbol(
    open_trades: list[dict[str, Any]],
) -> dict[str, datetime]:
    """Return {symbol: most_recent_entry_time} across all open tracker lots.

    Multiple lots (partial fills / repeated buys) per symbol are common; we
    only care about the *most recent* buy into a symbol, since that is the
    one the cooldown should be measured from.
    """
    latest: dict[str, datetime] = {}
    for trade in open_trades:
        symbol = str(trade.get("symbol") or "").upper()
        if not symbol:
            continue
        entry_dt = _parse_iso(trade.get("entry_time"))
        if entry_dt is None:
            continue
        existing = latest.get(symbol)
        if existing is None or entry_dt > existing:
            latest[symbol] = entry_dt
    return latest


def filter_buys_by_same_symbol_cooldown(
    decisions: list[Any],
    open_trades: list[dict[str, Any]],
    config: SameSymbolCooldownConfig | None = None,
    now: datetime | None = None,
) -> tuple[list[Any], list[tuple[str, str]]]:
    """Block BUY decisions into a symbol bought within the cooldown window.

    Args:
        decisions: list of DecisionRecord-like objects (must have .action,
            .symbol attributes). Non-buy decisions always pass through.
        open_trades: open tracker trades (e.g. pnl_tracker.get_open_positions()),
            each a dict with at least "symbol" and "entry_time".
        config: SameSymbolCooldownConfig (defaults to from_env()).
        now: current time (injectable for tests; defaults to
            datetime.now(timezone.utc)).

    Returns:
        (allowed, blocked) where blocked is a list of (symbol, reason).
    """
    cfg = config or SameSymbolCooldownConfig.from_env()
    if cfg.disabled:
        return list(decisions), []

    current_time = now or datetime.now(timezone.utc)
    latest_entry_by_symbol = _most_recent_open_entry_by_symbol(open_trades)

    allowed: list[Any] = []
    blocked: list[tuple[str, str]] = []

    for decision in decisions:
        action = getattr(decision, "action", "")
        symbol = str(getattr(decision, "symbol", "") or "").upper()

        if action != "buy" or not symbol:
            allowed.append(decision)
            continue

        last_entry = latest_entry_by_symbol.get(symbol)
        if last_entry is None:
            allowed.append(decision)
            continue

        elapsed_hours = (current_time - last_entry).total_seconds() / 3600.0
        if elapsed_hours < cfg.cooldown_hours:
            reason = (
                f"same_symbol_cooldown: last buy into {symbol} was "
                f"{elapsed_hours:.1f}h ago (< {cfg.cooldown_hours:.0f}h cooldown); "
                f"blocking additional buy while an existing position is still fresh"
            )
            blocked.append((symbol, reason))
        else:
            allowed.append(decision)

    return allowed, blocked
