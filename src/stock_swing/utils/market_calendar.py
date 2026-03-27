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

        # Good Friday (complex calculation - approximate)
        # TODO: Implement proper Easter calculation if needed
        if month == 4 and 15 <= day <= 22 and weekday == 4:  # Approximate
            return True, "Good Friday (approximate)"

        return False, ""

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
    def is_market_open(dt: datetime = None) -> Tuple[bool, str]:
        """Check if US market is currently open.

        Args:
            dt: DateTime to check (defaults to now)

        Returns:
            Tuple of (is_open, status_message)
        """
        if dt is None:
            dt = datetime.now(ZoneInfo("Asia/Tokyo"))

        # Check if holiday
        is_holiday, holiday_name = MarketCalendar.is_us_holiday(dt)
        if is_holiday:
            return False, f"Market closed: {holiday_name}"

        # Check if weekend
        if dt.weekday() >= 5:  # Saturday=5, Sunday=6
            return False, "Market closed: Weekend"

        # Get market hours in JST
        market_hours = MarketCalendar.get_market_hours_jst(dt)
        current_time = dt.time()

        # Check regular hours
        regular_start, regular_end = market_hours["regular"]
        if regular_start <= current_time < regular_end:
            return True, "Market open: Regular hours"

        # Check pre-market
        pre_start, pre_end = market_hours["pre_market"]
        if pre_start <= current_time < pre_end:
            return True, "Market open: Pre-market"

        # Check after-hours
        after_start, after_end = market_hours["after_hours"]
        if after_start <= current_time < after_end:
            return True, "Market open: After-hours"

        return False, "Market closed: Outside trading hours"


# Convenience functions
def is_market_open(dt: datetime = None) -> bool:
    """Check if market is open (convenience function)."""
    is_open, _ = MarketCalendar.is_market_open(dt)
    return is_open


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
