"""Tests for _filter_by_period / _keep_recent_calendar_days calendar-date fix
(bug fix 2026-08-13).

Background: _filter_by_period previously sliced by *record count*
(snapshots[-30:] for 'month', etc.), but daily_snapshots can contain
multiple records per calendar day (one per paper_demo run --
premarket/open/midday/close, observed up to 8/day in practice). On busy
days the last-30-records window could span as little as ~8-11 calendar
days instead of 30, silently shrinking the Alpha/Beta/Sharpe calculation
window (and any other period-filtered view) and making short-window
statistics like Sharpe wildly unstable.

get_trading() also pre-truncated daily_snapshots to the last 30 *records*
before any period filtering could even see the rest of history, compounding
the bug; this is now _keep_recent_calendar_days keeping up to 90 calendar
days (bounded by a record-count safety cap) instead.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from console.services.dashboard_service import DashboardService


class _StubService(DashboardService):
    def __init__(self, project_root: Path) -> None:  # type: ignore[override]
        self.project_root = project_root
        self._broker = None
        self._tracker = None


def _multi_run_snapshots(dates_and_run_counts: list[tuple[str, int]]) -> list[dict]:
    """Build synthetic daily_snapshots with N records per date, simulating
    multiple paper_demo runs landing on the same calendar day."""
    snaps = []
    equity = 1_000_000.0
    for date, run_count in dates_and_run_counts:
        for _ in range(run_count):
            equity += 100.0
            snaps.append({"date": date, "equity": equity})
    return snaps


class TestFilterByPeriodCalendarDays:
    def test_month_covers_30_calendar_days_even_with_multiple_runs_per_day(self, tmp_path):
        svc = _StubService(tmp_path)
        # 40 calendar days, 4 runs/day = 160 records. A record-count slice of
        # [-30:] would only cover the last ~7.5 calendar days; the fix must
        # cover up to 30 calendar days regardless of run density.
        dates = [f"2026-07-{d:02d}" for d in range(1, 32)] + [f"2026-08-{d:02d}" for d in range(1, 10)]
        snaps = _multi_run_snapshots([(d, 4) for d in dates])

        filtered = svc._filter_by_period(snaps, "month")
        covered_dates = sorted({s["date"] for s in filtered})

        assert len(covered_dates) == 30
        assert covered_dates[-1] == "2026-08-09"
        assert covered_dates[0] == "2026-07-11"

    def test_week_covers_7_calendar_days_regardless_of_run_density(self, tmp_path):
        svc = _StubService(tmp_path)
        dates = [f"2026-08-{d:02d}" for d in range(1, 14)]
        snaps = _multi_run_snapshots([(d, 8) for d in dates])  # 8 runs/day, worst observed case

        filtered = svc._filter_by_period(snaps, "week")
        covered_dates = sorted({s["date"] for s in filtered})

        assert len(covered_dates) == 7
        assert covered_dates == [f"2026-08-{d:02d}" for d in range(7, 14)]

    def test_day_returns_only_latest_calendar_day_all_its_runs(self, tmp_path):
        svc = _StubService(tmp_path)
        snaps = _multi_run_snapshots([("2026-08-11", 3), ("2026-08-12", 5)])

        filtered = svc._filter_by_period(snaps, "day")

        assert {s["date"] for s in filtered} == {"2026-08-12"}
        assert len(filtered) == 5

    def test_all_returns_everything_unfiltered(self, tmp_path):
        svc = _StubService(tmp_path)
        snaps = _multi_run_snapshots([("2026-08-01", 2), ("2026-08-02", 3)])

        filtered = svc._filter_by_period(snaps, "all")

        assert filtered == snaps

    def test_fewer_calendar_days_than_period_returns_all_available(self, tmp_path):
        svc = _StubService(tmp_path)
        snaps = _multi_run_snapshots([("2026-08-01", 1), ("2026-08-02", 1)])

        filtered = svc._filter_by_period(snaps, "month")

        assert len(filtered) == 2

    def test_empty_snapshots_returns_empty(self, tmp_path):
        svc = _StubService(tmp_path)
        assert svc._filter_by_period([], "month") == []

    def test_snapshots_missing_date_field_are_skipped_not_crashed(self, tmp_path):
        svc = _StubService(tmp_path)
        snaps = [
            {"date": "2026-08-01", "equity": 1000.0},
            {"equity": 1001.0},  # no date
            {"date": "2026-08-02", "equity": 1002.0},
        ]
        filtered = svc._filter_by_period(snaps, "month")
        assert len(filtered) == 2


class TestKeepRecentCalendarDays:
    def test_keeps_records_within_window_regardless_of_run_density(self, tmp_path):
        svc = _StubService(tmp_path)
        dates = [f"2026-08-{d:02d}" for d in range(1, 14)]
        snaps = _multi_run_snapshots([(d, 8) for d in dates])

        kept = svc._keep_recent_calendar_days(snaps, days=7)
        covered_dates = sorted({s["date"] for s in kept})

        assert len(covered_dates) == 7
        assert covered_dates == [f"2026-08-{d:02d}" for d in range(7, 14)]

    def test_respects_max_records_safety_cap(self, tmp_path):
        svc = _StubService(tmp_path)
        dates = [f"2026-08-{d:02d}" for d in range(1, 14)]
        snaps = _multi_run_snapshots([(d, 8) for d in dates])  # 104 records total

        kept = svc._keep_recent_calendar_days(snaps, days=90, max_records=10)

        assert len(kept) == 10
        # Must keep the most recent records, not the oldest.
        assert kept[-1]["date"] == "2026-08-13"

    def test_empty_input_returns_empty(self, tmp_path):
        svc = _StubService(tmp_path)
        assert svc._keep_recent_calendar_days([], days=30) == []

    def test_no_max_records_returns_all_within_window(self, tmp_path):
        svc = _StubService(tmp_path)
        snaps = _multi_run_snapshots([("2026-08-01", 2), ("2026-08-02", 3)])
        kept = svc._keep_recent_calendar_days(snaps, days=30)
        assert len(kept) == 5


class TestGetTradingDailySnapshotsCalendarWindow:
    """End-to-end regression: get_trading() must not silently shrink history
    to fewer calendar days than intended just because runs are dense."""

    def test_month_period_alpha_uses_a_real_30_day_window_not_8_days(self, tmp_path):
        # Reproduces the exact regression: 40 days of history at multiple
        # runs/day previously made 'month' collapse to ~8 calendar days
        # after get_trading()'s [-30:] record slice; now it should cover a
        # genuinely wide multi-week window (bounded correctly at 30 days by
        # _filter_by_period, but not pre-truncated to a handful of days by
        # get_trading's storage-side cap).
        svc = _StubService(tmp_path)
        dates = [f"2026-07-{d:02d}" for d in range(1, 32)] + [f"2026-08-{d:02d}" for d in range(1, 10)]
        snaps = _multi_run_snapshots([(d, 5) for d in dates])

        # Simulate what get_trading() does to daily_snapshots before storing.
        stored = svc._keep_recent_calendar_days(snaps, days=90, max_records=2000)
        covered_dates = sorted({s["date"] for s in stored})

        # All 40 calendar days should survive the storage-side cap (well
        # under the 90-day/2000-record limits), leaving _filter_by_period
        # free to select a genuine 30-day window from full history.
        assert len(covered_dates) == 40

        filtered = svc._filter_by_period(stored, "month")
        filtered_dates = sorted({s["date"] for s in filtered})
        assert len(filtered_dates) == 30
