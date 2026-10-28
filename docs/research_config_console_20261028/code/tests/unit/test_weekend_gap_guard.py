from datetime import UTC, datetime
from unittest.mock import patch

from stock_swing.risk.weekend_gap_guard import (
    ZoneInfoNotFoundError,
    get_us_eastern_tz,
    is_weekend_gap_window,
    to_us_eastern,
)


def test_to_us_eastern_uses_dst_in_summer():
    eastern = to_us_eastern(datetime(2026, 6, 1, 14, 0, tzinfo=UTC))
    assert eastern.utcoffset().total_seconds() == -4 * 3600


def test_to_us_eastern_uses_standard_time_in_winter():
    eastern = to_us_eastern(datetime(2026, 1, 5, 15, 0, tzinfo=UTC))
    assert eastern.utcoffset().total_seconds() == -5 * 3600


def test_get_us_eastern_tz_falls_back_when_zoneinfo_missing():
    with patch("stock_swing.risk.weekend_gap_guard.ZoneInfo", side_effect=ZoneInfoNotFoundError("missing")):
        eastern_tz = get_us_eastern_tz()
    converted = datetime(2026, 7, 1, 14, 0, tzinfo=UTC).astimezone(eastern_tz)
    assert converted.utcoffset().total_seconds() == -4 * 3600


def test_is_weekend_gap_window_true_over_weekend():
    assert is_weekend_gap_window(datetime(2026, 6, 7, 16, 0, tzinfo=UTC)) is True


def test_is_weekend_gap_window_false_after_monday_open():
    assert is_weekend_gap_window(datetime(2026, 6, 8, 14, 30, tzinfo=UTC)) is False
