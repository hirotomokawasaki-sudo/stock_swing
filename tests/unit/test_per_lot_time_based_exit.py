"""Unit tests for per_lot_time_based_exit.py (2026-09-02, R16 incident fix).

Regression basis: 2026-09-01T19:55Z market_close run. The symbol-level
max-hold clock (driven by the OLDEST lot) liquidated entire positions,
dragging out young lots:
  NOW : old 15sh (2026-08-12, day 20) + new 385sh (2026-08-31, day 1) ->
        the 1-day-old lot was sold at -$2,333 under "Max hold period reached"
  ORCL: 13sh (day 20) + 340sh (day 15) -> younger lot sold at -$2,768
Shadow log data/lot_level_exit_shadow_log.jsonl recorded all three as
aggregate_exit_lot_disagreement the same run.
"""

from datetime import datetime, timedelta, timezone

import pytest

from stock_swing.risk.per_lot_time_based_exit import (
    PerLotTimeBasedExitPlan,
    plan_time_based_partial_exit,
)

NOW_DT = datetime(2026, 9, 1, 19, 55, 0, tzinfo=timezone.utc)


def _lot(trade_id, symbol, qty, days_ago: float | None, entry_time_override=None):
    if entry_time_override is not None:
        entry_time = entry_time_override
    elif days_ago is None:
        entry_time = None
    else:
        entry_time = (NOW_DT - timedelta(days=days_ago)).isoformat()
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "qty": qty,
        "entry_time": entry_time,
        "status": "open",
    }


# ── Incident reproduction ────────────────────────────────────────────────

def test_reproduces_now_incident_partial_plan():
    """NOW 2026-09-01: old 15sh lot (day 20) expired, new 385sh lot (day 1)
    not expired -> plan must sell exactly 15 shares and keep 385."""
    lots = [
        _lot("broker_open_0231_NOW", "NOW", 15, 20.1),
        _lot("NOW-5144f488", "NOW", 385, 1.0),
    ]
    plan = plan_time_based_partial_exit(
        symbol="NOW", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.is_partial is True, "the incident shape must produce a partial plan"
    assert plan.expired_qty == 15
    assert plan.total_open_qty == 400
    assert plan.expired_lot_ids == ["broker_open_0231_NOW"]
    assert plan.kept_lot_ids == ["NOW-5144f488"]
    assert plan.reason == "partial"


def test_reproduces_orcl_incident_partial_plan():
    """ORCL 2026-09-01: 13sh (day 20) expired, 340sh (day 15) not."""
    lots = [
        _lot("broker_open_0238_ORCL", "ORCL", 13, 20.2),
        _lot("broker_open_0239_ORCL", "ORCL", 340, 15.2),
    ]
    plan = plan_time_based_partial_exit(
        symbol="ORCL", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.is_partial is True
    assert plan.expired_qty == 13
    assert plan.kept_lot_ids == ["broker_open_0239_ORCL"]


# ── Non-partial outcomes (must fall back to full-position behavior) ─────

def test_all_lots_expired_is_not_partial():
    lots = [
        _lot("A-1", "AAA", 10, 25),
        _lot("A-2", "AAA", 20, 21),
    ]
    plan = plan_time_based_partial_exit(
        symbol="AAA", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.is_partial is False
    assert plan.reason == "all_expired"
    assert plan.expired_qty == 30


def test_no_lots_expired_is_not_partial_fail_closed():
    """Aggregate anomaly (no lot individually expired): keep full exit."""
    lots = [
        _lot("B-1", "BBB", 10, 5),
        _lot("B-2", "BBB", 20, 3),
    ]
    plan = plan_time_based_partial_exit(
        symbol="BBB", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.is_partial is False
    assert plan.reason == "none_expired"
    assert plan.expired_qty == 0


def test_missing_entry_time_fail_closed():
    lots = [
        _lot("C-1", "CCC", 10, 25),
        _lot("C-2", "CCC", 20, None),  # no entry_time
    ]
    plan = plan_time_based_partial_exit(
        symbol="CCC", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.is_partial is False
    assert plan.reason == "unparseable_entry_time"


def test_garbage_entry_time_fail_closed():
    lots = [
        _lot("D-1", "DDD", 10, 25),
        _lot("D-2", "DDD", 20, None, entry_time_override="not-a-date"),
    ]
    plan = plan_time_based_partial_exit(
        symbol="DDD", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.is_partial is False
    assert plan.reason == "unparseable_entry_time"


def test_no_lots_for_symbol():
    plan = plan_time_based_partial_exit(
        symbol="ZZZ", open_trades=[_lot("X-1", "XXX", 10, 25)],
        max_hold_days=20, now=NOW_DT,
    )
    assert plan.is_partial is False
    assert plan.reason == "no_lots"
    assert plan.total_open_qty == 0


# ── Semantics details ────────────────────────────────────────────────────

def test_boundary_exactly_max_hold_days_counts_as_expired():
    """generate() fires at hold_days >= max_hold_days; per-lot expiry must
    use the same >= comparison so they can never disagree at the boundary."""
    lots = [
        _lot("E-1", "EEE", 10, 20.0),  # .days == 20 exactly
        _lot("E-2", "EEE", 5, 2),
    ]
    plan = plan_time_based_partial_exit(
        symbol="EEE", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.is_partial is True
    assert plan.expired_qty == 10


def test_calendar_day_truncation_matches_generate():
    """19.9 days -> .days == 19 -> NOT expired at max_hold_days=20 (same
    truncation semantics as generate()'s hold_duration.days)."""
    lots = [
        _lot("F-1", "FFF", 10, 19.9),
        _lot("F-2", "FFF", 5, 21),
    ]
    plan = plan_time_based_partial_exit(
        symbol="FFF", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.is_partial is True
    assert plan.expired_qty == 5, "only the 21-day lot is expired"
    assert plan.kept_lot_ids == ["F-1"]


def test_symbol_matching_case_insensitive():
    lots = [
        _lot("G-1", "ggg", 10, 25),
        _lot("G-2", "GGG", 5, 2),
    ]
    plan = plan_time_based_partial_exit(
        symbol="GgG", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.total_open_qty == 15
    assert plan.is_partial is True


def test_zero_qty_lots_ignored():
    lots = [
        _lot("H-1", "HHH", 0, 25),   # zero qty: ignored entirely
        _lot("H-2", "HHH", 10, 25),
        _lot("H-3", "HHH", 5, 2),
    ]
    plan = plan_time_based_partial_exit(
        symbol="HHH", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.total_open_qty == 15
    assert plan.expired_qty == 10


def test_multiple_expired_lots_sum():
    lots = [
        _lot("I-1", "III", 10, 30),
        _lot("I-2", "III", 20, 22),
        _lot("I-3", "III", 40, 3),
    ]
    plan = plan_time_based_partial_exit(
        symbol="III", open_trades=lots, max_hold_days=20, now=NOW_DT,
    )
    assert plan.is_partial is True
    assert plan.expired_qty == 30
    assert set(plan.expired_lot_ids) == {"I-1", "I-2"}
    assert plan.kept_lot_ids == ["I-3"]
