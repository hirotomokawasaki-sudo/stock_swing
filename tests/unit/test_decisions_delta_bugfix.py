"""Tests for the decisions_vs_prev_snapshot delta bug fix (2026-08-13).

Background: dashboard_service.get_deltas() computed:
    decisions_now = <cumulative file count in data/decisions/>
    decisions_prev = max(0, decisions_now - latest_signals)
    decisions_vs_prev_snapshot = decisions_now - decisions_prev

Algebraically this collapses to just `latest_signals` -- a number with no
relationship to the actual decision count delta. Confirmed against real
data: filename-derived decision counts went 51 -> 64 across two days (a
real delta of +13), while the old formula only ever surfaced the current
run's signal-generated count (e.g. 21), regardless of how many decisions
were actually produced.

Fix: DailySnapshot now records decisions_generated per run (analogous to
signals_generated/orders_submitted); get_deltas() diffs that field directly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from console.services.dashboard_service import DashboardService
from stock_swing.tracking.pnl_tracker import PnLTracker


class _StubService(DashboardService):
    def __init__(self, project_root: Path) -> None:  # type: ignore[override]
        self.project_root = project_root
        self._broker = None
        self._tracker = None


def _make_tracker(tmp_path: Path) -> PnLTracker:
    return PnLTracker(project_root=tmp_path)


class TestRecordDailySnapshotDecisionsGenerated:
    def test_records_decisions_generated_count(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        snap = tracker.record_daily_snapshot(equity=1_000_000.0, decisions_generated=64)
        assert snap.decisions_generated == 64

    def test_defaults_to_zero_when_not_passed(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        snap = tracker.record_daily_snapshot(equity=1_000_000.0)
        assert snap.decisions_generated == 0

    def test_persisted_and_reloadable(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.record_daily_snapshot(equity=1_000_000.0, decisions_generated=51)

        reloaded = PnLTracker(project_root=tmp_path)
        assert reloaded.state.daily_snapshots[0]["decisions_generated"] == 51


class TestGetDeltasDecisionsVsPrevSnapshot:
    def test_computes_real_delta_between_consecutive_runs(self, tmp_path):
        svc = _StubService(tmp_path)
        trading = {
            "daily_snapshots": [
                {"date": "2026-08-11", "decisions_generated": 51},
                {"date": "2026-08-12", "decisions_generated": 64},
            ],
            "summary": {},
        }
        deltas = svc.get_deltas(trading=trading, positions={"summary": {}})
        assert deltas["decisions_vs_prev_snapshot"] == 13

    def test_does_not_use_signals_generated_as_a_stand_in(self, tmp_path):
        # Regression guard: even if signals_generated is present and very
        # different from any sane decisions delta, it must not leak into
        # decisions_vs_prev_snapshot.
        svc = _StubService(tmp_path)
        trading = {
            "daily_snapshots": [
                {"date": "2026-08-11", "decisions_generated": 51, "signals_generated": 999},
                {"date": "2026-08-12", "decisions_generated": 64, "signals_generated": 21},
            ],
            "summary": {},
        }
        deltas = svc.get_deltas(trading=trading, positions={"summary": {}})
        assert deltas["decisions_vs_prev_snapshot"] == 13
        assert deltas["decisions_vs_prev_snapshot"] != 21
        assert deltas["decisions_vs_prev_snapshot"] != 999

    def test_negative_delta_when_decisions_drop(self, tmp_path):
        svc = _StubService(tmp_path)
        trading = {
            "daily_snapshots": [
                {"date": "2026-08-11", "decisions_generated": 80},
                {"date": "2026-08-12", "decisions_generated": 64},
            ],
            "summary": {},
        }
        deltas = svc.get_deltas(trading=trading, positions={"summary": {}})
        assert deltas["decisions_vs_prev_snapshot"] == -16

    def test_missing_field_on_older_snapshots_returns_none_not_fabricated(self, tmp_path):
        # Pre-fix snapshots have no decisions_generated key at all.
        svc = _StubService(tmp_path)
        trading = {
            "daily_snapshots": [
                {"date": "2026-08-11", "signals_generated": 18},  # no decisions_generated
                {"date": "2026-08-12", "decisions_generated": 64},
            ],
            "summary": {},
        }
        deltas = svc.get_deltas(trading=trading, positions={"summary": {}})
        assert deltas["decisions_vs_prev_snapshot"] is None

    def test_single_snapshot_returns_none(self, tmp_path):
        svc = _StubService(tmp_path)
        trading = {
            "daily_snapshots": [{"date": "2026-08-12", "decisions_generated": 64}],
            "summary": {},
        }
        deltas = svc.get_deltas(trading=trading, positions={"summary": {}})
        assert deltas["decisions_vs_prev_snapshot"] is None

    def test_no_snapshots_returns_none(self, tmp_path):
        svc = _StubService(tmp_path)
        trading = {"daily_snapshots": [], "summary": {}}
        deltas = svc.get_deltas(trading=trading, positions={"summary": {}})
        assert deltas["decisions_vs_prev_snapshot"] is None
