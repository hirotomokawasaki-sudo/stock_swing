"""2026-08-14 (roadmap gap #5): tests for sector_shock_historical_replay.py's
--rolling option, which re-runs the historical replay with the same rolling
3-day sector-return check added to the live paper_demo.py path on
2026-08-14 (see sector_shock_hold.py's sector_shock_rolling_threshold_pct).

Real-data finding (documented here and in docs/console_improvement_tasks.md
穴5): re-running the 103-trade historical replay with --rolling produced
IDENTICAL classifications to the non-rolling run (0 diffs across all 103
trades) -- the rolling fix, while correct and beneficial for future live
detection (confirmed separately against the real 2026-06-08 LRCX case),
did not change this particular historical dataset's classification
distribution. This is a negative result worth recording: it means the
R3-v2 "forward valid stop-trigger shadow >= 10" activation threshold
question raised in gap #5 is not resolved by re-running history -- it can
only be answered by observing live forward shadow data after the rolling
fix, which the existing 08-21 R9 Plan B/C/D/E interim review can also check
by reviewing data/sector_shock_shadow_log.jsonl's post-2026-08-14 entries.
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "sector_shock_historical_replay.py"
_spec = importlib.util.spec_from_file_location("sector_shock_historical_replay", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["sector_shock_historical_replay"] = _module
_spec.loader.exec_module(_module)


def _bm_csv_path(tmp_path: Path) -> Path:
    p = tmp_path / "data" / "benchmarks" / "benchmark_returns.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class TestLoadBenchmarkRollingReturnsByDate:
    def test_reads_return_3d_column_by_default(self, tmp_path, monkeypatch):
        csv_path = _bm_csv_path(tmp_path)
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "symbol", "close", "daily_return", "return_3d", "return_5d", "cumulative_return"])
            writer.writerow(["2026-06-08", "SMH", "600.0", "0.0500", "-0.0623", "-0.0159", "0.10"])
            writer.writerow(["2026-06-08", "SOXX", "550.0", "0.0587", "-0.0718", "-0.0008", "0.12"])

        monkeypatch.setattr(_module, "ROOT", tmp_path)
        result = _module.load_benchmark_rolling_returns_by_date()

        assert result["2026-06-08"]["SMH"] == -0.0623
        assert result["2026-06-08"]["SOXX"] == -0.0718

    def test_custom_column_name(self, tmp_path, monkeypatch):
        csv_path = _bm_csv_path(tmp_path)
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "symbol", "return_5d"])
            writer.writerow(["2026-06-08", "SMH", "-0.0159"])

        monkeypatch.setattr(_module, "ROOT", tmp_path)
        result = _module.load_benchmark_rolling_returns_by_date(column="return_5d")

        assert result["2026-06-08"]["SMH"] == -0.0159

    def test_missing_or_empty_values_skipped(self, tmp_path, monkeypatch):
        csv_path = _bm_csv_path(tmp_path)
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "symbol", "return_3d"])
            writer.writerow(["2026-06-08", "SMH", ""])  # empty
            writer.writerow(["2026-06-09", "SOXX", "-0.05"])

        monkeypatch.setattr(_module, "ROOT", tmp_path)
        result = _module.load_benchmark_rolling_returns_by_date()

        assert "SMH" not in result.get("2026-06-08", {})
        assert result["2026-06-09"]["SOXX"] == -0.05

    def test_empty_csv_returns_empty_dict(self, tmp_path, monkeypatch):
        csv_path = _bm_csv_path(tmp_path)
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "symbol", "return_3d"])

        monkeypatch.setattr(_module, "ROOT", tmp_path)
        result = _module.load_benchmark_rolling_returns_by_date()

        assert result == {}
