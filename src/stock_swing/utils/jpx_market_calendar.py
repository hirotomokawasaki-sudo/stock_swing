"""JPX (Tokyo Stock Exchange) market calendar utilities.

New module (2026-08-19, JP semiconductor/AI expansion Phase 2 design —
see docs/jp_semiconductor_ai_expansion_phase2_design.md section 3-A).

This is a **standalone, independent class** from `MarketCalendar`
(stock_swing.utils.market_calendar), which remains NYSE-only and unmodified.
JPXMarketCalendar exists so that a future Phase 3 (post-IBKR-connection)
integration can gate JP order submission the same way MarketCalendar gates
US order submission, without touching any existing US-market code path.

JPX-specific characteristics handled here (vs. NYSE in MarketCalendar):
  - Japanese national holidays (内閣府 "国民の祝日") + year-end/New Year bank
    holidays (12/31-1/3), which do not follow the US holiday calendar at all.
  - Trading sessions: 前場 (morning session) 9:00-11:30 JST,
    午後 (afternoon session) 12:30-15:00 JST, with a lunch break in between
    (NYSE has no equivalent midday closure).
  - No US-style DST/ET-JST timezone conversion is needed: JPX is always
    quoted and traded in JST, so this class works entirely in JST.

No external dependency (e.g. `jpholiday`) is introduced, following the same
"exact date computation, no external dependency" philosophy as
`MarketCalendar._good_friday()`. Floating holidays (Happy Monday System)
are computed directly; a small set of irregular holidays (e.g. the Emperor's
enthronement day observed once in 2019, or holidays shifted for the Tokyo
2020 Olympics) are NOT modeled here since they fall outside the trading
history / forward-looking window this system cares about. If historical
backtests ever need those years, extend HISTORICAL_IRREGULAR_HOLIDAYS below.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Tuple
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


class JPXMarketCalendar:
    """Tokyo Stock Exchange (JPX) market calendar with holiday support.

    All datetime handling in this class assumes/produces JST. Unlike
    MarketCalendar (NYSE), there is no separate "exchange timezone" to
    convert to/from — JPX trades in JST natively.
    """

    # Fixed-date Japanese national holidays (month, day) -> name
    FIXED_HOLIDAYS = {
        (1, 1): "元日",
        (2, 11): "建国記念の日",
        (2, 23): "天皇誕生日",
        (4, 29): "昭和の日",
        (5, 3): "憲法記念日",
        (5, 4): "みどりの日",
        (5, 5): "こどもの日",
        (8, 11): "山の日",
        (11, 3): "文化の日",
        (11, 23): "勤労感謝の日",
    }

    # Bank/exchange year-end and New Year holidays (JPX does not trade these
    # days even though they are not all "国民の祝日").
    YEAR_END_NEW_YEAR = {(12, 31), (1, 2), (1, 3)}
    # Note: (1, 1) is already in FIXED_HOLIDAYS as 元日.

    # Trading session hours (JST)
    MORNING_SESSION_START = time(9, 0)
    MORNING_SESSION_END = time(11, 30)
    LUNCH_BREAK_START = time(11, 30)
    LUNCH_BREAK_END = time(12, 30)
    AFTERNOON_SESSION_START = time(12, 30)
    AFTERNOON_SESSION_END = time(15, 0)

    # Known irregular holidays outside the Happy-Monday/fixed-date rules,
    # for years actually covered by this system's trading history. Extend
    # this set if backtests reach further back or the government announces
    # a one-off holiday (e.g. a royal ceremony day).
    HISTORICAL_IRREGULAR_HOLIDAYS: dict[Tuple[int, int, int], str] = {
        # (year, month, day): name
        (2019, 5, 1): "天皇の即位の日（一代限り）",
        (2019, 10, 22): "即位礼正殿の儀（一代限り）",
    }

    @staticmethod
    def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
        """Return the date of the n-th occurrence of `weekday` in `month`.

        weekday: 0=Monday ... 6=Sunday (Python's date.weekday() convention).
        n: 1-indexed (1 = first occurrence).
        """
        d = date(year, month, 1)
        offset = (weekday - d.weekday()) % 7
        first_occurrence = d + timedelta(days=offset)
        return first_occurrence + timedelta(days=7 * (n - 1))

    @classmethod
    def _happy_monday_holidays(cls, year: int) -> dict[Tuple[int, int], str]:
        """Compute the "ハッピーマンデー" (Happy Monday System) floating
        holidays for a given year: 成人の日 (2nd Mon of Jan), 海の日 (3rd Mon
        of Jul), 敬老の日 (3rd Mon of Sep), スポーツの日 (2nd Mon of Oct).
        """
        seijin = cls._nth_weekday_of_month(year, 1, 0, 2)
        umi = cls._nth_weekday_of_month(year, 7, 0, 3)
        keiro = cls._nth_weekday_of_month(year, 9, 0, 3)
        sports = cls._nth_weekday_of_month(year, 10, 0, 2)
        return {
            (seijin.month, seijin.day): "成人の日",
            (umi.month, umi.day): "海の日",
            (keiro.month, keiro.day): "敬老の日",
            (sports.month, sports.day): "スポーツの日",
        }

    @classmethod
    def _shubun_no_hi(cls, year: int) -> date:
        """秋分の日 (Autumnal Equinox Day). Approximation valid for the
        Gregorian-calendar range relevant to this system (2000-2099):
        day = floor(23.2488 + 0.242194 * (year - 1980) - floor((year - 1980) / 4)).
        This is the standard approximation formula used by the Japanese
        government's National Astronomical Observatory publications.
        """
        import math

        day = math.floor(23.2488 + 0.242194 * (year - 1980) - math.floor((year - 1980) / 4))
        return date(year, 9, day)

    @classmethod
    def _shunbun_no_hi(cls, year: int) -> date:
        """春分の日 (Vernal Equinox Day). Same approximation family as
        _shubun_no_hi, valid for 2000-2099.
        """
        import math

        day = math.floor(20.8431 + 0.242194 * (year - 1980) - math.floor((year - 1980) / 4))
        return date(year, 3, day)

    @classmethod
    def _is_core_holiday(cls, d: date) -> Tuple[bool, str]:
        """Check holiday status considering only "core" holidays (fixed-date,
        Happy Monday, equinoxes, historical irregulars) — explicitly
        EXCLUDING 振替休日 (substitute holiday) and 年末年始休場 (year-end/
        New Year closure), since those are derived from core holidays and
        must not be treated as core themselves (would cause incorrect
        chaining in the substitute-holiday walk below).
        """
        month_day = (d.month, d.day)
        year_month_day = (d.year, d.month, d.day)

        if year_month_day in cls.HISTORICAL_IRREGULAR_HOLIDAYS:
            return True, cls.HISTORICAL_IRREGULAR_HOLIDAYS[year_month_day]
        if month_day in cls.FIXED_HOLIDAYS:
            return True, cls.FIXED_HOLIDAYS[month_day]
        happy_monday = cls._happy_monday_holidays(d.year)
        if month_day in happy_monday:
            return True, happy_monday[month_day]
        shunbun = cls._shunbun_no_hi(d.year)
        if d.month == shunbun.month and d.day == shunbun.day:
            return True, "春分の日"
        shubun = cls._shubun_no_hi(d.year)
        if d.month == shubun.month and d.day == shubun.day:
            return True, "秋分の日"
        return False, ""

    @classmethod
    def is_jp_holiday(cls, d: date) -> Tuple[bool, str]:
        """Check if `d` is a Japanese national holiday or JPX year-end/
        New Year non-trading day.

        Args:
            d: date (naive, no timezone needed — this is a calendar-date
               check).

        Returns:
            Tuple of (is_holiday, holiday_name).
        """
        is_core, core_name = cls._is_core_holiday(d)
        if is_core:
            return True, core_name

        month_day = (d.month, d.day)
        if month_day in cls.YEAR_END_NEW_YEAR:
            return True, "年末年始休場"

        # 振替休日 (substitute holiday), per the 2007 amendment to the
        # Public Holidays Act: when a core holiday falls on a Sunday, the
        # nearest following day that is NOT itself a core holiday becomes a
        # substitute holiday. This handles multi-day holiday chains (e.g.
        # 2025 Golden Week: Sun 5/4 みどりの日 -> Mon 5/5 こどもの日 [core,
        # not substitute] -> Tue 5/6 振替休日, since 5/5 was already a core
        # holiday and the shift continues past it).
        #
        # Algorithm: walk backward from d-1 while each day is a core holiday;
        # if that backward walk terminates at a Sunday core holiday (and d
        # itself is not a core holiday, already established above), d is a
        # substitute holiday.
        cursor = d - timedelta(days=1)
        for _ in range(7):  # JP holiday chains never exceed a few days
            is_core_cursor, _ = cls._is_core_holiday(cursor)
            if not is_core_cursor:
                break
            if cursor.weekday() == 6:  # Sunday
                return True, "振替休日"
            cursor = cursor - timedelta(days=1)

        return False, ""

    @classmethod
    def is_trading_day(cls, dt: datetime | date) -> Tuple[bool, str]:
        """Check if `dt` (or the calendar date it falls on) is a JPX trading
        day (i.e. not a weekend, not a holiday).

        Args:
            dt: datetime (any tz, will be treated by calendar date only) or
                a plain date.

        Returns:
            Tuple of (is_trading_day, reason_if_not).
        """
        d = dt.date() if isinstance(dt, datetime) else dt

        if d.weekday() >= 5:
            return False, "JPX closed: Weekend"

        is_holiday, holiday_name = cls.is_jp_holiday(d)
        if is_holiday:
            return False, f"JPX closed: {holiday_name}"

        return True, "JPX trading day"

    @classmethod
    def is_regular_session_hours(cls, dt: datetime | None = None) -> Tuple[bool, str]:
        """Check if JPX is in a regular trading session (前場 or 後場),
        excluding the lunch break, weekends, and holidays.

        Args:
            dt: datetime to check (any tz; converted to JST). Defaults to
                now in JST.

        Returns:
            Tuple of (is_open, status_message).
        """
        if dt is None:
            dt = datetime.now(JST)
        dt_jst = dt.astimezone(JST) if dt.tzinfo is not None else dt.replace(tzinfo=JST)

        is_trading, reason = cls.is_trading_day(dt_jst)
        if not is_trading:
            return False, reason

        current_time = dt_jst.time()

        if cls.MORNING_SESSION_START <= current_time < cls.MORNING_SESSION_END:
            return True, "JPX open: 前場 (morning session)"
        if cls.AFTERNOON_SESSION_START <= current_time < cls.AFTERNOON_SESSION_END:
            return True, "JPX open: 後場 (afternoon session)"
        if cls.LUNCH_BREAK_START <= current_time < cls.LUNCH_BREAK_END:
            return False, "JPX closed: 昼休み (lunch break)"

        return False, "JPX closed: Outside trading hours"

    @classmethod
    def previous_trading_close_jst(
        cls, dt: datetime | None = None, max_lookback_days: int = 10
    ) -> datetime:
        """Return the JST datetime of the most recently *completed* regular
        session close (15:00 JST, 後場 end) at or before `dt`.

        Mirrors MarketCalendar.previous_trading_close_utc()'s purpose but for
        JPX: used to compute daily-bar staleness relative to the last
        confirmed JPX close (needed once JP symbols are wired into any
        source-SLA style health check, per Phase 2 design section 2-A's note
        on JPX/NYSE holiday-calendar asymmetry).

        Args:
            dt: Reference datetime (any tz; converted to JST). Defaults to
                now.
            max_lookback_days: Safety bound for walking back through
                consecutive non-trading days (handles long holiday runs,
                e.g. Golden Week).

        Returns:
            Timezone-aware JST datetime for the 15:00 JST close of the most
            recent JPX trading day whose close has already occurred at `dt`.
        """
        if dt is None:
            dt = datetime.now(JST)
        dt_jst = dt.astimezone(JST) if dt.tzinfo is not None else dt.replace(tzinfo=JST)

        candidate_date = dt_jst.date()
        is_trading, _ = cls.is_trading_day(candidate_date)
        today_close = datetime.combine(candidate_date, cls.AFTERNOON_SESSION_END, tzinfo=JST)
        if not is_trading or dt_jst < today_close:
            candidate_date = candidate_date - timedelta(days=1)

        for _ in range(max_lookback_days):
            is_trading, _ = cls.is_trading_day(candidate_date)
            if is_trading:
                return datetime.combine(candidate_date, cls.AFTERNOON_SESSION_END, tzinfo=JST)
            candidate_date = candidate_date - timedelta(days=1)

        # Fallback: should not happen with a sane max_lookback_days.
        return dt_jst
