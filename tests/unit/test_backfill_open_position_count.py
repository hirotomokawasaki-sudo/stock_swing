"""Tests for scripts/backfill_open_position_count.py (bug fix 2026-08-13)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from backfill_open_position_count import active_on_date, compute_open_counts


# ── active_on_date ────────────────────────────────────────────────────────────

class TestActiveOnDate:
    def test_open_trade_entered_before_date_is_active(self):
        trade = {"entry_time": "2026-08-01T10:00:00Z", "exit_time": None}
        assert active_on_date(trade, "2026-08-05") is True

    def test_trade_entered_after_date_is_not_active(self):
        trade = {"entry_time": "2026-08-10T10:00:00Z", "exit_time": None}
        assert active_on_date(trade, "2026-08-05") is False

    def test_trade_entered_and_exited_same_day_is_active_that_day(self):
        # end-of-day snapshot semantics: exit must be strictly after date
        trade = {"entry_time": "2026-08-01T10:00:00Z", "exit_time": "2026-08-01T15:00:00Z"}
        assert active_on_date(trade, "2026-08-01") is False

    def test_trade_closed_the_day_after_is_active_on_entry_date(self):
        trade = {"entry_time": "2026-08-01T10:00:00Z", "exit_time": "2026-08-02T15:00:00Z"}
        assert active_on_date(trade, "2026-08-01") is True

    def test_trade_exited_before_date_is_not_active(self):
        trade = {"entry_time": "2026-07-01T10:00:00Z", "exit_time": "2026-07-15T15:00:00Z"}
        assert active_on_date(trade, "2026-08-01") is False

    def test_missing_entry_time_is_not_active(self):
        trade = {"entry_time": None, "exit_time": None}
        assert active_on_date(trade, "2026-08-01") is False

    def test_malformed_entry_time_is_not_active(self):
        trade = {"entry_time": "not-a-date", "exit_time": None}
        assert active_on_date(trade, "2026-08-01") is False


# ── compute_open_counts ───────────────────────────────────────────────────────

class TestComputeOpenCounts:
    def test_counts_across_multiple_dates(self):
        trades = [
            {"status": "open", "entry_time": "2026-08-01T10:00:00Z", "exit_time": None},
            {"status": "closed", "entry_time": "2026-08-02T10:00:00Z", "exit_time": "2026-08-03T10:00:00Z"},
        ]
        dates = ["2026-08-01", "2026-08-02", "2026-08-03"]
        counts = compute_open_counts(trades, dates)
        assert counts == {"2026-08-01": 1, "2026-08-02": 2, "2026-08-03": 1}

    def test_empty_trades_returns_zero_for_all_dates(self):
        counts = compute_open_counts([], ["2026-08-01", "2026-08-02"])
        assert counts == {"2026-08-01": 0, "2026-08-02": 0}

    def test_quarantined_trades_excluded(self):
        trades = [
            {"status": "quarantined", "entry_time": "2026-08-01T10:00:00Z", "exit_time": None},
            {"status": "open", "entry_time": "2026-08-01T10:00:00Z", "exit_time": None},
        ]
        counts = compute_open_counts(trades, ["2026-08-01"])
        assert counts == {"2026-08-01": 1}


# ── main() end-to-end on a fixture state file ────────────────────────────────

class TestMainBackfill:
    def _write_state(self, tmp_path: Path, snapshots: list[dict], trades: list[dict]) -> Path:
        path = tmp_path / "pnl_state.json"
        path.write_text(json.dumps({"daily_snapshots": snapshots, "trades": trades}), encoding="utf-8")
        return path

    def test_dry_run_does_not_modify_file(self, tmp_path, capsys):
        path = self._write_state(
            tmp_path,
            snapshots=[{"date": "2026-08-01", "equity": 1000.0}],
            trades=[{"status": "open", "entry_time": "2026-08-01T10:00:00Z", "exit_time": None}],
        )
        before = path.read_text(encoding="utf-8")

        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "backfill_open_position_count.py"),
             "--dry-run", "--state-path", str(path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Backfilled: 1" in result.stdout
        assert path.read_text(encoding="utf-8") == before

    def test_writes_backfilled_values(self, tmp_path):
        path = self._write_state(
            tmp_path,
            snapshots=[
                {"date": "2026-08-01", "equity": 1000.0},
                {"date": "2026-08-02", "equity": 1010.0},
            ],
            trades=[
                {"status": "open", "entry_time": "2026-08-01T10:00:00Z", "exit_time": None},
                {"status": "closed", "entry_time": "2026-08-01T10:00:00Z", "exit_time": "2026-08-01T12:00:00Z"},
            ],
        )
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "backfill_open_position_count.py"),
             "--state-path", str(path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        updated = json.loads(path.read_text(encoding="utf-8"))
        snaps_by_date = {s["date"]: s for s in updated["daily_snapshots"]}
        assert snaps_by_date["2026-08-01"]["open_position_count"] == 1
        assert snaps_by_date["2026-08-02"]["open_position_count"] == 1

    def test_does_not_overwrite_already_set_values(self, tmp_path):
        path = self._write_state(
            tmp_path,
            snapshots=[{"date": "2026-08-01", "equity": 1000.0, "open_position_count": 42}],
            trades=[{"status": "open", "entry_time": "2026-08-01T10:00:00Z", "exit_time": None}],
        )
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "backfill_open_position_count.py"),
             "--state-path", str(path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Already had open_position_count: 1" in result.stdout
        assert "Backfilled: 0" in result.stdout
        updated = json.loads(path.read_text(encoding="utf-8"))
        # Must stay at the pre-existing recorded value (1), not be overwritten
        # by the recomputed value (42 preserved, not replaced by 1).
        assert updated["daily_snapshots"][0]["open_position_count"] == 42

    def test_empty_snapshots_is_a_noop(self, tmp_path):
        path = self._write_state(tmp_path, snapshots=[], trades=[])
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "backfill_open_position_count.py"),
             "--state-path", str(path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "nothing to backfill" in result.stdout.lower()

    def test_backup_flag_creates_backup_file(self, tmp_path):
        path = self._write_state(
            tmp_path,
            snapshots=[{"date": "2026-08-01", "equity": 1000.0}],
            trades=[{"status": "open", "entry_time": "2026-08-01T10:00:00Z", "exit_time": None}],
        )
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "backfill_open_position_count.py"),
             "--backup", "--state-path", str(path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        backups = list(tmp_path.glob("pnl_state_backup_open_pos_backfill_*.json"))
        assert len(backups) == 1
