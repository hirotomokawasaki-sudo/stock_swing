"""Tests for MarketCalendar.is_regular_market_hours().

Verifies that new-buy guardrail correctly distinguishes regular trading hours
(9:30-16:00 ET) from pre-market and after-hours sessions.

Background: 2026-06-03 incident where market_close paper_demo run at 20:56 UTC
(4:56 PM ET, after-hours) submitted 27 buy orders that could not fill because
extended_hours=False, creating phantom accepted orders in the broker.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from stock_swing.utils.market_calendar import MarketCalendar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Create a datetime in America/New_York timezone."""
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("America/New_York"))


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Create a datetime in UTC timezone."""
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("UTC"))


# ---------------------------------------------------------------------------
# Regular hours (should return True)
# ---------------------------------------------------------------------------

class TestRegularHoursReturnsTrue:
    def test_regular_market_open_930(self):
        is_regular, _ = MarketCalendar.is_regular_market_hours(_et(2026, 6, 4, 9, 30))
        assert is_regular, "9:30 ET is regular open"

    def test_regular_midday(self):
        is_regular, _ = MarketCalendar.is_regular_market_hours(_et(2026, 6, 4, 12, 0))
        assert is_regular, "12:00 ET is regular hours"

    def test_regular_just_before_close(self):
        is_regular, _ = MarketCalendar.is_regular_market_hours(_et(2026, 6, 4, 15, 59))
        assert is_regular, "15:59 ET is still regular"

    def test_regular_via_utc_midday(self):
        # 19:00 UTC = 15:00 ET (DST)
        is_regular, _ = MarketCalendar.is_regular_market_hours(_utc(2026, 6, 3, 19, 0))
        assert is_regular, "19:00 UTC = 15:00 ET should be regular"

    def test_regular_market_open_run_utc(self):
        # 14:05 UTC = 10:05 ET (DST) — paper_demo market_open run timing
        is_regular, _ = MarketCalendar.is_regular_market_hours(_utc(2026, 6, 3, 14, 5))
        assert is_regular, "14:05 UTC = 10:05 ET should be regular"


# ---------------------------------------------------------------------------
# Non-regular hours (should return False)
# ---------------------------------------------------------------------------

class TestNonRegularHoursReturnsFalse:
    def test_after_hours_1700_et(self):
        """After-hours: 17:00 ET is outside regular."""
        is_regular, _ = MarketCalendar.is_regular_market_hours(_et(2026, 6, 4, 17, 0))
        assert not is_regular

    def test_after_hours_market_close_run(self):
        """2026-06-03 incident: market_close run at 20:56 UTC = 16:56 ET."""
        is_regular, _ = MarketCalendar.is_regular_market_hours(_utc(2026, 6, 3, 20, 56))
        assert not is_regular, "20:56 UTC = 16:56 ET is after-hours, buy must be blocked"

    def test_pre_market_0800_et(self):
        """Pre-market: 08:00 ET should not be regular."""
        is_regular, _ = MarketCalendar.is_regular_market_hours(_et(2026, 6, 4, 8, 0))
        assert not is_regular

    def test_pre_market_0929_et(self):
        """One minute before open is not regular."""
        is_regular, _ = MarketCalendar.is_regular_market_hours(_et(2026, 6, 4, 9, 29))
        assert not is_regular

    def test_exact_close_1600_et(self):
        """16:00 ET is the close tick — no longer regular."""
        is_regular, _ = MarketCalendar.is_regular_market_hours(_et(2026, 6, 4, 16, 0))
        assert not is_regular

    def test_overnight_0300_et(self):
        """03:00 ET (overnight) is not regular."""
        is_regular, _ = MarketCalendar.is_regular_market_hours(_et(2026, 6, 4, 3, 0))
        assert not is_regular

    def test_holiday_juneteenth(self):
        """Juneteenth (June 19) is a market holiday — market is closed regardless of reason."""
        is_regular, _ = MarketCalendar.is_regular_market_hours(_et(2026, 6, 19, 12, 0))
        assert not is_regular  # closed (holiday or JST day-boundary maps to weekend)

    def test_status_message_non_regular(self):
        """Status message should indicate why buy is blocked."""
        is_regular, msg = MarketCalendar.is_regular_market_hours(_et(2026, 6, 4, 17, 0))
        assert not is_regular
        assert msg  # must have a non-empty reason string
