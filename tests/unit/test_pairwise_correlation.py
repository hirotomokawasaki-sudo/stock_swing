"""R5-v2 (2026-08-14): pairwise_correlation.py tests.

Fills the last remaining R5-v2 REOPENED gap: an actual correlation
coefficient between symbol return series (distinct from
correlation_cluster.py's fixed hand-authored cluster groupings).
"""
from __future__ import annotations

import json
from pathlib import Path

from stock_swing.risk.pairwise_correlation import (
    build_daily_closes_from_raw_bars,
    compute_pair_correlation,
    compute_pairwise_correlation,
    summarize_high_correlation_pairs,
    _daily_returns,
)


# ---------------------------------------------------------------------------
# build_daily_closes_from_raw_bars
# ---------------------------------------------------------------------------

def _write_bars_snapshot(dir_path: Path, symbol: str, filename: str, bars: list[dict], endpoint: str = "marketdata/bars") -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / filename).write_text(json.dumps({
        "endpoint": endpoint,
        "payload": {"bars": bars},
    }), encoding="utf-8")


class TestBuildDailyClosesFromRawBars:
    def test_missing_directory_returns_empty(self, tmp_path):
        result = build_daily_closes_from_raw_bars("NVDA", tmp_path / "nonexistent")
        assert result == {}

    def test_no_matching_files_returns_empty(self, tmp_path):
        _write_bars_snapshot(tmp_path, "AMD", "broker_amd_2026-08-01_000000.json", [
            {"t": "2026-08-01T04:00:00Z", "c": 100.0},
        ])
        result = build_daily_closes_from_raw_bars("NVDA", tmp_path)
        assert result == {}

    def test_single_snapshot_extracted(self, tmp_path):
        _write_bars_snapshot(tmp_path, "NVDA", "broker_nvda_2026-08-01_000000.json", [
            {"t": "2026-07-30T04:00:00Z", "c": 100.0},
            {"t": "2026-07-31T04:00:00Z", "c": 101.5},
        ])
        result = build_daily_closes_from_raw_bars("NVDA", tmp_path)
        assert result == {"2026-07-30": 100.0, "2026-07-31": 101.5}

    def test_case_insensitive_symbol_matching(self, tmp_path):
        _write_bars_snapshot(tmp_path, "nvda", "broker_nvda_2026-08-01_000000.json", [
            {"t": "2026-07-30T04:00:00Z", "c": 100.0},
        ])
        result = build_daily_closes_from_raw_bars("nvda", tmp_path)
        assert result == {"2026-07-30": 100.0}

    def test_multiple_snapshots_deduplicated_by_date(self, tmp_path):
        _write_bars_snapshot(tmp_path, "NVDA", "broker_nvda_a.json", [
            {"t": "2026-07-30T04:00:00Z", "c": 100.0},
        ])
        _write_bars_snapshot(tmp_path, "NVDA", "broker_nvda_b.json", [
            {"t": "2026-07-30T04:00:00Z", "c": 100.0},  # same date, different fetch
            {"t": "2026-07-31T04:00:00Z", "c": 105.0},
        ])
        result = build_daily_closes_from_raw_bars("NVDA", tmp_path)
        assert len(result) == 2
        assert result["2026-07-31"] == 105.0

    def test_non_bars_endpoint_ignored(self, tmp_path):
        _write_bars_snapshot(
            tmp_path, "NVDA", "broker_nvda_quote.json",
            bars=[], endpoint="quotes/latest",
        )
        result = build_daily_closes_from_raw_bars("NVDA", tmp_path)
        assert result == {}

    def test_corrupt_file_skipped_not_raised(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "broker_nvda_bad.json").write_text("not json", encoding="utf-8")
        _write_bars_snapshot(tmp_path, "NVDA", "broker_nvda_good.json", [
            {"t": "2026-07-30T04:00:00Z", "c": 100.0},
        ])
        result = build_daily_closes_from_raw_bars("NVDA", tmp_path)
        assert result == {"2026-07-30": 100.0}

    def test_missing_close_or_date_skipped(self, tmp_path):
        _write_bars_snapshot(tmp_path, "NVDA", "broker_nvda_x.json", [
            {"t": "2026-07-30T04:00:00Z", "c": 100.0},
            {"t": "2026-07-31T04:00:00Z"},  # missing close
            {"c": 102.0},  # missing date
        ])
        result = build_daily_closes_from_raw_bars("NVDA", tmp_path)
        assert result == {"2026-07-30": 100.0}


# ---------------------------------------------------------------------------
# _daily_returns
# ---------------------------------------------------------------------------

class TestDailyReturns:
    def test_empty_input_empty_output(self):
        assert _daily_returns({}) == {}

    def test_single_point_no_returns(self):
        assert _daily_returns({"2026-01-01": 100.0}) == {}

    def test_two_points_one_return(self):
        result = _daily_returns({"2026-01-01": 100.0, "2026-01-02": 110.0})
        assert result == {"2026-01-02": 0.1}

    def test_returns_sorted_by_date(self):
        # Insert out of order
        closes = {"2026-01-03": 121.0, "2026-01-01": 100.0, "2026-01-02": 110.0}
        result = _daily_returns(closes)
        assert result["2026-01-02"] == 0.1
        assert abs(result["2026-01-03"] - 0.1) < 1e-9

    def test_zero_prev_close_skipped(self):
        closes = {"2026-01-01": 0.0, "2026-01-02": 100.0}
        result = _daily_returns(closes)
        assert result == {}


# ---------------------------------------------------------------------------
# compute_pair_correlation
# ---------------------------------------------------------------------------

class TestComputePairCorrelation:
    def test_insufficient_overlap_reports_unavailable(self):
        closes_a = {f"2026-01-{i:02d}": 100.0 + i for i in range(1, 5)}
        closes_b = {f"2026-01-{i:02d}": 200.0 + i for i in range(1, 5)}
        result = compute_pair_correlation(closes_a, closes_b, min_overlap_days=10)
        assert result["available"] is False
        assert "insufficient_overlap" in result["reason"]

    # Varying daily % moves (not a constant growth rate) so the return
    # series has genuine variance -- a constant growth rate produces
    # near-zero-variance returns (all ~equal), which is numerically
    # unstable for a correlation coefficient (dividing by near-zero std).
    _DAILY_PCT_MOVES = [0.02, -0.01, 0.03, 0.01, -0.02, 0.015, -0.005, 0.025, -0.015, 0.01, 0.02, -0.01, 0.005, -0.02]

    def _apply_moves(self, start: float, moves: list[float]) -> dict[str, float]:
        dates = [f"2026-01-{i:02d}" for i in range(1, len(moves) + 2)]
        closes = {dates[0]: start}
        price = start
        for i, move in enumerate(moves):
            price = price * (1 + move)
            closes[dates[i + 1]] = price
        return closes

    def test_perfectly_correlated_series(self):
        """Series B follows the exact same daily % moves as A (different
        starting price) -> identical daily returns -> correlation == 1.0."""
        closes_a = self._apply_moves(100.0, self._DAILY_PCT_MOVES)
        closes_b = self._apply_moves(50.0, self._DAILY_PCT_MOVES)
        result = compute_pair_correlation(closes_a, closes_b, min_overlap_days=10)
        assert result["available"] is True
        assert result["correlation"] > 0.99

    def test_perfectly_anti_correlated_series(self):
        """Series B has exactly inverted daily % moves from A ->
        correlation == -1.0."""
        closes_a = self._apply_moves(100.0, self._DAILY_PCT_MOVES)
        closes_b = self._apply_moves(100.0, [-m for m in self._DAILY_PCT_MOVES])
        result = compute_pair_correlation(closes_a, closes_b, min_overlap_days=10)
        assert result["available"] is True
        assert result["correlation"] < -0.99

    def test_zero_variance_series_unavailable(self):
        dates = [f"2026-01-{i:02d}" for i in range(1, 16)]
        closes_a = {d: 100.0 for d in dates}  # flat, zero variance in returns
        closes_b = {d: 100.0 + i for i, d in enumerate(dates)}
        result = compute_pair_correlation(closes_a, closes_b, min_overlap_days=10)
        assert result["available"] is False
        assert result["reason"] == "zero_variance"

    def test_no_overlapping_dates(self):
        closes_a = {f"2026-01-{i:02d}": 100.0 for i in range(1, 15)}
        closes_b = {f"2026-02-{i:02d}": 100.0 for i in range(1, 15)}
        result = compute_pair_correlation(closes_a, closes_b, min_overlap_days=5)
        assert result["available"] is False
        assert result["overlap_days"] == 0

    def test_correlation_clamped_to_valid_range(self):
        """Even with float precision noise, correlation must stay in [-1, 1]."""
        dates = [f"2026-01-{i:02d}" for i in range(1, 16)]
        closes_a = {d: 100.0 + i * 2 for i, d in enumerate(dates)}
        closes_b = {d: 100.0 + i * 2 for i, d in enumerate(dates)}  # identical series
        result = compute_pair_correlation(closes_a, closes_b, min_overlap_days=10)
        assert result["available"] is True
        assert -1.0 <= result["correlation"] <= 1.0


# ---------------------------------------------------------------------------
# compute_pairwise_correlation
# ---------------------------------------------------------------------------

class TestComputePairwiseCorrelation:
    def test_empty_input_returns_empty(self):
        assert compute_pairwise_correlation({}) == []

    def test_single_symbol_no_pairs(self):
        dates = [f"2026-01-{i:02d}" for i in range(1, 15)]
        closes = {"NVDA": {d: 100.0 + i for i, d in enumerate(dates)}}
        assert compute_pairwise_correlation(closes) == []

    def test_two_symbols_one_pair(self):
        dates = [f"2026-01-{i:02d}" for i in range(1, 15)]
        closes = {
            "NVDA": {d: 100.0 + i for i, d in enumerate(dates)},
            "AMD": {d: 50.0 + i for i, d in enumerate(dates)},
        }
        results = compute_pairwise_correlation(closes)
        assert len(results) == 1
        assert results[0]["symbol_a"] == "AMD"  # alphabetically sorted
        assert results[0]["symbol_b"] == "NVDA"

    def test_three_symbols_three_pairs_no_duplicates(self):
        dates = [f"2026-01-{i:02d}" for i in range(1, 15)]
        closes = {
            sym: {d: 100.0 + i * (idx + 1) for i, d in enumerate(dates)}
            for idx, sym in enumerate(["NVDA", "AMD", "MSFT"])
        }
        results = compute_pairwise_correlation(closes)
        assert len(results) == 3  # C(3,2) = 3
        pair_keys = {(r["symbol_a"], r["symbol_b"]) for r in results}
        assert len(pair_keys) == 3  # no duplicate/reversed pairs


# ---------------------------------------------------------------------------
# summarize_high_correlation_pairs
# ---------------------------------------------------------------------------

class TestSummarizeHighCorrelationPairs:
    def test_empty_input_fails_closed(self):
        result = summarize_high_correlation_pairs([])
        assert result["available"] is False
        assert result["reason"] == "no_computable_pairs"

    def test_all_unavailable_pairs_fails_closed(self):
        pairwise = [
            {"symbol_a": "A", "symbol_b": "B", "available": False, "correlation": None, "overlap_days": 2, "reason": "insufficient_overlap"},
        ]
        result = summarize_high_correlation_pairs(pairwise)
        assert result["available"] is False
        assert result["checked_pairs"] == 1
        assert result["available_pairs"] == 0

    def test_no_high_correlation_pairs(self):
        pairwise = [
            {"symbol_a": "A", "symbol_b": "B", "available": True, "correlation": 0.3, "overlap_days": 15, "reason": None},
        ]
        result = summarize_high_correlation_pairs(pairwise, high_correlation_threshold=0.80)
        assert result["available"] is True
        assert result["high_correlation_pairs"] == []

    def test_high_correlation_pair_detected(self):
        pairwise = [
            {"symbol_a": "A", "symbol_b": "B", "available": True, "correlation": 0.95, "overlap_days": 15, "reason": None},
            {"symbol_a": "A", "symbol_b": "C", "available": True, "correlation": 0.2, "overlap_days": 15, "reason": None},
        ]
        result = summarize_high_correlation_pairs(pairwise, high_correlation_threshold=0.80)
        assert len(result["high_correlation_pairs"]) == 1
        assert result["high_correlation_pairs"][0]["symbol_a"] == "A"
        assert result["high_correlation_pairs"][0]["symbol_b"] == "B"

    def test_high_negative_correlation_also_detected(self):
        """abs(correlation) >= threshold, so strong negative correlation counts too."""
        pairwise = [
            {"symbol_a": "A", "symbol_b": "B", "available": True, "correlation": -0.90, "overlap_days": 15, "reason": None},
        ]
        result = summarize_high_correlation_pairs(pairwise, high_correlation_threshold=0.80)
        assert len(result["high_correlation_pairs"]) == 1

    def test_mixed_available_and_unavailable_pairs(self):
        pairwise = [
            {"symbol_a": "A", "symbol_b": "B", "available": True, "correlation": 0.90, "overlap_days": 15, "reason": None},
            {"symbol_a": "A", "symbol_b": "C", "available": False, "correlation": None, "overlap_days": 3, "reason": "insufficient_overlap"},
        ]
        result = summarize_high_correlation_pairs(pairwise, high_correlation_threshold=0.80)
        assert result["available"] is True
        assert result["checked_pairs"] == 2
        assert result["available_pairs"] == 1
        assert len(result["high_correlation_pairs"]) == 1
