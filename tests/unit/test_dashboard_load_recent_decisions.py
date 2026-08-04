"""Tests for DashboardService._load_recent_decisions() sort-by-content-time fix.

Regression (2026-08-04): user-reported "Decisions" count on the Trading tab
stayed frozen at exactly 500 for weeks. Root cause: a 2026-07-13 bulk
rebuild/backfill operation touched (mtime) ~1956 old decision files without
changing their content or decision date. _load_recent_decisions() sorted by
filesystem st_mtime and truncated to `limit` BEFORE reading file content, so
that batch of stale files permanently occupied the mtime-sorted top slots --
every dashboard call got a stale ~500-decision snapshot dominated by the
07-13 rebuild, hard-capping the Trading tab funnel's "Decisions" metric at
exactly 500 and effectively freezing the by_strategy/by_symbol/deny-reason
breakdowns at 07-13-era content, even though thousands of newer decisions
existed on disk.

Fix: parse each file's actual decision timestamp (generated_at/created_at/
decision_time, falling back to filename-derived time) first, then sort/
truncate by that content-derived timestamp instead of filesystem mtime.

See docs/daily_logs/2026-08-04.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from console.services.dashboard_service import DashboardService


class _StubService(DashboardService):
    """Minimal DashboardService stub that avoids real broker/tracker I/O."""
    def __init__(self, project_root: Path) -> None:  # type: ignore[override]
        self.project_root = project_root
        self._broker = None
        self._tracker = None


def _write_decision(
    decisions_dir: Path,
    filename: str,
    generated_at: str,
    mtime: float | None = None,
    symbol: str = "AAPL",
) -> Path:
    path = decisions_dir / filename
    decisions_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "decision_id": filename,
        "symbol": symbol,
        "action": "buy",
        "generated_at": generated_at,
    }), encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(path, (mtime, mtime))
    return path


class TestLoadRecentDecisionsSortsByContentTime:
    def test_regression_bulk_rebuild_mtime_does_not_mask_newer_decisions(self, tmp_path):
        """
        Regression: replicate the exact 2026-07-13 incident at small scale.
        A batch of OLD decisions (by generated_at) gets its mtime bumped to
        "now" (simulating a rebuild touching the files), while a handful of
        genuinely NEW decisions have older mtimes (simulating files written
        before some unrelated background process touched the old batch).
        The newest-by-generated_at decisions must still be selected.
        """
        decisions_dir = tmp_path / "data" / "decisions"
        now = datetime.now(timezone.utc)
        rebuild_mtime = now.timestamp()  # "just touched" by the rebuild
        older_mtime = (now - timedelta(days=30)).timestamp()

        # 20 OLD decisions (by content), but mtime bumped to "now" by a rebuild.
        for i in range(20):
            _write_decision(
                decisions_dir,
                f"decision_OLD{i}.json",
                (now - timedelta(days=60, hours=i)).isoformat(),
                mtime=rebuild_mtime,
            )

        # 5 NEW decisions (by content), with an OLDER mtime (written before
        # some background process touched the old batch above).
        new_files = []
        for i in range(5):
            new_files.append(_write_decision(
                decisions_dir,
                f"decision_NEW{i}.json",
                (now - timedelta(minutes=i)).isoformat(),
                mtime=older_mtime,
            ).name)

        svc = _StubService(tmp_path)
        top = svc._load_recent_decisions(limit=5)

        selected_files = {d["_source_file"] for d in top}
        assert selected_files == set(new_files), (
            f"Expected the 5 content-newest decisions {new_files}, "
            f"got {selected_files} (mtime-based sorting bug not fixed)"
        )

    def test_normal_case_no_mtime_skew_returns_newest_by_content(self, tmp_path):
        """AC: normal case (mtime happens to match content order) still works."""
        decisions_dir = tmp_path / "data" / "decisions"
        now = datetime.now(timezone.utc)
        for i in range(10):
            gen_at = now - timedelta(hours=i)
            _write_decision(decisions_dir, f"decision_D{i}.json", gen_at.isoformat(), mtime=gen_at.timestamp())

        svc = _StubService(tmp_path)
        top3 = svc._load_recent_decisions(limit=3)
        assert [d["_source_file"] for d in top3] == ["decision_D0.json", "decision_D1.json", "decision_D2.json"]

    def test_limit_boundary_returns_at_most_limit_items(self, tmp_path):
        """境界値: limit より少ないファイルしかない場合は全件返す。"""
        decisions_dir = tmp_path / "data" / "decisions"
        now = datetime.now(timezone.utc)
        for i in range(3):
            _write_decision(decisions_dir, f"decision_D{i}.json", (now - timedelta(hours=i)).isoformat())

        svc = _StubService(tmp_path)
        result = svc._load_recent_decisions(limit=500)
        assert len(result) == 3

    def test_missing_decisions_dir_returns_empty_list(self, tmp_path):
        """境界値: decisions ディレクトリが存在しない -> クラッシュせず空リスト。"""
        svc = _StubService(tmp_path)
        assert svc._load_recent_decisions(limit=500) == []

    def test_corrupt_json_file_skipped_not_crash(self, tmp_path):
        """破損入力: 1件が不正JSONでもクラッシュせず、他の正常ファイルは返る。"""
        decisions_dir = tmp_path / "data" / "decisions"
        decisions_dir.mkdir(parents=True)
        now = datetime.now(timezone.utc)
        _write_decision(decisions_dir, "decision_GOOD.json", now.isoformat())
        (decisions_dir / "decision_BAD.json").write_text("{not valid json", encoding="utf-8")

        svc = _StubService(tmp_path)
        result = svc._load_recent_decisions(limit=500)
        assert len(result) == 1
        assert result[0]["_source_file"] == "decision_GOOD.json"

    def test_missing_generated_at_falls_back_to_filename_timestamp(self, tmp_path):
        """境界値: generated_at 欠損時はファイル名から時刻を推定してソートする
        （extract_decision_dt の filename_dt フォールバックに委ねる）。"""
        decisions_dir = tmp_path / "data" / "decisions"
        decisions_dir.mkdir(parents=True)
        # Filename pattern: decision_{symbol}_{YYYYMMDD}_{HHMMSS}.json
        (decisions_dir / "decision_AAPL_20260101_010000.json").write_text(
            json.dumps({"decision_id": "d1", "symbol": "AAPL", "action": "buy"}), encoding="utf-8"
        )
        (decisions_dir / "decision_MSFT_20260601_010000.json").write_text(
            json.dumps({"decision_id": "d2", "symbol": "MSFT", "action": "buy"}), encoding="utf-8"
        )

        svc = _StubService(tmp_path)
        result = svc._load_recent_decisions(limit=500)
        # MSFT (June) must sort before AAPL (January) despite neither having
        # generated_at, using the filename-derived timestamp fallback.
        assert result[0]["_source_file"] == "decision_MSFT_20260601_010000.json"
        assert result[1]["_source_file"] == "decision_AAPL_20260101_010000.json"
