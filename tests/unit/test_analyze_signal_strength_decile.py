"""R4-C (2026-08-14): signal-strength decile analysis regression tests.

Covers scripts/analyze_signal_strength_decile.py's compute_decile_stats(),
which was previously untested despite being the source of the R4-C
recommendation logic (min_signal_strength threshold suggestion).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "analyze_signal_strength_decile.py"
_spec = importlib.util.spec_from_file_location("analyze_signal_strength_decile", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["analyze_signal_strength_decile"] = _module
_spec.loader.exec_module(_module)

compute_decile_stats = _module.compute_decile_stats
compute_calibration_curve = _module.compute_calibration_curve


def _trade(ss: float, pnl: float, status: str = "closed", entry_time: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "status": status,
        "entry_signal_strength": ss,
        "pnl": pnl,
        "entry_time": entry_time,
    }


class TestFiltering:
    def test_empty_trades_returns_empty(self):
        assert compute_decile_stats([]) == []

    def test_non_closed_trades_excluded(self):
        trades = [_trade(0.5, 100.0, status="open")]
        assert compute_decile_stats(trades) == []

    def test_missing_signal_strength_excluded(self):
        trades = [{"status": "closed", "pnl": 100.0, "entry_time": "2026-01-01T00:00:00Z"}]
        assert compute_decile_stats(trades) == []

    def test_missing_pnl_excluded(self):
        trades = [{"status": "closed", "entry_signal_strength": 0.5, "entry_time": "2026-01-01T00:00:00Z"}]
        assert compute_decile_stats(trades) == []

    def test_since_filter_excludes_older_trades(self):
        trades = [
            _trade(0.5, 100.0, entry_time="2026-01-01T00:00:00Z"),
            _trade(0.6, 200.0, entry_time="2026-06-01T00:00:00Z"),
        ]
        rows = compute_decile_stats(trades, since="2026-03-01", n_buckets=1)
        assert sum(r["count"] for r in rows) == 1


class TestBucketing:
    def test_single_bucket_aggregates_all(self):
        trades = [_trade(0.5, 100.0), _trade(0.6, -50.0), _trade(0.7, 200.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        assert len(rows) == 1
        assert rows[0]["count"] == 3
        assert rows[0]["net_pnl"] == 250.0

    def test_deciles_sorted_ascending_by_signal_strength(self):
        trades = [_trade(0.9, 10.0), _trade(0.1, 10.0), _trade(0.5, 10.0)]
        rows = compute_decile_stats(trades, n_buckets=3)
        ss_mins = [r["ss_min"] for r in rows]
        assert ss_mins == sorted(ss_mins)

    def test_fewer_trades_than_buckets_produces_nonempty_buckets_only(self):
        trades = [_trade(0.3, 10.0), _trade(0.8, -10.0)]
        rows = compute_decile_stats(trades, n_buckets=10)
        assert len(rows) <= 2
        assert all(r["count"] > 0 for r in rows)


class TestPfWrComputation:
    def test_all_wins_pf_is_infinite_none(self):
        trades = [_trade(0.5, 100.0), _trade(0.6, 50.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        assert rows[0]["profit_factor"] is None  # infinite PF serialized as None
        assert rows[0]["win_rate"] == 1.0

    def test_all_losses_pf_is_zero(self):
        trades = [_trade(0.5, -100.0), _trade(0.6, -50.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        assert rows[0]["profit_factor"] == 0.0
        assert rows[0]["win_rate"] == 0.0

    def test_mixed_pf_computed_correctly(self):
        trades = [_trade(0.5, 100.0), _trade(0.6, -50.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        assert rows[0]["profit_factor"] == 2.0  # 100 / 50
        assert rows[0]["win_rate"] == 0.5

    def test_zero_pnl_trade_counts_as_neither_win_nor_loss(self):
        trades = [_trade(0.5, 0.0), _trade(0.6, 100.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        assert rows[0]["count"] == 2
        assert rows[0]["wins"] == 1
        assert rows[0]["losses"] == 0


class TestExpectancy:
    """R4-v2 residual (2026-08-17): expectancy = net_pnl / count for the
    decile, distinct from the bucket-total net_pnl already computed."""

    def test_expectancy_is_net_pnl_divided_by_count(self):
        trades = [_trade(0.5, 100.0), _trade(0.6, -50.0), _trade(0.7, 30.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        assert rows[0]["count"] == 3
        assert rows[0]["net_pnl"] == 80.0
        assert rows[0]["expectancy"] == round(80.0 / 3, 2)

    def test_expectancy_present_on_every_bucket(self):
        trades = [_trade(0.1, 10.0), _trade(0.9, -10.0)]
        rows = compute_decile_stats(trades, n_buckets=2)
        assert all("expectancy" in r for r in rows)

    def test_expectancy_matches_single_trade_pnl(self):
        trades = [_trade(0.5, -123.45)]
        rows = compute_decile_stats(trades, n_buckets=1)
        assert rows[0]["expectancy"] == -123.45


class TestCalibrationCurve:
    """R4-v2 residual (2026-08-23): calibration curve (predicted midpoint vs
    actual win_rate), read-only diagnostic, no automatic threshold changes."""

    def test_empty_rows_returns_empty_curve(self):
        assert compute_calibration_curve([]) == []

    def test_curve_has_one_row_per_decile(self):
        trades = [_trade(0.1, 10.0), _trade(0.9, -10.0)]
        rows = compute_decile_stats(trades, n_buckets=2)
        curve = compute_calibration_curve(rows)
        assert len(curve) == len(rows)

    def test_predicted_is_midpoint_of_ss_range(self):
        trades = [_trade(0.4, 10.0), _trade(0.6, 10.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        curve = compute_calibration_curve(rows)
        assert curve[0]["predicted"] == round((0.4 + 0.6) / 2.0, 4)

    def test_actual_matches_win_rate(self):
        trades = [_trade(0.5, 100.0), _trade(0.6, -50.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        curve = compute_calibration_curve(rows)
        assert curve[0]["actual"] == rows[0]["win_rate"]

    def test_calibration_error_is_abs_diff(self):
        trades = [_trade(0.5, 100.0), _trade(0.6, -50.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        curve = compute_calibration_curve(rows)
        expected = round(abs(curve[0]["predicted"] - curve[0]["actual"]), 4)
        assert curve[0]["calibration_error"] == expected

    def test_perfect_calibration_zero_error(self):
        # ss range collapses to a single point (0.5), and win_rate is
        # exactly 0.5 -> predicted == actual -> zero error.
        trades = [_trade(0.5, 100.0), _trade(0.5, -100.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        curve = compute_calibration_curve(rows)
        assert curve[0]["predicted"] == 0.5
        assert curve[0]["actual"] == 0.5
        assert curve[0]["calibration_error"] == 0.0


class TestSsRangeFormatting:
    def test_ss_range_reflects_min_max_of_bucket(self):
        trades = [_trade(0.3, 10.0), _trade(0.4, 10.0), _trade(0.5, 10.0)]
        rows = compute_decile_stats(trades, n_buckets=1)
        assert rows[0]["ss_min"] == 0.3
        assert rows[0]["ss_max"] == 0.5
