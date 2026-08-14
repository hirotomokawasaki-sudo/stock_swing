"""R7-v2 / H8: Market guard – non-market day early exit tests.

Validates that:
  - is_us_trading_day() correctly identifies weekdays / weekends / holidays
  - should_skip_non_market_day() returns skip=True on non-market days
  - STOCK_SWING_FORCE_MARKET_DAY=true overrides the skip
  - reconcile_orders.py is NOT affected (maintenance job; no guard)

History:
    R7-v2 / H8 (2026-07-23): prevents cron jobs from running full API cycles
    on weekends and US holidays, reducing wasted API calls and log noise.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from stock_swing.utils.market_guard import (
    is_us_trading_day,
    should_skip_non_market_day,
    should_skip_outside_market_hours,
)


JST = ZoneInfo("Asia/Tokyo")


def _jst(year: int, month: int, day: int, hour: int = 20) -> datetime:
    """Create a JST datetime.  Default hour=20 (08:00 UTC, valid for ET weekday checks).

    2026-07-25 note: hour was 12 (noon JST = ~23:00 ET previous day), which
    mapped Sat/Sun JST to Fri/Sat ET and caused weekend tests to fail after
    the ET-based weekday fix.  Changed to 20:00 JST = 11:00 UTC = 07:00 ET,
    which correctly falls on the same calendar day in both JST and ET.
    """
    return datetime(year, month, day, hour, 0, 0, tzinfo=JST)


# ---------------------------------------------------------------------------
# is_us_trading_day
# ---------------------------------------------------------------------------

class TestIsUsTradingDay:
    def test_tuesday_is_trading_day(self) -> None:
        dt = _jst(2026, 7, 21)  # Tuesday
        is_td, reason = is_us_trading_day(dt)
        assert is_td is True
        assert "Trading day" in reason

    def test_saturday_is_not_trading_day(self) -> None:
        dt = _jst(2026, 7, 18)  # Saturday
        is_td, reason = is_us_trading_day(dt)
        assert is_td is False
        assert "Saturday" in reason

    def test_sunday_is_not_trading_day(self) -> None:
        dt = _jst(2026, 7, 19)  # Sunday
        is_td, reason = is_us_trading_day(dt)
        assert is_td is False
        assert "Sunday" in reason

    def test_july_4th_is_holiday(self) -> None:
        """Independence Day – fixed US holiday."""
        dt = _jst(2026, 7, 4)  # Friday Jul 4 2026 (not weekend)
        # Note: check weekday first
        # Jul 4 2026 is a Saturday → already weekend. Use 2025 instead.
        dt2 = _jst(2025, 7, 4)  # Friday
        is_td, reason = is_us_trading_day(dt2)
        assert is_td is False
        assert "Independence Day" in reason

    def test_christmas_is_holiday(self) -> None:
        """Christmas – fixed US holiday."""
        # Dec 25 2025 is Thursday
        dt = _jst(2025, 12, 25)
        is_td, reason = is_us_trading_day(dt)
        assert is_td is False
        assert "Christmas" in reason

    def test_new_years_day_is_holiday(self) -> None:
        dt = _jst(2026, 1, 1)  # Thursday Jan 1 2026
        is_td, reason = is_us_trading_day(dt)
        assert is_td is False
        assert "New Year" in reason

    def test_regular_thursday_is_trading_day(self) -> None:
        dt = _jst(2026, 7, 23)  # Thursday
        is_td, reason = is_us_trading_day(dt)
        assert is_td is True

    def test_defaults_to_now(self) -> None:
        """Calling with no args must not crash."""
        is_td, reason = is_us_trading_day()
        assert isinstance(is_td, bool)
        assert isinstance(reason, str)


# ---------------------------------------------------------------------------
# should_skip_non_market_day
# ---------------------------------------------------------------------------

class TestShouldSkipNonMarketDay:
    def test_skip_on_saturday(self) -> None:
        dt = _jst(2026, 7, 18)  # Saturday
        skip, reason = should_skip_non_market_day(dt)
        assert skip is True
        assert "Saturday" in reason

    def test_no_skip_on_trading_day(self) -> None:
        dt = _jst(2026, 7, 21)  # Tuesday
        skip, reason = should_skip_non_market_day(dt)
        assert skip is False

    def test_force_override_on_weekend(self) -> None:
        """STOCK_SWING_FORCE_MARKET_DAY=true overrides skip on weekend."""
        dt = _jst(2026, 7, 18)  # Saturday
        with patch.dict(os.environ, {"STOCK_SWING_FORCE_MARKET_DAY": "true"}):
            skip, reason = should_skip_non_market_day(dt)
        assert skip is False, "force override must disable skip"
        assert "override" in reason.lower()

    def test_force_override_values(self) -> None:
        """Both '1' and 'true' are accepted as force values."""
        dt = _jst(2026, 7, 18)  # Saturday
        for val in ("true", "1", "True", "TRUE"):
            with patch.dict(os.environ, {"STOCK_SWING_FORCE_MARKET_DAY": val}):
                skip, _ = should_skip_non_market_day(dt)
            assert skip is False, f"STOCK_SWING_FORCE_MARKET_DAY={val!r} must override"

    def test_force_false_does_not_override(self) -> None:
        """Empty / false values do not override."""
        dt = _jst(2026, 7, 18)  # Saturday
        for val in ("false", "0", "", "no"):
            with patch.dict(os.environ, {"STOCK_SWING_FORCE_MARKET_DAY": val}):
                skip, _ = should_skip_non_market_day(dt)
            assert skip is True, f"STOCK_SWING_FORCE_MARKET_DAY={val!r} must not override"

    def test_env_var_absent_uses_calendar(self) -> None:
        """Without env var, normal calendar logic applies."""
        dt = _jst(2026, 7, 18)  # Saturday
        env = {k: v for k, v in os.environ.items() if k != "STOCK_SWING_FORCE_MARKET_DAY"}
        with patch.dict(os.environ, env, clear=True):
            skip, _ = should_skip_non_market_day(dt)
        assert skip is True

    def test_holiday_triggers_skip(self) -> None:
        """US holiday (non-weekend) also triggers skip."""
        dt = _jst(2025, 7, 4)  # Friday – Independence Day
        skip, reason = should_skip_non_market_day(dt)
        assert skip is True
        assert "Independence Day" in reason

    def test_skip_returns_informative_reason(self) -> None:
        """Reason string must be non-empty and human-readable."""
        dt = _jst(2026, 7, 19)  # Saturday
        skip, reason = should_skip_non_market_day(dt)
        assert len(reason) > 10, "reason must be informative"

    def test_regression_paper_demo_cron_skip_on_weekend(self) -> None:
        """Regression: paper_demo cron must not run full cycle on weekends.
        Before R7-v2, the script ran on Saturdays/Sundays burning API credits.
        should_skip_non_market_day() enables early-exit in paper_demo main().
        """
        saturday = _jst(2026, 7, 18)  # Saturday
        sunday = _jst(2026, 7, 19)    # Sunday
        for dt in (saturday, sunday):
            skip, _ = should_skip_non_market_day(dt)
            assert skip is True, f"{dt.strftime('%A')} must trigger skip for paper_demo"


class TestUsFridayAfternoonNotSkipped:
    """Regression tests for the 2026-07-24 US Friday cron skip incident.

    Root cause: is_us_trading_day() and is_regular_market_hours() used the
    JST calendar date for the weekend check.  US Friday afternoon (15:55-19:55
    UTC) fires crons in JST Saturday morning, so they were incorrectly skipped.

    Fix (2026-07-25): use America/New_York for the calendar date in all
    weekend/holiday checks inside market_guard.py and market_calendar.py.

    Incident: 2026-07-24 midday (12:00 ET) and market_close (15:55 ET) crons
    were both skipped, so DDOG / META / MSFT trailing_stop exits were not
    processed despite hitting thresholds during the US trading day.
    """

    # 07-24 19:55 UTC = 15:55 ET Fri = JST 07-25 04:55 Sat
    DT_FRI_CLOSE_UTC = datetime(2026, 7, 24, 19, 55, tzinfo=ZoneInfo("UTC"))
    # 07-24 16:00 UTC = 12:00 ET Fri = JST 07-25 01:00 Sat
    DT_FRI_MIDDAY_UTC = datetime(2026, 7, 24, 16, 0, tzinfo=ZoneInfo("UTC"))

    def test_regression_us_friday_close_not_skipped(self) -> None:
        """
        Regression: 2026-07-24 market_close cron (15:55 ET) must not be skipped.
        Before fix, JST date check saw Saturday → skipped.
        """
        skip, reason = should_skip_non_market_day(self.DT_FRI_CLOSE_UTC)
        assert not skip, (
            f"US Friday 15:55 ET must NOT be skipped; got: {reason!r}\n"
            "Root cause: weekend check was using JST date (Saturday) instead of ET (Friday)"
        )

    def test_regression_us_friday_midday_not_skipped(self) -> None:
        """
        Regression: 2026-07-24 midday cron (12:00 ET) must not be skipped.
        """
        skip, reason = should_skip_non_market_day(self.DT_FRI_MIDDAY_UTC)
        assert not skip, (
            f"US Friday 12:00 ET must NOT be skipped; got: {reason!r}"
        )

    def test_us_friday_close_is_trading_day(self) -> None:
        """is_us_trading_day() must return True for US Friday afternoon."""
        is_td, reason = is_us_trading_day(self.DT_FRI_CLOSE_UTC)
        assert is_td, f"US Friday must be a trading day; got: {reason!r}"
        assert "Fri" in reason or "Friday" in reason.lower() or "2026-07-24" in reason

    def test_is_regular_market_hours_friday_close(self) -> None:
        """is_regular_market_hours() must return True for 15:55 ET Friday."""
        from stock_swing.utils.market_calendar import MarketCalendar
        is_reg, msg = MarketCalendar.is_regular_market_hours(self.DT_FRI_CLOSE_UTC)
        assert is_reg, f"15:55 ET Friday must be regular hours; got: {msg!r}"

    def test_is_regular_market_hours_friday_midday(self) -> None:
        """is_regular_market_hours() must return True for 12:00 ET Friday."""
        from stock_swing.utils.market_calendar import MarketCalendar
        is_reg, msg = MarketCalendar.is_regular_market_hours(self.DT_FRI_MIDDAY_UTC)
        assert is_reg, f"12:00 ET Friday must be regular hours; got: {msg!r}"

    def test_is_market_open_friday_close(self) -> None:
        """is_market_open() must return True for 15:55 ET Friday."""
        from stock_swing.utils.market_calendar import MarketCalendar
        is_open, msg = MarketCalendar.is_market_open(self.DT_FRI_CLOSE_UTC)
        assert is_open, f"15:55 ET Friday market must be open; got: {msg!r}"
        assert "Regular" in msg

    def test_actual_saturday_still_skipped(self) -> None:
        """Genuine Saturday must still be skipped (no regression)."""
        dt_real_sat = datetime(2026, 7, 25, 16, 0, tzinfo=ZoneInfo("UTC"))
        skip, reason = should_skip_non_market_day(dt_real_sat)
        assert skip, f"Actual Saturday must still be skipped; got: {reason!r}"

    def test_actual_sunday_still_skipped(self) -> None:
        """Genuine Sunday must still be skipped."""
        dt_real_sun = datetime(2026, 7, 26, 16, 0, tzinfo=ZoneInfo("UTC"))
        skip, reason = should_skip_non_market_day(dt_real_sun)
        assert skip, f"Actual Sunday must still be skipped; got: {reason!r}"

    def test_monday_morning_et_not_skipped(self) -> None:
        """Monday morning ET (UTC Sunday) must be treated as a trading day."""
        # 2026-07-27 Monday 09:00 ET = 13:00 UTC (Sun JST 22:00)
        dt_mon_morning = datetime(2026, 7, 27, 13, 0, tzinfo=ZoneInfo("UTC"))
        skip, reason = should_skip_non_market_day(dt_mon_morning)
        assert not skip, f"Monday morning ET must not be skipped; got: {reason!r}"


# ---------------------------------------------------------------------------
# should_skip_outside_market_hours (R7-v2, 2026-08-14)
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")


def _et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Build an ET-tz datetime for a fixed 2026 Tuesday-based test week."""
    return datetime(year, month, day, hour, minute, tzinfo=ET)


class TestShouldSkipOutsideMarketHours:
    """A known regular US trading Tuesday: 2026-07-21."""

    TUESDAY = (2026, 7, 21)

    def test_dead_zone_is_skipped(self) -> None:
        """22:00 ET (after after-hours 20:00, before next pre-market 04:00)
        on an otherwise valid trading weekday must be skipped."""
        dt = _et(*self.TUESDAY, 22, 0)
        skip, reason = should_skip_outside_market_hours(dt)
        assert skip is True
        assert "closed" in reason.lower()

    def test_early_morning_dead_zone_is_skipped(self) -> None:
        """02:00 ET (still before 04:00 pre-market start) must be skipped."""
        dt = _et(*self.TUESDAY, 2, 0)
        skip, reason = should_skip_outside_market_hours(dt)
        assert skip is True

    def test_pre_market_not_skipped(self) -> None:
        """06:00 ET (pre-market session, 04:00-09:30) must NOT be skipped."""
        dt = _et(*self.TUESDAY, 6, 0)
        skip, reason = should_skip_outside_market_hours(dt)
        assert skip is False
        assert "open" in reason.lower()

    def test_regular_hours_not_skipped(self) -> None:
        """11:00 ET (regular session) must NOT be skipped."""
        dt = _et(*self.TUESDAY, 11, 0)
        skip, reason = should_skip_outside_market_hours(dt)
        assert skip is False

    def test_after_hours_not_skipped(self) -> None:
        """17:00 ET (after-hours session, 16:00-20:00) must NOT be skipped."""
        dt = _et(*self.TUESDAY, 17, 0)
        skip, reason = should_skip_outside_market_hours(dt)
        assert skip is False

    def test_weekend_is_skipped_even_during_session_hours(self) -> None:
        """Saturday 11:00 ET must be skipped by the weekday check first,
        regardless of what the clock-time session window would say."""
        saturday = _et(2026, 7, 18, 11, 0)
        skip, reason = should_skip_outside_market_hours(saturday)
        assert skip is True
        assert "saturday" in reason.lower()

    def test_holiday_is_skipped(self) -> None:
        """US holiday (non-weekend) must be skipped."""
        dt = _et(2025, 7, 4, 11, 0)  # Independence Day, Friday
        skip, reason = should_skip_outside_market_hours(dt)
        assert skip is True
        assert "independence day" in reason.lower()

    def test_force_override_bypasses_dead_zone_skip(self) -> None:
        """STOCK_SWING_FORCE_MARKET_DAY=true must also override the
        within-day session gate, not just the weekday/holiday gate."""
        dt = _et(*self.TUESDAY, 22, 0)
        with patch.dict(os.environ, {"STOCK_SWING_FORCE_MARKET_DAY": "true"}):
            skip, reason = should_skip_outside_market_hours(dt)
        assert skip is False, "force override must disable dead-zone skip"
        assert "override" in reason.lower()

    def test_force_override_bypasses_weekend_skip(self) -> None:
        saturday = _et(2026, 7, 18, 11, 0)
        with patch.dict(os.environ, {"STOCK_SWING_FORCE_MARKET_DAY": "true"}):
            skip, reason = should_skip_outside_market_hours(saturday)
        assert skip is False

    def test_defaults_to_now_does_not_crash(self) -> None:
        skip, reason = should_skip_outside_market_hours()
        assert isinstance(skip, bool)
        assert isinstance(reason, str)

    def test_dead_zone_boundary_just_before_premarket(self) -> None:
        """03:59 ET must still be skipped (dead zone)."""
        dt = _et(*self.TUESDAY, 3, 59)
        skip, _ = should_skip_outside_market_hours(dt)
        assert skip is True

    def test_pre_market_boundary_exact_start(self) -> None:
        """04:00 ET is exactly pre-market start -- must NOT be skipped."""
        dt = _et(*self.TUESDAY, 4, 0)
        skip, _ = should_skip_outside_market_hours(dt)
        assert skip is False

    def test_after_hours_boundary_exact_end(self) -> None:
        """20:00 ET is exactly after-hours end -- must be skipped (dead zone starts)."""
        dt = _et(*self.TUESDAY, 20, 0)
        skip, _ = should_skip_outside_market_hours(dt)
        assert skip is True
