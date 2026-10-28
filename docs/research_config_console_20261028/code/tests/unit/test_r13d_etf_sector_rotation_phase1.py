"""R13-D Phase 1 (2026-08-23): unit tests for scripts/
r13d_etf_sector_rotation_phase1.py's rotation logic core functions.

Pure-function tests against small synthetic return series -- does not
touch data/r11_price_cache/ or any production data/config path. This is a
research-only script (Phase 1 feasibility check); these tests exist so the
ranking/rebalance/metrics math itself is verified independent of which
real-world result it produces.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from r13d_etf_sector_rotation_phase1 import (  # noqa: E402
    cumulative_curve,
    max_drawdown,
    run_rotation,
    sharpe_ratio,
    trailing_return,
)


class TestTrailingReturn:
    def test_computes_cumulative_return_over_window(self):
        dates = [f"d{i}" for i in range(10)]
        returns = {d: 0.01 for d in dates}  # +1% every day
        tr = trailing_return(returns, dates, end_idx=5, lookback=5)
        expected = (1.01 ** 5) - 1
        assert abs(tr - expected) < 1e-9

    def test_returns_none_when_not_enough_history(self):
        dates = [f"d{i}" for i in range(3)]
        returns = {d: 0.01 for d in dates}
        assert trailing_return(returns, dates, end_idx=2, lookback=10) is None

    def test_returns_none_when_coverage_too_sparse(self):
        dates = [f"d{i}" for i in range(10)]
        # Only 2 of 5 lookback days have data -- below the 80% coverage floor.
        returns = {"d3": 0.01, "d4": 0.01}
        assert trailing_return(returns, dates, end_idx=5, lookback=5) is None


class TestRunRotation:
    def test_picks_top_n_sectors_by_trailing_return(self):
        dates = [f"d{i}" for i in range(30)]
        # sector A: strong uptrend, sector B: flat, sector C: downtrend
        sector_returns = {
            "A": {d: 0.02 for d in dates},
            "B": {d: 0.0 for d in dates},
            "C": {d: -0.01 for d in dates},
        }
        result = run_rotation(sector_returns, dates, top_n=1, lookback_days=10, hold_days=5)
        assert result["rebalance_log"], "expected at least one rebalance"
        first_rebalance = result["rebalance_log"][0]
        assert first_rebalance["holdings"] == ["A"], (
            f"expected sector A (strongest trailing return) to be selected; "
            f"got {first_rebalance['holdings']}"
        )

    def test_rebalances_only_every_hold_days(self):
        dates = [f"d{i}" for i in range(50)]
        sector_returns = {
            "A": {d: 0.01 for d in dates},
            "B": {d: 0.005 for d in dates},
        }
        result = run_rotation(sector_returns, dates, top_n=1, lookback_days=10, hold_days=7)
        rebalance_dates = [e["date"] for e in result["rebalance_log"]]
        # Rebalances should be spaced hold_days apart (first one forced at
        # the first eligible index, i.e. lookback_days).
        assert len(rebalance_dates) >= 2
        idx_map = {d: i for i, d in enumerate(dates)}
        gaps = [
            idx_map[rebalance_dates[i + 1]] - idx_map[rebalance_dates[i]]
            for i in range(len(rebalance_dates) - 1)
        ]
        assert all(g == 7 for g in gaps), f"expected all rebalance gaps == hold_days(7); got {gaps}"

    def test_portfolio_return_matches_held_sector_when_top_n_one(self):
        dates = [f"d{i}" for i in range(20)]
        sector_returns = {
            "A": {d: 0.03 for d in dates},
            "B": {d: -0.01 for d in dates},
        }
        result = run_rotation(sector_returns, dates, top_n=1, lookback_days=5, hold_days=100)
        daily = dict(result["daily_returns"])
        # Once holding sector A exclusively, daily portfolio return must
        # equal sector A's own return exactly (no blending).
        held_dates = [e for e in daily if e in sector_returns["A"]]
        assert held_dates
        for d in held_dates[5:]:  # skip warmup before first rebalance
            assert abs(daily[d] - 0.03) < 1e-9


class TestPerformanceMetrics:
    def test_cumulative_curve_compounds_correctly(self):
        daily_returns = [("d0", 0.10), ("d1", 0.10), ("d2", -0.10)]
        curve = cumulative_curve(daily_returns)
        expected_final = 1.10 * 1.10 * 0.90
        assert abs(curve[-1] - expected_final) < 1e-9

    def test_max_drawdown_detects_peak_to_trough(self):
        # Curve: 1.0 -> 1.5 (peak) -> 0.75 (50% drawdown from peak) -> 1.0
        curve = [1.0, 1.5, 0.75, 1.0]
        dd = max_drawdown(curve)
        assert abs(dd - 0.5) < 1e-9

    def test_sharpe_ratio_zero_for_zero_variance(self):
        daily_returns = [0.01, 0.01, 0.01, 0.01]
        assert sharpe_ratio(daily_returns) is None

    def test_sharpe_ratio_positive_for_positive_mean_return(self):
        daily_returns = [0.02, 0.01, 0.015, -0.005, 0.01]
        sharpe = sharpe_ratio(daily_returns)
        assert sharpe is not None
        assert sharpe > 0
