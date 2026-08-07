"""Tests for MarketCalendar Good Friday holiday detection.

Regression (2026-08-07): the previous approximation
("month==4 and 15<=day<=22 and weekday==4") only matched Good Fridays that
happen to fall in mid-to-late April -- true only ~1 year in 6. NYSE/Nasdaq
close on Good Friday every year regardless of month (it can fall in March
or April depending on Easter). The known miss dates below (2026, 2027,
2028, 2029) were silently treated as regular trading days by the old code,
which could cause paper_demo to run on a day markets are actually closed.

Fixed by computing the exact Good Friday date (Easter Sunday - 2 days) via
the Anonymous Gregorian algorithm.
"""
from __future__ import annotations

from datetime import date, datetime

from stock_swing.utils.market_calendar import MarketCalendar


# Known correct Good Friday dates (independently verified), spanning years
# the old approximation got both right and wrong.
KNOWN_GOOD_FRIDAYS = {
    2024: date(2024, 3, 29),   # old approx: WRONG (March, missed entirely)
    2025: date(2025, 4, 18),   # old approx: happened to be correct
    2026: date(2026, 4, 3),    # old approx: WRONG (April but day=3, outside 15-22 window)
    2027: date(2027, 3, 26),   # old approx: WRONG (March, missed entirely)
    2028: date(2028, 4, 14),   # old approx: WRONG (April but day=14, outside 15-22 window)
    2029: date(2029, 3, 30),   # old approx: WRONG (March, missed entirely)
    2030: date(2030, 4, 19),
}


def test_good_friday_computed_dates_match_known_correct_dates():
    for year, expected in KNOWN_GOOD_FRIDAYS.items():
        computed = MarketCalendar._good_friday(year)
        assert computed == expected, f"year={year}: expected {expected}, got {computed}"


def test_is_us_holiday_flags_good_friday_2026():
    """The actual incident case: 2026 Good Friday (April 3) was previously
    missed entirely because day=3 falls outside the old 15-22 window."""
    is_holiday, name = MarketCalendar.is_us_holiday(datetime(2026, 4, 3))
    assert is_holiday is True
    assert name == "Good Friday"


def test_is_us_holiday_flags_good_friday_2027_march():
    """2027 Good Friday falls in March -- previously always missed since
    the old check only ever looked at month==4."""
    is_holiday, name = MarketCalendar.is_us_holiday(datetime(2027, 3, 26))
    assert is_holiday is True
    assert name == "Good Friday"


def test_is_us_holiday_flags_good_friday_2028():
    is_holiday, name = MarketCalendar.is_us_holiday(datetime(2028, 4, 14))
    assert is_holiday is True
    assert name == "Good Friday"


def test_is_us_holiday_flags_good_friday_2025_still_correct():
    """The one date the old approximation happened to get right must
    still work after the fix (no regression)."""
    is_holiday, name = MarketCalendar.is_us_holiday(datetime(2025, 4, 18))
    assert is_holiday is True
    assert name == "Good Friday"


def test_day_before_good_friday_not_flagged():
    is_holiday, _ = MarketCalendar.is_us_holiday(datetime(2026, 4, 2))
    assert is_holiday is False


def test_day_after_good_friday_not_flagged():
    is_holiday, _ = MarketCalendar.is_us_holiday(datetime(2026, 4, 4))
    assert is_holiday is False


def test_same_month_day_different_year_not_incorrectly_flagged():
    """2026 Good Friday is April 3. A different year's April 3 (not Good
    Friday) must not be flagged just because month/day match some other
    year's holiday."""
    is_holiday, _ = MarketCalendar.is_us_holiday(datetime(2025, 4, 3))
    assert is_holiday is False


def test_is_market_open_returns_false_on_good_friday():
    is_open, status = MarketCalendar.is_market_open(datetime(2026, 4, 3, 12, 0))
    assert is_open is False
    assert "Good Friday" in status
