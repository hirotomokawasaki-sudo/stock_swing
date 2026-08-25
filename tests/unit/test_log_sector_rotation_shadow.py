"""Tests for scripts/log_sector_rotation_shadow.py (R13-D shadow logger,
2026-08-25/26).

Focus: the safety guard that prevents this shadow script from ever writing
to the REAL production RebalanceState file (data/sector_rotation_state.json),
and the log_shadow()/fetch helper functions that don't need network access.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "log_sector_rotation_shadow.py"

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from log_sector_rotation_shadow import load_etf_sector_map, log_shadow  # noqa: E402


def test_state_path_guard_rejects_real_production_state_file(tmp_path):
    """The safety guard must refuse to run if --state-path points at the
    real production state filename, even in a different directory --
    matching by filename only is deliberately strict (see module
    docstring point 4: shadow runs must never interfere with a future
    real Phase 3 wiring's state).
    """
    fake_prod_state = tmp_path / "sector_rotation_state.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", "--state-path", str(fake_prod_state)],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    assert result.returncode == 1
    assert "must not be the real production state file" in result.stderr


def test_load_etf_sector_map_returns_us_etfs_with_sector_tags():
    """Sanity: the registry loader must return a non-empty US-ETF-only
    sector map (JP ETFs, ending in .T, are excluded -- this script is US
    sector rotation only, matching R13-D's scope)."""
    sector_map = load_etf_sector_map()
    assert sector_map, "expected at least one ETF with a sector tag"
    assert all(not sym.endswith(".T") for sym in sector_map)
    assert all(isinstance(sector, str) and sector for sector in sector_map.values())


def test_log_shadow_writes_jsonl(tmp_path):
    log_path = tmp_path / "sector_rotation_shadow_log.jsonl"
    record = {
        "date": "2026-08-26",
        "rebalance_due": True,
        "top_sectors": ["technology_cloud", "broad_market"],
        "candidate_symbols": ["SKYY", "SPY"],
        "mode": "shadow",
    }
    log_shadow(record, shadow_log_path=log_path)

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["candidate_symbols"] == ["SKYY", "SPY"]
    assert parsed["mode"] == "shadow"


def test_log_shadow_without_path_does_not_raise():
    log_shadow({"date": "2026-08-26", "mode": "shadow"}, shadow_log_path=None)  # must not raise


def test_log_shadow_appends_multiple_records(tmp_path):
    log_path = tmp_path / "sector_rotation_shadow_log.jsonl"
    for i in range(3):
        log_shadow({"date": f"2026-08-{26 + i}", "mode": "shadow"}, shadow_log_path=log_path)
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
