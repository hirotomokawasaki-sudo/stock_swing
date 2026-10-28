"""2026-08-14: tests for scripts/capture_promotion_gate_snapshot.py (R5-v2
roadmap gap #2 -- explicit branch conditions for the promotion-gate
observation window).

Covers classify_trend()'s four branches (passing / improving / stuck /
worsening) and _extract_numeric_actual()'s parsing of promotion_gate.py's
mixed string/float 'actual' field formats.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "capture_promotion_gate_snapshot.py"
_spec = importlib.util.spec_from_file_location("capture_promotion_gate_snapshot", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["capture_promotion_gate_snapshot"] = _module
_spec.loader.exec_module(_module)

classify_trend = _module.classify_trend
_extract_numeric_actual = _module._extract_numeric_actual
evaluate_trend = _module.evaluate_trend


class TestExtractNumericActual:
    def test_extracts_float_directly(self):
        promotion = {"portfolio_beta": {"actual": 0.704}}
        assert _extract_numeric_actual(promotion, "portfolio_beta") == 0.704

    def test_extracts_percent_string(self):
        promotion = {"top5_concentration": {"actual": "51.9%"}}
        assert _extract_numeric_actual(promotion, "top5_concentration") == 51.9

    def test_extracts_plain_numeric_string(self):
        promotion = {"clean_cohort_pf": {"actual": "0.914"}}
        assert _extract_numeric_actual(promotion, "clean_cohort_pf") == 0.914

    def test_returns_none_for_missing_criterion(self):
        promotion = {}
        assert _extract_numeric_actual(promotion, "top5_concentration") is None

    def test_returns_none_for_list_actual(self):
        """pairwise_correlation's 'actual' is a list of pair strings, not a
        single numeric value -- must not crash, just return None."""
        promotion = {"pairwise_correlation": {"actual": ["AMZN/MSFT=0.94"]}}
        assert _extract_numeric_actual(promotion, "pairwise_correlation") is None

    def test_returns_none_for_unavailable_string(self):
        promotion = {"clean_cohort_pf": {"actual": "unavailable"}}
        assert _extract_numeric_actual(promotion, "clean_cohort_pf") is None

    def test_returns_none_when_actual_is_none(self):
        promotion = {"portfolio_beta": {"actual": None}}
        assert _extract_numeric_actual(promotion, "portfolio_beta") is None


class TestClassifyTrendInsufficientData:
    def test_single_value_is_insufficient_data(self):
        result = classify_trend([51.9], threshold=40.0, direction="lower_is_better")
        assert result["classification"] == "insufficient_data"

    def test_empty_values_is_insufficient_data(self):
        result = classify_trend([], threshold=40.0, direction="lower_is_better")
        assert result["classification"] == "insufficient_data"
        assert result["first_value"] is None


class TestClassifyTrendPassing:
    def test_lower_is_better_already_passing(self):
        result = classify_trend([35.0, 32.0], threshold=40.0, direction="lower_is_better")
        assert result["classification"] == "passing"

    def test_higher_is_better_already_passing(self):
        result = classify_trend([1.1, 1.2], threshold=1.0, direction="higher_is_better")
        assert result["classification"] == "passing"


class TestClassifyTrendImproving:
    def test_lower_is_better_improving_and_on_track(self):
        """top5_concentration decreasing from 52% toward 40% threshold,
        ending close enough to count as 'on track'."""
        values = [52.0, 48.0, 44.0, 41.0]  # gap = 1.0/40 = 2.5% <= 10% tolerance
        result = classify_trend(values, threshold=40.0, direction="lower_is_better")
        assert result["classification"] == "improving"
        assert "ON TRACK" in result["recommendation"]

    def test_higher_is_better_improving_and_on_track(self):
        values = [0.914, 0.94, 0.96, 0.99]  # gap = 0.01/1.0 = 1% <= 10%
        result = classify_trend(values, threshold=1.0, direction="higher_is_better")
        assert result["classification"] == "improving"
        assert "ON TRACK" in result["recommendation"]

    def test_improving_but_not_yet_close(self):
        values = [52.0, 50.0, 48.0]  # moving toward pass but gap still large
        result = classify_trend(values, threshold=40.0, direction="lower_is_better")
        assert result["classification"] == "improving"
        assert "not yet close" in result["recommendation"]


class TestClassifyTrendStuck:
    def test_lower_is_better_stuck(self):
        """Value barely moves (well within STUCK_TOLERANCE_PCT=3%) across
        the whole window."""
        values = [52.0, 52.3, 51.8, 52.1]
        result = classify_trend(values, threshold=40.0, direction="lower_is_better")
        assert result["classification"] == "stuck"
        assert "STUCK" in result["recommendation"]

    def test_higher_is_better_stuck(self):
        values = [0.914, 0.916, 0.912, 0.915]
        result = classify_trend(values, threshold=1.0, direction="higher_is_better")
        assert result["classification"] == "stuck"


class TestClassifyTrendWorsening:
    def test_lower_is_better_worsening(self):
        """top5_concentration increasing (moving away from the <=40% threshold)."""
        values = [52.0, 56.0, 60.0]
        result = classify_trend(values, threshold=40.0, direction="lower_is_better")
        assert result["classification"] == "worsening"
        assert "WORSENING" in result["recommendation"]
        assert "immediate intervention" in result["recommendation"]

    def test_higher_is_better_worsening(self):
        """clean_cohort_pf decreasing (moving away from the >=1.0 threshold)."""
        values = [0.914, 0.85, 0.78]
        result = classify_trend(values, threshold=1.0, direction="higher_is_better")
        assert result["classification"] == "worsening"


class TestClassifyTrendReturnShape:
    def test_delta_computed_correctly(self):
        result = classify_trend([52.0, 48.0], threshold=40.0, direction="lower_is_better")
        assert result["delta"] == -4.0

    def test_first_and_last_value_recorded(self):
        result = classify_trend([52.0, 50.0, 48.0], threshold=40.0, direction="lower_is_better")
        assert result["first_value"] == 52.0
        assert result["last_value"] == 48.0


class TestEvaluateTrendIntegration:
    def _snapshot(self, top5, clean_pf, beta):
        return {
            "promotion": {
                "top5_concentration": {"actual": f"{top5}%", "pass": top5 <= 40.0},
                "clean_cohort_pf": {"actual": clean_pf, "pass": clean_pf >= 1.0},
                "portfolio_beta": {"actual": beta, "pass": beta <= 1.5},
            }
        }

    def test_evaluate_trend_produces_all_three_criteria(self):
        snapshots = [
            self._snapshot(52.0, 0.914, 0.704),
            self._snapshot(48.0, 0.94, 0.71),
        ]
        result = evaluate_trend(snapshots)
        assert set(result.keys()) == {"top5_concentration", "clean_cohort_pf", "portfolio_beta"}
        assert result["top5_concentration"]["classification"] == "improving"
        assert result["portfolio_beta"]["classification"] == "passing"

    def test_evaluate_trend_handles_missing_criterion_in_some_snapshots(self):
        """If a criterion is unavailable in some snapshots (e.g. correlation
        data missing for a day), only the available values should be used
        for trend classification, not crash."""
        snapshots = [
            {"promotion": {"top5_concentration": {"actual": "52.0%"}}},
            {"promotion": {}},  # missing this day
            {"promotion": {"top5_concentration": {"actual": "48.0%"}}},
        ]
        result = evaluate_trend(snapshots)
        assert result["top5_concentration"]["first_value"] == 52.0
        assert result["top5_concentration"]["last_value"] == 48.0
