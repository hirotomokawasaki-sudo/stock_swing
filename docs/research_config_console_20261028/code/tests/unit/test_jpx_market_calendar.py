"""Tests for JPXMarketCalendar (2026-08-19, JP semiconductor expansion Phase 2).

See docs/jp_semiconductor_ai_expansion_phase2_design.md section 3-A. This is
a new, independent class from MarketCalendar (NYSE) — these tests verify it
does not interfere with the existing US market calendar and correctly models
JPX-specific holidays/sessions.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from stock_swing.utils.jpx_market_calendar import JPXMarketCalendar

JST = ZoneInfo("Asia/Tokyo")


class TestIsJpHoliday:
    """Acceptance: verify against publicly known Japanese national holidays
    for 2024 and 2025 (independently verifiable calendar facts)."""

    @pytest.mark.parametrize(
        "d,expected_name",
        [
            (date(2024, 1, 1), "元日"),
            (date(2024, 1, 8), "成人の日"),
            (date(2024, 2, 11), "建国記念の日"),
            (date(2024, 2, 12), "振替休日"),  # 2/11 was a Sunday in 2024
            (date(2024, 2, 23), "天皇誕生日"),
            (date(2024, 3, 20), "春分の日"),
            (date(2024, 4, 29), "昭和の日"),
            (date(2024, 5, 3), "憲法記念日"),
            (date(2024, 5, 4), "みどりの日"),
            (date(2024, 5, 5), "こどもの日"),
            (date(2024, 5, 6), "振替休日"),  # 5/5 was a Sunday in 2024
            (date(2024, 7, 15), "海の日"),
            (date(2024, 8, 11), "山の日"),
            (date(2024, 8, 12), "振替休日"),  # 8/11 was a Sunday in 2024
            (date(2024, 9, 16), "敬老の日"),
            (date(2024, 9, 22), "秋分の日"),
            (date(2024, 9, 23), "振替休日"),  # 9/22 was a Sunday in 2024
            (date(2024, 10, 14), "スポーツの日"),
            (date(2024, 11, 3), "文化の日"),
            (date(2024, 11, 4), "振替休日"),  # 11/3 was a Sunday in 2024
            (date(2024, 11, 23), "勤労感謝の日"),
        ],
    )
    def test_2024_holidays(self, d: date, expected_name: str) -> None:
        is_holiday, name = JPXMarketCalendar.is_jp_holiday(d)
        assert is_holiday is True
        assert name == expected_name

    @pytest.mark.parametrize(
        "d,expected_name",
        [
            (date(2025, 1, 1), "元日"),
            (date(2025, 1, 13), "成人の日"),
            (date(2025, 2, 11), "建国記念の日"),
            (date(2025, 2, 23), "天皇誕生日"),
            (date(2025, 2, 24), "振替休日"),  # 2/23 was a Sunday in 2025
            (date(2025, 3, 20), "春分の日"),
            (date(2025, 4, 29), "昭和の日"),
            (date(2025, 5, 3), "憲法記念日"),
            (date(2025, 5, 4), "みどりの日"),
            (date(2025, 5, 5), "こどもの日"),
            # Regression: 5/4 みどりの日 was a Sunday in 2025, but the
            # substitute holiday shifts to 5/6 (not 5/5, since 5/5 is
            # itself a core holiday こどもの日 and the shift must skip past
            # it). This is the exact case the backward-walk substitute
            # holiday algorithm was designed to handle correctly.
            (date(2025, 5, 6), "振替休日"),
            (date(2025, 7, 21), "海の日"),
            (date(2025, 8, 11), "山の日"),
            (date(2025, 9, 15), "敬老の日"),
            (date(2025, 9, 23), "秋分の日"),
            (date(2025, 10, 13), "スポーツの日"),
            (date(2025, 11, 3), "文化の日"),
            (date(2025, 11, 23), "勤労感謝の日"),
            (date(2025, 11, 24), "振替休日"),  # 11/23 was a Sunday in 2025
        ],
    )
    def test_2025_holidays(self, d: date, expected_name: str) -> None:
        is_holiday, name = JPXMarketCalendar.is_jp_holiday(d)
        assert is_holiday is True
        assert name == expected_name

    @pytest.mark.parametrize(
        "d",
        [
            date(2025, 5, 7),   # ordinary weekday right after Golden Week
            date(2024, 5, 7),
            date(2025, 1, 14),  # day after 成人の日
            date(2025, 3, 21),  # day after 春分の日
            date(2026, 8, 19),  # today (arbitrary ordinary Wednesday)
        ],
    )
    def test_ordinary_weekdays_are_not_holidays(self, d: date) -> None:
        is_holiday, _ = JPXMarketCalendar.is_jp_holiday(d)
        assert is_holiday is False

    def test_year_end_new_year_closure(self) -> None:
        """JPX closes 12/31-1/3 regardless of weekday (bank holiday
        convention), distinct from the 元日 national holiday on 1/1."""
        is_holiday, name = JPXMarketCalendar.is_jp_holiday(date(2025, 12, 31))
        assert is_holiday is True
        assert name == "年末年始休場"

        is_holiday, _ = JPXMarketCalendar.is_jp_holiday(date(2025, 1, 2))
        assert is_holiday is True

        is_holiday, _ = JPXMarketCalendar.is_jp_holiday(date(2025, 1, 3))
        assert is_holiday is True


class TestIsTradingDay:
    def test_weekend_is_not_trading_day(self) -> None:
        # 2026-08-15 is a Saturday
        is_trading, reason = JPXMarketCalendar.is_trading_day(date(2026, 8, 15))
        assert is_trading is False
        assert "Weekend" in reason

    def test_holiday_is_not_trading_day(self) -> None:
        is_trading, reason = JPXMarketCalendar.is_trading_day(date(2025, 1, 1))
        assert is_trading is False
        assert "元日" in reason

    def test_ordinary_weekday_is_trading_day(self) -> None:
        # 2026-08-19 is a Wednesday, not a holiday
        is_trading, reason = JPXMarketCalendar.is_trading_day(date(2026, 8, 19))
        assert is_trading is True

    def test_accepts_datetime_not_just_date(self) -> None:
        """Boundary: is_trading_day must accept a full datetime (using only
        its calendar date), not just a bare date object."""
        dt = datetime(2026, 8, 19, 10, 30, tzinfo=JST)
        is_trading, _ = JPXMarketCalendar.is_trading_day(dt)
        assert is_trading is True


class TestIsRegularSessionHours:
    @pytest.mark.parametrize(
        "hour,minute,expected_open,note",
        [
            (9, 0, True, "前場 open"),
            (9, 30, True, "前場 mid"),
            (11, 29, True, "前場 last minute"),
            (11, 30, False, "lunch break starts"),
            (12, 0, False, "lunch break mid"),
            (12, 30, True, "後場 open"),
            (14, 59, True, "後場 last minute"),
            (15, 0, False, "後場 closed"),
            (8, 59, False, "before open"),
            (16, 0, False, "after close"),
        ],
    )
    def test_session_boundaries_on_ordinary_weekday(
        self, hour: int, minute: int, expected_open: bool, note: str
    ) -> None:
        # 2026-08-19 is an ordinary Wednesday (not a holiday)
        dt = datetime(2026, 8, 19, hour, minute, tzinfo=JST)
        is_open, _ = JPXMarketCalendar.is_regular_session_hours(dt)
        assert is_open == expected_open, f"{note}: expected {expected_open}, got {is_open}"

    def test_weekend_is_closed_even_during_session_hours(self) -> None:
        # 2026-08-15 is a Saturday
        dt = datetime(2026, 8, 15, 10, 0, tzinfo=JST)
        is_open, reason = JPXMarketCalendar.is_regular_session_hours(dt)
        assert is_open is False
        assert "Weekend" in reason

    def test_holiday_is_closed_even_during_session_hours(self) -> None:
        dt = datetime(2025, 5, 5, 10, 0, tzinfo=JST)  # こどもの日
        is_open, reason = JPXMarketCalendar.is_regular_session_hours(dt)
        assert is_open is False
        assert "こどもの日" in reason

    def test_naive_datetime_is_treated_as_jst(self) -> None:
        """Boundary: a tz-naive datetime must be assumed to already be JST
        (not silently misinterpreted), consistent with MarketCalendar's
        handling of naive datetimes elsewhere in this codebase."""
        dt = datetime(2026, 8, 19, 10, 0)  # naive
        is_open, _ = JPXMarketCalendar.is_regular_session_hours(dt)
        assert is_open is True

    def test_defaults_to_now_when_dt_omitted(self) -> None:
        """Fallback: calling with no argument must not raise."""
        result = JPXMarketCalendar.is_regular_session_hours()
        assert isinstance(result, tuple)
        assert isinstance(result[0], bool)


class TestPreviousTradingCloseJst:
    def test_mid_session_returns_prior_days_close(self) -> None:
        # 2026-08-19 10:00 is mid-morning-session on a Wednesday;
        # today's close (15:00) has not happened yet, so it must return
        # the previous trading day's (2026-08-18, Tuesday) close.
        dt = datetime(2026, 8, 19, 10, 0, tzinfo=JST)
        result = JPXMarketCalendar.previous_trading_close_jst(dt)
        assert result == datetime(2026, 8, 18, 15, 0, tzinfo=JST)

    def test_after_close_returns_todays_close(self) -> None:
        dt = datetime(2026, 8, 19, 16, 0, tzinfo=JST)
        result = JPXMarketCalendar.previous_trading_close_jst(dt)
        assert result == datetime(2026, 8, 19, 15, 0, tzinfo=JST)

    def test_monday_before_open_skips_weekend_to_friday(self) -> None:
        # 2026-08-17 is a Monday; before open should walk back through the
        # weekend to the prior Friday (2026-08-14) close.
        dt = datetime(2026, 8, 17, 8, 0, tzinfo=JST)
        result = JPXMarketCalendar.previous_trading_close_jst(dt)
        assert result == datetime(2026, 8, 14, 15, 0, tzinfo=JST)

    def test_result_is_always_a_trading_day(self) -> None:
        """Acceptance: the returned date must itself be a JPX trading day
        (never a weekend/holiday), for any of several probe dates spanning
        a holiday cluster (Golden Week 2025)."""
        for probe in [
            datetime(2025, 5, 1, 8, 0, tzinfo=JST),
            datetime(2025, 5, 7, 8, 0, tzinfo=JST),
            datetime(2025, 5, 10, 8, 0, tzinfo=JST),
        ]:
            result = JPXMarketCalendar.previous_trading_close_jst(probe)
            is_trading, _ = JPXMarketCalendar.is_trading_day(result.date())
            assert is_trading is True, f"probe={probe} returned non-trading-day close={result}"
