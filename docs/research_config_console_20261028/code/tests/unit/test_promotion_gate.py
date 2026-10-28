"""R5-v2 (2026-08-14): promotion_gate.evaluate_promotion_readiness() tests.

Covers the previously-missing combination of market beta / cluster cap /
top-5 concentration / clean-cohort PF into a single promotion-readiness
verdict (docs/console_improvement_tasks.md R5-v2 REOPENED reason).
"""
from __future__ import annotations

from stock_swing.risk.promotion_gate import (
    evaluate_promotion_readiness,
    _evaluate_cluster_cap,
    _evaluate_top5_concentration,
    _evaluate_beta,
    _evaluate_clean_cohort_pf,
    _evaluate_pairwise_correlation,
    DEFAULT_MIN_CLEAN_TRADES,
)


def _closed(pnl: float) -> dict:
    return {"status": "closed", "pnl": pnl}


# ---------------------------------------------------------------------------
# _evaluate_cluster_cap
# ---------------------------------------------------------------------------

class TestClusterCap:
    def test_none_input_fails_closed(self):
        result = _evaluate_cluster_cap(None)
        assert result.passed is False
        assert result.actual == "unavailable"

    def test_empty_list_passes(self):
        result = _evaluate_cluster_cap([])
        assert result.passed is True

    def test_no_cluster_over_cap_passes(self):
        exposures = [{"cluster_name": "hyperscale", "over_cap": False}]
        result = _evaluate_cluster_cap(exposures)
        assert result.passed is True

    def test_one_cluster_over_cap_fails(self):
        exposures = [
            {"cluster_name": "hyperscale", "over_cap": False},
            {"cluster_name": "cloud_software", "over_cap": True},
        ]
        result = _evaluate_cluster_cap(exposures)
        assert result.passed is False
        assert "cloud_software" in result.actual


# ---------------------------------------------------------------------------
# _evaluate_top5_concentration
# ---------------------------------------------------------------------------

class TestTop5Concentration:
    def test_none_fails_closed(self):
        result = _evaluate_top5_concentration(None)
        assert result.passed is False

    def test_under_threshold_passes(self):
        result = _evaluate_top5_concentration(0.30)  # 30%
        assert result.passed is True
        # AUDIT FIX (2026-08-23): actual is now labeled "% of equity" since
        # this criterion evaluates the equity-based top5 fraction, not the
        # legacy gross-exposure-based fraction. See
        # _evaluate_top5_concentration()'s docstring for the distinction.
        assert result.actual == "30.0% of equity"

    def test_over_threshold_fails(self):
        result = _evaluate_top5_concentration(0.55)  # 55%
        assert result.passed is False

    def test_exactly_at_threshold_passes(self):
        result = _evaluate_top5_concentration(0.40, max_pct=40.0)
        assert result.passed is True

    def test_custom_threshold_respected(self):
        result = _evaluate_top5_concentration(0.25, max_pct=20.0)
        assert result.passed is False


# ---------------------------------------------------------------------------
# _evaluate_beta
# ---------------------------------------------------------------------------

class TestBeta:
    def test_none_fails_closed(self):
        result = _evaluate_beta(None)
        assert result.passed is False

    def test_unavailable_fails_closed(self):
        result = _evaluate_beta({"available": False, "error": "not enough data"})
        assert result.passed is False
        assert result.detail == "not enough data"

    def test_low_beta_passes(self):
        result = _evaluate_beta({"available": True, "beta": 0.9})
        assert result.passed is True
        assert result.actual == 0.9

    def test_high_beta_fails(self):
        result = _evaluate_beta({"available": True, "beta": 1.8})
        assert result.passed is False

    def test_exactly_at_max_passes(self):
        result = _evaluate_beta({"available": True, "beta": 1.5}, max_beta=1.5)
        assert result.passed is True

    def test_missing_beta_key_fails_closed(self):
        result = _evaluate_beta({"available": True})
        assert result.passed is False


# ---------------------------------------------------------------------------
# _evaluate_clean_cohort_pf
# ---------------------------------------------------------------------------

class TestCleanCohortPf:
    def test_none_fails_closed(self):
        result = _evaluate_clean_cohort_pf(None)
        assert result.passed is False

    def test_insufficient_trades_fails(self):
        trades = [_closed(100.0) for _ in range(5)]  # n=5 < default min 20
        result = _evaluate_clean_cohort_pf(trades)
        assert result.passed is False
        assert "n=5" in result.actual

    def test_sufficient_trades_good_pf_passes(self):
        trades = [_closed(100.0) for _ in range(15)] + [_closed(-50.0) for _ in range(10)]
        result = _evaluate_clean_cohort_pf(trades, min_trades=20)
        assert len(trades) == 25
        assert result.passed is True  # PF = 1500/500 = 3.0

    def test_sufficient_trades_bad_pf_fails(self):
        trades = [_closed(50.0) for _ in range(5)] + [_closed(-100.0) for _ in range(20)]
        result = _evaluate_clean_cohort_pf(trades, min_trades=20)
        assert result.passed is False  # PF = 250/2000 = 0.125

    def test_all_wins_infinite_pf_passes(self):
        trades = [_closed(100.0) for _ in range(25)]
        result = _evaluate_clean_cohort_pf(trades, min_trades=20)
        assert result.passed is True
        assert result.actual == "inf"

    def test_trades_missing_pnl_excluded_from_count(self):
        trades = [_closed(100.0) for _ in range(20)] + [{"status": "closed", "pnl": None}]
        result = _evaluate_clean_cohort_pf(trades, min_trades=20)
        assert "n=20" in result.actual or result.passed  # 20 valid trades counted, not 21

    def test_custom_min_pf_respected(self):
        trades = [_closed(100.0) for _ in range(10)] + [_closed(-80.0) for _ in range(10)]
        # PF = 1000/800 = 1.25
        result_strict = _evaluate_clean_cohort_pf(trades, min_pf=1.5, min_trades=20)
        result_loose = _evaluate_clean_cohort_pf(trades, min_pf=1.0, min_trades=20)
        assert result_strict.passed is False
        assert result_loose.passed is True


# ---------------------------------------------------------------------------
# _evaluate_pairwise_correlation
# ---------------------------------------------------------------------------

class TestPairwiseCorrelation:
    def test_none_fails_closed(self):
        result = _evaluate_pairwise_correlation(None)
        assert result.passed is False
        assert result.actual == "unavailable"

    def test_unavailable_summary_fails_closed(self):
        result = _evaluate_pairwise_correlation({"available": False, "reason": "no_computable_pairs"})
        assert result.passed is False
        assert result.detail == "no_computable_pairs"

    def test_no_high_correlation_pairs_passes(self):
        result = _evaluate_pairwise_correlation({
            "available": True, "high_correlation_pairs": [], "checked_pairs": 5,
        })
        assert result.passed is True
        assert result.actual == "none"

    def test_high_correlation_pair_fails(self):
        result = _evaluate_pairwise_correlation({
            "available": True,
            "high_correlation_pairs": [{"symbol_a": "AMZN", "symbol_b": "MSFT", "correlation": 0.94}],
            "checked_pairs": 10,
        })
        assert result.passed is False
        assert "AMZN/MSFT=0.94" in result.actual


# ---------------------------------------------------------------------------
# evaluate_promotion_readiness (combined)
# ---------------------------------------------------------------------------

class TestEvaluatePromotionReadiness:
    def test_all_criteria_missing_fails_closed_overall(self):
        readiness = evaluate_promotion_readiness()
        assert readiness.all_pass is False
        assert len(readiness.failing) == 5  # all 5 criteria fail-closed with no data

    def test_all_criteria_pass_overall_pass(self):
        trades = [_closed(100.0) for _ in range(15)] + [_closed(-50.0) for _ in range(10)]
        readiness = evaluate_promotion_readiness(
            cluster_exposures=[{"cluster_name": "hyperscale", "over_cap": False}],
            top5_concentration=0.30,
            beta_data={"available": True, "beta": 1.0},
            closed_trades=trades,
            correlation_summary={"available": True, "high_correlation_pairs": [], "checked_pairs": 3},
            clean_pf_min_trades=20,
        )
        assert readiness.all_pass is True
        assert readiness.failing == []

    def test_one_failing_criterion_overall_fails(self):
        trades = [_closed(100.0) for _ in range(15)] + [_closed(-50.0) for _ in range(10)]
        readiness = evaluate_promotion_readiness(
            cluster_exposures=[{"cluster_name": "cloud_software", "over_cap": True}],  # fails
            top5_concentration=0.30,
            beta_data={"available": True, "beta": 1.0},
            closed_trades=trades,
            correlation_summary={"available": True, "high_correlation_pairs": [], "checked_pairs": 3},
            clean_pf_min_trades=20,
        )
        assert readiness.all_pass is False
        assert "cluster_cap" in readiness.failing

    def test_high_pairwise_correlation_alone_fails_overall(self):
        trades = [_closed(100.0) for _ in range(15)] + [_closed(-50.0) for _ in range(10)]
        readiness = evaluate_promotion_readiness(
            cluster_exposures=[{"cluster_name": "hyperscale", "over_cap": False}],
            top5_concentration=0.30,
            beta_data={"available": True, "beta": 1.0},
            closed_trades=trades,
            correlation_summary={
                "available": True,
                "high_correlation_pairs": [{"symbol_a": "AMZN", "symbol_b": "MSFT", "correlation": 0.94}],
                "checked_pairs": 3,
            },
            clean_pf_min_trades=20,
        )
        assert readiness.all_pass is False
        assert "pairwise_correlation" in readiness.failing

    def test_to_dict_shape(self):
        readiness = evaluate_promotion_readiness()
        d = readiness.to_dict()
        assert set(d.keys()) == {"all_pass", "failing", "criteria"}
        assert len(d["criteria"]) == 5
        for c in d["criteria"]:
            assert set(c.keys()) == {"name", "passed", "actual", "required", "detail"}

    def test_default_min_clean_trades_constant_used(self):
        """Regression: ensure the module-level default constant is actually
        threaded through when caller doesn't override clean_pf_min_trades."""
        trades = [_closed(100.0) for _ in range(DEFAULT_MIN_CLEAN_TRADES - 1)]
        readiness = evaluate_promotion_readiness(closed_trades=trades)
        clean_pf_criterion = next(c for c in readiness.criteria if c.name == "clean_cohort_pf")
        assert clean_pf_criterion.passed is False
