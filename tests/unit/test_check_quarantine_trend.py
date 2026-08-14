"""2026-08-14 (roadmap gap #6): tests for check_quarantine_trend.py.

Roadmap gap analysis found quarantine count (102 as of 2026-08-14) is
displayed in console health output every run, but nothing distinguishes
"new quarantines from ongoing trading" from "the same historical batch
sitting there since 2026-07 ledger repair work". These tests cover
evaluate_trend()'s classification logic (baseline / stable / growing /
decreased) and the new-quarantine detection via newest entry_time
comparison.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_quarantine_trend.py"
_spec = importlib.util.spec_from_file_location("check_quarantine_trend", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["check_quarantine_trend"] = _module
_spec.loader.exec_module(_module)

evaluate_trend = _module.evaluate_trend
load_quarantine_snapshot = _module.load_quarantine_snapshot
load_history = _module.load_history
append_history = _module.append_history


def _snapshot(count: int, newest_entry_time: str | None) -> dict:
    return {
        "checked_at": "2026-08-14T00:00:00Z",
        "quarantine_count": count,
        "newest_quarantined_entry_time": newest_entry_time,
    }


class TestEvaluateTrendNoHistory:
    def test_empty_history_is_baseline(self):
        current = _snapshot(101, "2026-07-22T16:00:27Z")
        result = evaluate_trend(current, [])
        assert result["status"] == "baseline"
        assert result["new_quarantine_detected"] is False


class TestEvaluateTrendStable:
    def test_same_count_and_entry_time_is_stable(self):
        current = _snapshot(101, "2026-07-22T16:00:27Z")
        history = [_snapshot(101, "2026-07-22T16:00:27Z")]
        result = evaluate_trend(current, history)
        assert result["status"] == "stable"
        assert result["count_delta"] == 0
        assert result["new_quarantine_detected"] is False


class TestEvaluateTrendGrowing:
    def test_count_increase_is_growing(self):
        current = _snapshot(105, "2026-07-22T16:00:27Z")
        history = [_snapshot(101, "2026-07-22T16:00:27Z")]
        result = evaluate_trend(current, history)
        assert result["status"] == "growing"
        assert result["count_delta"] == 4
        assert "⚠️" in result["message"]

    def test_newer_entry_time_alone_is_growing_even_if_count_unchanged(self):
        """Regression guard: if a trade were removed and a newer one
        quarantined in the same period keeping count flat, the newest
        entry_time comparison must still catch it -- this is exactly the
        scenario a pure count-based check would miss."""
        current = _snapshot(101, "2026-08-10T12:00:00Z")  # newer than baseline!
        history = [_snapshot(101, "2026-07-22T16:00:27Z")]
        result = evaluate_trend(current, history)
        assert result["status"] == "growing"
        assert result["new_quarantine_detected"] is True

    def test_appearance_of_entry_time_when_previously_none_is_growing(self):
        current = _snapshot(1, "2026-08-10T00:00:00Z")
        history = [_snapshot(0, None)]
        result = evaluate_trend(current, history)
        assert result["new_quarantine_detected"] is True


class TestEvaluateTrendDecreased:
    def test_count_decrease_is_decreased_status(self):
        current = _snapshot(95, "2026-07-22T16:00:27Z")
        history = [_snapshot(101, "2026-07-22T16:00:27Z")]
        result = evaluate_trend(current, history)
        assert result["status"] == "decreased"
        assert result["count_delta"] == -6


class TestEvaluateTrendUsesOnlyMostRecentHistoryEntry:
    def test_compares_against_last_entry_not_first(self):
        current = _snapshot(103, "2026-07-22T16:00:27Z")
        history = [
            _snapshot(90, "2026-07-01T00:00:00Z"),  # older, should be ignored
            _snapshot(101, "2026-07-22T16:00:27Z"),  # most recent, used for comparison
        ]
        result = evaluate_trend(current, history)
        assert result["count_delta"] == 2  # 103 - 101, not 103 - 90


class TestLoadQuarantineSnapshotRealData:
    def test_real_data_returns_valid_shape(self):
        """Sanity check against the actual project pnl_state.json."""
        snapshot = load_quarantine_snapshot()
        assert "quarantine_count" in snapshot
        assert "newest_quarantined_entry_time" in snapshot
        assert isinstance(snapshot["quarantine_count"], int)
        assert snapshot["quarantine_count"] >= 0


class TestHistoryPersistence:
    def test_append_and_load_roundtrip(self, tmp_path, monkeypatch):
        history_path = tmp_path / "quarantine_trend_history.jsonl"
        monkeypatch.setattr(_module, "HISTORY_PATH", history_path)

        assert load_history() == []

        snap1 = _snapshot(101, "2026-07-22T16:00:27Z")
        append_history(snap1)
        assert load_history() == [snap1]

        snap2 = _snapshot(102, "2026-08-01T00:00:00Z")
        append_history(snap2)
        loaded = load_history()
        assert len(loaded) == 2
        assert loaded[-1] == snap2

    def test_load_history_skips_corrupt_lines(self, tmp_path, monkeypatch):
        history_path = tmp_path / "quarantine_trend_history.jsonl"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text("not json\n" + '{"quarantine_count": 101}\n', encoding="utf-8")
        monkeypatch.setattr(_module, "HISTORY_PATH", history_path)

        loaded = load_history()
        assert len(loaded) == 1
        assert loaded[0]["quarantine_count"] == 101

    def test_load_history_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_module, "HISTORY_PATH", tmp_path / "nonexistent.jsonl")
        assert load_history() == []
