"""Weekend gap risk helpers with safe US Eastern timezone fallback.

This module intentionally avoids failing at import time when the system
timezone database is missing. It prefers ZoneInfo("America/New_York")
and falls back to a small US Eastern DST implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python 3.11+ ships zoneinfo
    ZoneInfo = None  # type: ignore[assignment]

    class ZoneInfoNotFoundError(Exception):
        pass


class _USEasternFallback(tzinfo):
    """Small DST-aware fallback for America/New_York."""

    @staticmethod
    def _first_sunday(year: int, month: int) -> datetime:
        dt = datetime(year, month, 1)
        days = (6 - dt.weekday()) % 7
        return dt + timedelta(days=days)

    @classmethod
    def _dst_bounds_local(cls, year: int) -> tuple[datetime, datetime]:
        march_first_sunday = cls._first_sunday(year, 3)
        november_first_sunday = cls._first_sunday(year, 11)
        second_sunday_march = march_first_sunday + timedelta(days=7)
        dst_start_local = datetime(year, 3, second_sunday_march.day, 2, 0)
        dst_end_local = datetime(year, 11, november_first_sunday.day, 2, 0)
        return dst_start_local, dst_end_local

    def _is_dst(self, dt: datetime | None) -> bool:
        if dt is None:
            return False
        local_wall = dt.replace(tzinfo=None)
        start, end = self._dst_bounds_local(local_wall.year)
        return start <= local_wall < end

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=-4 if self._is_dst(dt) else -5)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=1 if self._is_dst(dt) else 0)

    def tzname(self, dt: datetime | None) -> str:
        return "EDT" if self._is_dst(dt) else "EST"


def get_us_eastern_tz() -> tzinfo:
    """Return America/New_York or a DST-aware fallback."""
    if ZoneInfo is None:
        return _USEasternFallback()
    try:
        return ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        return _USEasternFallback()


def to_us_eastern(dt: datetime | None = None) -> datetime:
    """Convert a datetime to US Eastern time.

    Naive datetimes are treated as UTC to keep the fallback fail-closed.
    """
    dt = dt or datetime.now(UTC)
    dt_utc = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt_utc.astimezone(get_us_eastern_tz())


def is_weekend_gap_window(now_utc: datetime | None = None) -> bool:
    """Return True between Friday 16:00 ET and Monday 09:30 ET."""
    eastern = to_us_eastern(now_utc)
    weekday = eastern.weekday()  # Monday=0
    hm = (eastern.hour, eastern.minute)

    if weekday == 4:
        return hm >= (16, 0)
    if weekday in {5, 6}:
        return True
    if weekday == 0:
        return hm < (9, 30)
    return False
