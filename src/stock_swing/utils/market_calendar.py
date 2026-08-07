"""Market calendar utilities with US holiday and daylight saving time support.

Handles:
- US market holidays
- Daylight Saving Time (DST) transitions
- Market hours (pre-market, regular, after-hours)
- ET to JST timezone conversions
"""

from datetime import datetime, time, timedelta
from typing import Dict, Tuple
from zoneinfo import ZoneInfo


class MarketCalendar:
    """US stock market calendar with holiday and DST support."""

    # US market holidays (month, day) for fixed dates
    FIXED_HOLIDAYS = {
        (1, 1): "New Year's Day",
        (6, 19): "Juneteenth",
        (7, 4): "Independence Day",
        (12, 25): "Christmas",
    }

    # Market hours in ET
    PRE_MARKET_START = time(4, 0)
    PRE_MARKET_END = time(9, 30)
    REGULAR_START = time(9, 30)
    REGULAR_END = time(16, 0)
    AFTER_HOURS_START = time(16, 0)
    AFTER_HOURS_END = time(20, 0)

    @staticmethod
    def is_us_holiday(date: datetime) -> Tuple[bool, str]:
        """Check if date is a US market holiday.

        Args:
            date: Date to check

        Returns:
            Tuple of (is_holiday, holiday_name)
        """
        month = date.month
        day = date.day
        weekday = date.weekday()  # 0=Monday, 6=Sunday

        # Fixed date holidays
        if (month, day) in MarketCalendar.FIXED_HOLIDAYS:
            return True, MarketCalendar.FIXED_HOLIDAYS[(month, day)]

        # Observed holidays (if fixed date falls on weekend)
        if (month, day - 1) in MarketCalendar.FIXED_HOLIDAYS and weekday == 0:  # Monday
            return True, f"{MarketCalendar.FIXED_HOLIDAYS[(month, day - 1)]} (observed)"
        if (month, day + 1) in MarketCalendar.FIXED_HOLIDAYS and weekday == 4:  # Friday
            return True, f"{MarketCalendar.FIXED_HOLIDAYS[(month, day + 1)]} (observed)"

        # Floating holidays
        if month == 1 and 15 <= day <= 21 and weekday == 0:  # 3rd Monday
            return True, "Martin Luther King Jr. Day"

        if month == 2 and 15 <= day <= 21 and weekday == 0:  # 3rd Monday
            return True, "Presidents' Day"

        if month == 5 and day >= 25 and weekday == 0:  # Last Monday
            return True, "Memorial Day"

        if month == 9 and 1 <= day <= 7 and weekday == 0:  # 1st Monday
            return True, "Labor Day"

        if month == 11 and 22 <= day <= 28 and weekday == 3:  # 4th Thursday
            return True, "Thanksgiving"

        # Good Friday: NYSE/Nasdaq close on Good Friday every year.
        # 2026-08-07 fix: the old "month==4 and 15<=day<=22 and weekday==4"
        # approximation only matched Good Fridays that happen to fall in
        # mid-to-late April (true only ~1 year in 6; e.g. 2025-04-18 matched,
        # but 2026-04-03, 2027-03-26, 2028-04-14, 2029-03-30 do NOT and were
        # silently treated as regular trading days). Replaced with an exact
        # Good Friday date (Easter Sunday - 2 days) via the Anonymous
        # Gregorian algorithm, which is a fixed, well-tested date computation
        # (no external dependency needed).
        good_friday = MarketCalendar._good_friday(date.year)
        if date.month == good_friday.month and date.day == good_friday.day:
            return True, "Good Friday"

        return False, ""

    @staticmethod
    def _good_friday(year: int) -> "datetime.date":
        """Return the date of Good Friday (Easter Sunday - 2 days) for *year*.

        Uses the Anonymous Gregorian algorithm (a.k.a. Meeus/Jones/Butcher
        algorithm) to compute Easter Sunday, which is exact for the Gregorian
        calendar (valid for any year >= 1583). Good Friday is always exactly
        2 days before Easter Sunday.
        """
        from datetime import date as _date

        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        easter_sunday = _date(year, month, day)
        return easter_sunday - timedelta(days=2)

    @staticmethod
    def is_daylight_saving_time(date: datetime) -> bool:
        """Check if date is in Daylight Saving Time period.

        DST in US: 2nd Sunday of March to 1st Sunday of November

        Args:
            date: Date to check

        Returns:
            True if in DST period
        """
        et_tz = ZoneInfo("America/New_York")
        dt_et = date.astimezone(et_tz)
        return bool(dt_et.dst())

    @staticmethod
    def get_et_offset_hours(date: datetime) -> int:
        """Get ET to JST offset in hours.

        Args:
            date: Date to check

        Returns:
            Offset in hours (13 during DST, 14 otherwise)
        """
        return 13 if MarketCalendar.is_daylight_saving_time(date) else 14

    @staticmethod
    def get_market_hours_jst(date: datetime) -> Dict[str, Tuple[time, time]]:
        """Get market hours in JST for given date.

        Args:
            date: Date to get market hours for

        Returns:
            Dictionary with pre_market, regular, after_hours as (start, end) tuples
        """
        offset = MarketCalendar.get_et_offset_hours(date)

        def add_hours_to_time(t: time, hours: int) -> time:
            """Add hours to time, handling day rollover."""
            dt = datetime.combine(datetime.today(), t) + timedelta(hours=hours)
            return dt.time()

        return {
            "pre_market": (
                add_hours_to_time(MarketCalendar.PRE_MARKET_START, offset),
                add_hours_to_time(MarketCalendar.PRE_MARKET_END, offset),
            ),
            "regular": (
                add_hours_to_time(MarketCalendar.REGULAR_START, offset),
                add_hours_to_time(MarketCalendar.REGULAR_END, offset),
            ),
            "after_hours": (
                add_hours_to_time(MarketCalendar.AFTER_HOURS_START, offset),
                add_hours_to_time(MarketCalendar.AFTER_HOURS_END, offset),
            ),
        }

    @staticmethod
    def is_regular_market_hours(dt: datetime = None) -> Tuple[bool, str]:
        """Check if US market is in REGULAR trading hours (9:30–16:00 ET).

        Unlike is_market_open(), this returns False during pre-market and
        after-hours sessions.  Use this to gate new buy-order submission:
        market orders with extended_hours=False cannot fill outside regular
        hours, so submitting them then just creates phantom accepted orders
        that carry over to the next session.

        Args:
            dt: DateTime to check (defaults to now in Asia/Tokyo)

        Returns:
            Tuple of (is_regular, status_message)
        """
        if dt is None:
            dt = datetime.now(ZoneInfo("Asia/Tokyo"))

        # Weekend/holiday check uses ET (America/New_York): the US market calendar
        # is defined in ET, not JST.  US Friday afternoon (15:55-19:55 UTC) is
        # JST Saturday morning — using JST here caused Friday crons to be skipped.
        # Bug fixed 2026-07-25 (root cause: 2026-07-24 US Friday cron skip incident).
        et_tz = ZoneInfo("America/New_York")
        dt_et = dt.astimezone(et_tz) if dt.tzinfo is not None else dt

        is_holiday, holiday_name = MarketCalendar.is_us_holiday(dt_et)
        if is_holiday:
            return False, f"Regular market closed: {holiday_name}"

        if dt_et.weekday() >= 5:
            return False, "Regular market closed: Weekend"

        # Time comparison uses JST so dt_jst.time() is comparable with
        # get_market_hours_jst() output (which expresses ET hours in JST).
        jst = ZoneInfo("Asia/Tokyo")
        dt_jst = dt.astimezone(jst) if dt.tzinfo is not None else dt

        market_hours = MarketCalendar.get_market_hours_jst(dt_jst)
        current_time = dt_jst.time()
        regular_start, regular_end = market_hours["regular"]
        # JST regular hours wrap midnight (e.g., 22:30–05:00).
        # When end < start we must use OR logic instead of AND.
        if regular_end < regular_start:
            # wraps midnight: open if current >= start OR current < end
            in_regular = current_time >= regular_start or current_time < regular_end
        else:
            in_regular = regular_start <= current_time < regular_end

        if in_regular:
            return True, "Regular market open (9:30–16:00 ET)"

        return False, "Regular market closed (pre-market or after-hours)"

    @staticmethod
    def is_market_open(dt: datetime = None) -> Tuple[bool, str]:
        """Check if US market is currently open.

        Args:
            dt: DateTime to check (defaults to now)

        Returns:
            Tuple of (is_open, status_message)
        """
        if dt is None:
            dt = datetime.now(ZoneInfo("Asia/Tokyo"))

        # Weekend/holiday check uses ET (America/New_York).
        # US Friday afternoon (15:55-19:55 UTC) is JST Saturday morning;
        # using the raw dt timezone for weekday() caused Friday crons to
        # be skipped.  Bug fixed 2026-07-25.
        et_tz = ZoneInfo("America/New_York")
        dt_et = dt.astimezone(et_tz) if dt.tzinfo is not None else dt

        # Check if holiday (use ET calendar date)
        is_holiday, holiday_name = MarketCalendar.is_us_holiday(dt_et)
        if is_holiday:
            return False, f"Market closed: {holiday_name}"

        # Check if weekend (use ET calendar date)
        if dt_et.weekday() >= 5:  # Saturday=5, Sunday=6
            return False, "Market closed: Weekend"

        # Time comparison: convert to JST so dt_jst.time() is comparable with
        # get_market_hours_jst() output (which expresses ET hours in JST offsets).
        jst = ZoneInfo("Asia/Tokyo")
        dt_jst = dt.astimezone(jst) if dt.tzinfo is not None else dt
        market_hours = MarketCalendar.get_market_hours_jst(dt_jst)
        current_time = dt_jst.time()

        def _in_window(start: time, end: time) -> bool:
            if end < start:
                return current_time >= start or current_time < end
            return start <= current_time < end

        # Check regular hours
        regular_start, regular_end = market_hours["regular"]
        if _in_window(regular_start, regular_end):
            return True, "Market open: Regular hours"

        # Check pre-market
        pre_start, pre_end = market_hours["pre_market"]
        if _in_window(pre_start, pre_end):
            return True, "Market open: Pre-market"

        # Check after-hours
        after_start, after_end = market_hours["after_hours"]
        if _in_window(after_start, after_end):
            return True, "Market open: After-hours"

        return False, "Market closed: Outside trading hours"


# Convenience functions
def is_market_open(dt: datetime = None) -> bool:
    """Check if market is open (convenience function)."""
    is_open, _ = MarketCalendar.is_market_open(dt)
    return is_open


def is_regular_market_hours(dt: datetime = None) -> bool:
    """Check if market is in regular hours 9:30–16:00 ET (convenience function)."""
    is_regular, _ = MarketCalendar.is_regular_market_hours(dt)
    return is_regular


def is_us_holiday(date: datetime = None) -> bool:
    """Check if date is US holiday (convenience function)."""
    if date is None:
        date = datetime.now()
    is_holiday, _ = MarketCalendar.is_us_holiday(date)
    return is_holiday


def get_market_hours(date: datetime = None) -> Dict[str, Tuple[time, time]]:
    """Get market hours in JST (convenience function)."""
    if date is None:
        date = datetime.now()
    return MarketCalendar.get_market_hours_jst(date)


def is_daylight_saving_time(date: datetime = None) -> bool:
    """Check if date is in DST (convenience function)."""
    if date is None:
        date = datetime.now()
    return MarketCalendar.is_daylight_saving_time(date)
