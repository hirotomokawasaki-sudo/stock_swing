"""Market trading day / trading session guards for cron job early exit.

R7-v2 / H8 (2026-07-23): skip non-maintenance cron jobs on non-market days
(weekends and US holidays) to reduce wasted API calls and log noise.

R7-v2 (2026-08-14): extend the same idea *within* a trading day. Some
non-maintenance jobs (e.g. stock_swing_news_collection, which runs every 4h
around the clock) still execute their full API cycle during the ET
"dead zone" (after after-hours ends at 20:00 ET, before pre-market starts at
04:00 ET) even on a genuine US trading weekday, burning API calls and
producing snapshots with no trading-session relevance. should_skip_outside_
market_hours() closes that gap by additionally checking the current trading
session (pre-market / regular / after-hours) via MarketCalendar.is_market_
open(), while should_skip_non_market_day() keeps checking only the calendar
date (weekday/holiday) for callers (e.g. paper_demo.py) that already have
their own session-specific gating.

Usage in CLI main():
    from stock_swing.utils.market_guard import should_skip_non_market_day
    skip, reason = should_skip_non_market_day()
    if skip:
        print(f"⏭  Skipping: {reason}")
        if args.cron_summary_json:
            emit_cron_summary({"job": "...", "status": "skipped", "reason": reason})
        return 0

Override (for manual testing on weekends / outside trading hours):
    export STOCK_SWING_FORCE_MARKET_DAY=true

Maintenance jobs (reconcile_orders, audit) should NOT call either guard –
they should always run to cancel stale orders and check integrity.
"""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_swing.utils.market_calendar import MarketCalendar


def is_us_trading_day(dt: datetime | None = None) -> tuple[bool, str]:
    """Return (is_trading_day, reason) for the given datetime.

    A trading day is a US weekday that is not a US market holiday.
    Time of day is ignored; only the **ET calendar date** matters.

    Bug fixed (2026-07-25): previously used JST date for the weekend check.
    US Friday afternoon crons (15:55-19:55 UTC) fire on JST Saturday morning,
    causing them to be incorrectly skipped every Friday.  Now uses ET
    (America/New_York) as the authoritative calendar, matching the US market.

    Args:
        dt: Datetime to check (defaults to now).

    Returns:
        Tuple of (is_trading_day, human-readable reason).
    """
    if dt is None:
        dt = datetime.now(ZoneInfo("Asia/Tokyo"))

    # Use ET (America/New_York) for calendar date — the US market is US-based.
    # JST is UTC+9; ET is UTC-4/-5.  Friday afternoon ET = Saturday JST, which
    # is still a valid US trading day.  Using JST here was the root cause of
    # the 2026-07-24 US Friday cron skip incident.
    et_tz = ZoneInfo("America/New_York")
    dt_et = dt.astimezone(et_tz) if dt.tzinfo is not None else dt.replace(tzinfo=et_tz)

    # Weekend check (using ET date)
    if dt_et.weekday() >= 5:  # Saturday=5, Sunday=6
        day_name = "Saturday" if dt_et.weekday() == 5 else "Sunday"
        return False, f"Non-trading day: {day_name} {dt_et.strftime('%Y-%m-%d')}"

    # US holiday check (using ET date)
    is_holiday, holiday_name = MarketCalendar.is_us_holiday(dt_et)
    if is_holiday:
        return False, f"Non-trading day: {holiday_name} ({dt_et.strftime('%Y-%m-%d')})"

    return True, f"Trading day: {dt_et.strftime('%Y-%m-%d %a')}"


def should_skip_non_market_day(dt: datetime | None = None) -> tuple[bool, str]:
    """Return (should_skip, reason) – True when cron should exit early.

    Respects the STOCK_SWING_FORCE_MARKET_DAY=true env-var override so that
    manual runs on weekends / holidays are still possible.

    Args:
        dt: Datetime to check (defaults to now).

    Returns:
        (True, reason) when the job should be skipped.
        (False, reason) when the job should proceed normally.
    """
    # Override: manual testing / special sessions
    force = os.environ.get("STOCK_SWING_FORCE_MARKET_DAY", "").lower() in ("1", "true", "yes")
    if force:
        return False, "STOCK_SWING_FORCE_MARKET_DAY override active – proceeding on non-market day"

    is_trading, reason = is_us_trading_day(dt)
    if not is_trading:
        return True, reason
    return False, reason


def should_skip_outside_market_hours(dt: datetime | None = None) -> tuple[bool, str]:
    """Return (should_skip, reason) for non-maintenance jobs that should also
    early-exit *within* a trading weekday when no trading session is active.

    This is a superset of should_skip_non_market_day(): it first applies the
    same weekend/holiday check, then additionally skips during the ET dead
    zone (after after-hours ends, before pre-market starts -- roughly
    20:00-04:00 ET) on an otherwise valid trading day.

    Respects the same STOCK_SWING_FORCE_MARKET_DAY=true override as
    should_skip_non_market_day().

    Args:
        dt: Datetime to check (defaults to now).

    Returns:
        (True, reason) when the job should be skipped.
        (False, reason) when the job should proceed normally.
    """
    force = os.environ.get("STOCK_SWING_FORCE_MARKET_DAY", "").lower() in ("1", "true", "yes")
    if force:
        return False, "STOCK_SWING_FORCE_MARKET_DAY override active – proceeding outside market hours"

    skip_day, reason = should_skip_non_market_day(dt)
    if skip_day:
        return True, reason

    is_open, session_reason = MarketCalendar.is_market_open(dt)
    if not is_open:
        return True, session_reason
    return False, session_reason
