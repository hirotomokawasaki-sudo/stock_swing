"""R7-v2-A (2026-08-14): MarketCalendar.previous_trading_close_utc() tests.

Used by the console's daily-bar / sector-benchmark source SLA checks to
compute staleness relative to the most recently confirmed 16:00 ET close,
instead of a fixed wall-clock window that doesn't account for
weekends/holidays.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from stock_swing.utils.market_calendar import MarketCalendar

ET = ZoneInfo("America/New_York")


def _et(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ET)


class TestPreviousTradingCloseUtc:
    def test_during_regular_hours_returns_previous_day_close(self):
        """Tue 2026-07-21 11:00 ET (market open, before today's close) ->
        Monday 2026-07-20's 16:00 ET close."""
        dt = _et(2026, 7, 21, 11, 0)
        close = MarketCalendar.previous_trading_close_utc(dt).astimezone(ET)
        assert close.date().isoformat() == "2026-07-20"
        assert close.hour == 16

    def test_after_todays_close_returns_todays_close(self):
        """Tue 2026-07-21 18:00 ET (after today's 16:00 close) -> today's close."""
        dt = _et(2026, 7, 21, 18, 0)
        close = MarketCalendar.previous_trading_close_utc(dt).astimezone(ET)
        assert close.date().isoformat() == "2026-07-21"

    def test_exactly_at_close_returns_todays_close(self):
        """Exactly 16:00 ET must count as 'today's close has happened'."""
        dt = _et(2026, 7, 21, 16, 0)
        close = MarketCalendar.previous_trading_close_utc(dt).astimezone(ET)
        assert close.date().isoformat() == "2026-07-21"

    def test_saturday_returns_fridays_close(self):
        dt = _et(2026, 7, 25, 11, 0)  # Saturday
        close = MarketCalendar.previous_trading_close_utc(dt).astimezone(ET)
        assert close.date().isoformat() == "2026-07-24"  # Friday

    def test_sunday_returns_fridays_close(self):
        dt = _et(2026, 7, 26, 11, 0)  # Sunday
        close = MarketCalendar.previous_trading_close_utc(dt).astimezone(ET)
        assert close.date().isoformat() == "2026-07-24"  # Friday

    def test_monday_before_open_returns_fridays_close(self):
        """Monday 2026-07-27 06:00 ET (before Monday's own close has
        happened, and before Monday's open too) -> Friday's close."""
        dt = _et(2026, 7, 27, 6, 0)
        close = MarketCalendar.previous_trading_close_utc(dt).astimezone(ET)
        assert close.date().isoformat() == "2026-07-24"  # Friday

    def test_holiday_is_skipped(self):
        """Day after Independence Day (2025-07-04, Friday) at 11:00 ET on
        2025-07-07 (Monday) -> skips weekend + holiday back to 2025-07-03
        (Thursday, the last trading day before the holiday weekend)."""
        dt = _et(2025, 7, 7, 11, 0)  # Monday, market open, before close
        close = MarketCalendar.previous_trading_close_utc(dt).astimezone(ET)
        assert close.date().isoformat() == "2025-07-03"

    def test_returns_utc_tz(self):
        dt = _et(2026, 7, 21, 18, 0)
        close = MarketCalendar.previous_trading_close_utc(dt)
        assert close.tzinfo is not None
        assert close.utcoffset().total_seconds() == 0

    def test_defaults_to_now_does_not_crash(self):
        close = MarketCalendar.previous_trading_close_utc()
        assert close.tzinfo is not None
