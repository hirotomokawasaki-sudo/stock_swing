"""Market trading day guard for cron job early exit.

R7-v2 / H8 (2026-07-23): skip non-maintenance cron jobs on non-market days
(weekends and US holidays) to reduce wasted API calls and log noise.

Usage in CLI main():
    from stock_swing.utils.market_guard import should_skip_non_market_day
    skip, reason = should_skip_non_market_day()
    if skip:
        print(f"⏭  Skipping: {reason}")
        if args.cron_summary_json:
            emit_cron_summary({"job": "...", "status": "skipped", "reason": reason})
        return 0

Override (for manual testing on weekends):
    export STOCK_SWING_FORCE_MARKET_DAY=true

Maintenance jobs (reconcile_orders, audit) should NOT call this guard –
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
    Time of day is ignored; only the calendar date matters.

    Args:
        dt: Datetime to check (defaults to now in Asia/Tokyo).

    Returns:
        Tuple of (is_trading_day, human-readable reason).
    """
    if dt is None:
        dt = datetime.now(ZoneInfo("Asia/Tokyo"))

    jst = ZoneInfo("Asia/Tokyo")
    dt_jst = dt.astimezone(jst) if dt.tzinfo is not None else dt.replace(tzinfo=jst)

    # Weekend check
    if dt_jst.weekday() >= 5:  # Saturday=5, Sunday=6
        day_name = "Saturday" if dt_jst.weekday() == 5 else "Sunday"
        return False, f"Non-trading day: {day_name} {dt_jst.strftime('%Y-%m-%d')}"

    # US holiday check
    is_holiday, holiday_name = MarketCalendar.is_us_holiday(dt_jst)
    if is_holiday:
        return False, f"Non-trading day: {holiday_name} ({dt_jst.strftime('%Y-%m-%d')})"

    return True, f"Trading day: {dt_jst.strftime('%Y-%m-%d %a')}"


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
