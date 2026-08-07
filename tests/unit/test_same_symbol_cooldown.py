"""Tests for the same-symbol buy cooldown guard (2026-08-07, NBIS incident).

See src/stock_swing/risk/same_symbol_cooldown.py module docstring for full
context: three NBIS BUYs within ~37h were all stopped out together for
-$7,774 on 2026-08-06. This guard blocks additional BUYs into a symbol
that already has an open position entered within the cooldown window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from stock_swing.risk.same_symbol_cooldown import (
    SameSymbolCooldownConfig,
    _most_recent_open_entry_by_symbol,
    filter_buys_by_same_symbol_cooldown,
)


def _decision(symbol: str, action: str = "buy") -> SimpleNamespace:
    return SimpleNamespace(symbol=symbol, action=action)


def _open_trade(symbol: str, entry_time: str) -> dict:
    return {"symbol": symbol, "entry_time": entry_time, "status": "open"}


NOW = datetime(2026, 8, 6, 20, 0, 0, tzinfo=timezone.utc)


# ── Normal path: within / outside cooldown ──────────────────────────────── #

def test_buy_blocked_within_cooldown_window():
    decisions = [_decision("NBIS")]
    open_trades = [_open_trade("NBIS", (NOW - timedelta(hours=2)).isoformat())]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    assert allowed == []
    assert len(blocked) == 1
    assert blocked[0][0] == "NBIS"
    assert "same_symbol_cooldown" in blocked[0][1]


def test_buy_allowed_after_cooldown_expires():
    decisions = [_decision("NBIS")]
    open_trades = [_open_trade("NBIS", (NOW - timedelta(hours=25)).isoformat())]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    assert len(allowed) == 1
    assert blocked == []


def test_buy_allowed_for_symbol_with_no_open_position():
    decisions = [_decision("NBIS")]
    open_trades = [_open_trade("AMD", (NOW - timedelta(hours=1)).isoformat())]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    assert len(allowed) == 1
    assert blocked == []


# ── Boundary values ──────────────────────────────────────────────────────── #

def test_buy_allowed_exactly_at_cooldown_boundary():
    """elapsed_hours == cooldown_hours must NOT be blocked (strict <)."""
    decisions = [_decision("NBIS")]
    open_trades = [_open_trade("NBIS", (NOW - timedelta(hours=24)).isoformat())]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    assert len(allowed) == 1
    assert blocked == []


def test_buy_blocked_one_second_before_boundary():
    decisions = [_decision("NBIS")]
    open_trades = [_open_trade("NBIS", (NOW - timedelta(hours=24) + timedelta(seconds=1)).isoformat())]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    assert allowed == []
    assert len(blocked) == 1


# ── Multiple lots per symbol: must use the MOST RECENT entry ────────────── #

def test_multiple_lots_uses_most_recent_entry_time():
    """The NBIS incident itself: 3 lots at different times. Cooldown must be
    measured from the most recent lot, not the oldest."""
    decisions = [_decision("NBIS")]
    open_trades = [
        _open_trade("NBIS", (NOW - timedelta(hours=40)).isoformat()),  # oldest lot
        _open_trade("NBIS", (NOW - timedelta(hours=2)).isoformat()),   # most recent lot
    ]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    # Must be blocked because the most recent lot (2h ago) is within cooldown,
    # even though the oldest lot (40h ago) alone would have cleared it.
    assert allowed == []
    assert len(blocked) == 1


def test_most_recent_open_entry_by_symbol_picks_latest():
    open_trades = [
        _open_trade("NBIS", "2026-08-04T16:00:00+00:00"),
        _open_trade("NBIS", "2026-08-05T19:55:00+00:00"),
        _open_trade("AMD", "2026-08-01T00:00:00+00:00"),
    ]
    latest = _most_recent_open_entry_by_symbol(open_trades)
    assert latest["NBIS"] == datetime(2026, 8, 5, 19, 55, tzinfo=timezone.utc)
    assert latest["AMD"] == datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)


# ── Non-buy decisions always pass through ──────────────────────────────── #

def test_sell_decisions_never_blocked():
    decisions = [_decision("NBIS", action="sell")]
    open_trades = [_open_trade("NBIS", (NOW - timedelta(hours=1)).isoformat())]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    assert len(allowed) == 1
    assert blocked == []


def test_hold_decisions_never_blocked():
    decisions = [_decision("NBIS", action="hold")]
    open_trades = [_open_trade("NBIS", (NOW - timedelta(hours=1)).isoformat())]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, _ = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    assert len(allowed) == 1


# ── Missing / malformed data fallback ────────────────────────────────────── #

def test_missing_entry_time_does_not_block():
    decisions = [_decision("NBIS")]
    open_trades = [{"symbol": "NBIS", "status": "open"}]  # no entry_time
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    assert len(allowed) == 1
    assert blocked == []


def test_malformed_entry_time_does_not_raise_or_block():
    decisions = [_decision("NBIS")]
    open_trades = [{"symbol": "NBIS", "entry_time": "not-a-timestamp", "status": "open"}]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    assert len(allowed) == 1
    assert blocked == []


def test_empty_open_trades_allows_all_buys():
    decisions = [_decision("NBIS"), _decision("AMD")]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, [], cfg, now=NOW)

    assert len(allowed) == 2
    assert blocked == []


def test_empty_decisions_returns_empty():
    open_trades = [_open_trade("NBIS", (NOW - timedelta(hours=1)).isoformat())]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown([], open_trades, cfg, now=NOW)

    assert allowed == []
    assert blocked == []


# ── Disabled config bypasses everything ─────────────────────────────────── #

def test_disabled_config_bypasses_cooldown():
    decisions = [_decision("NBIS")]
    open_trades = [_open_trade("NBIS", (NOW - timedelta(minutes=1)).isoformat())]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0, disabled=True)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    assert len(allowed) == 1
    assert blocked == []


# ── Multiple symbols in one call, independent evaluation ────────────────── #

def test_multiple_symbols_evaluated_independently():
    decisions = [_decision("NBIS"), _decision("AMD"), _decision("MSFT")]
    open_trades = [
        _open_trade("NBIS", (NOW - timedelta(hours=1)).isoformat()),   # blocked
        _open_trade("AMD", (NOW - timedelta(hours=48)).isoformat()),   # allowed (past cooldown)
        # MSFT: no open position at all -> allowed
    ]
    cfg = SameSymbolCooldownConfig(cooldown_hours=24.0)

    allowed, blocked = filter_buys_by_same_symbol_cooldown(decisions, open_trades, cfg, now=NOW)

    allowed_symbols = {d.symbol for d in allowed}
    blocked_symbols = {s for s, _ in blocked}
    assert allowed_symbols == {"AMD", "MSFT"}
    assert blocked_symbols == {"NBIS"}


# ── Config from_env ──────────────────────────────────────────────────────── #

def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("SAME_SYMBOL_COOLDOWN_HOURS", raising=False)
    monkeypatch.delenv("SAME_SYMBOL_COOLDOWN_DISABLED", raising=False)
    cfg = SameSymbolCooldownConfig.from_env()
    assert cfg.cooldown_hours == 24.0
    assert cfg.disabled is False


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("SAME_SYMBOL_COOLDOWN_HOURS", "48")
    monkeypatch.setenv("SAME_SYMBOL_COOLDOWN_DISABLED", "true")
    cfg = SameSymbolCooldownConfig.from_env()
    assert cfg.cooldown_hours == 48.0
    assert cfg.disabled is True
