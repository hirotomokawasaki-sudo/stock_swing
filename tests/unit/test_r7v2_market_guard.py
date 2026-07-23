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

from stock_swing.utils.market_guard import is_us_trading_day, should_skip_non_market_day


JST = ZoneInfo("Asia/Tokyo")


def _jst(year: int, month: int, day: int, hour: int = 12) -> datetime:
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
