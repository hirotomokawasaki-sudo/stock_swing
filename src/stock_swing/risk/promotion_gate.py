"""R5-v2: promotion gate criteria for market beta / cluster cap / top-5
concentration / clean-cohort profit factor.

Context (docs/console_improvement_tasks.md R5-v2, REOPENED):
    "market beta / sector/factor exposure / pairwise correlation / top-5
    concentration 未実装" -- concentration and cluster-cap data already
    existed elsewhere (dashboard_service._summarize_positions()'s
    top5_concentration, correlation_cluster.compute_cluster_exposures()) and
    portfolio beta already existed in benchmark_service.calculate_beta(), but
    none of them were combined into an explicit promotion/graduation
    decision. This module is that combination layer: a single, testable,
    dependency-light function that takes already-computed pieces (this
    module does not itself talk to a broker or load YAML) and returns a
    pass/fail verdict per criterion plus an overall readiness flag.

Design notes:
    - Pure function over plain dicts/lists -- no I/O, no console/ imports --
      so it can be unit tested without mocking a broker or file system, and
      can be called equally from scripts/check_go_no_go.py, a console
      endpoint, or an isolated cron job.
    - "clean cohort" = trades already excluded from the quarantine bucket
      upstream (status == "closed" in pnl_state.json; quarantined trades
      never reach status="closed" -- see pnl_tracker.py's F1 quarantine
      gate). Callers must pass already-filtered closed trades; this module
      does not re-derive quarantine status itself to avoid duplicating that
      logic (single source of truth stays in pnl_tracker.py).
    - Recommendation-only: nothing in this module blocks trading. It is
      meant to feed a manual Go/No-Go decision (scripts/check_go_no_go.py)
      or dashboard visibility, matching the R4-v2/R5-v2 "recommendation-
      only" learning constraint already documented for related features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- Default thresholds -----------------------------------------------------
# These mirror existing related thresholds already in the codebase rather
# than inventing new numbers from scratch:
#   - cluster cap: correlation_cluster.DEFAULT_CLUSTER_CAPS (already enforced
#     as a hard BUY block elsewhere; this gate just checks "none currently
#     over cap" using the same compute_cluster_exposures() output).
#   - top5 concentration: 40% chosen to match
#     AllocationConfig.correlated_cluster_cap_pct (0.40), the existing
#     precedent for "no single correlated group should exceed 40% of
#     equity" in this codebase.
#   - beta: <=1.5 chosen to match benchmark_service._interpret_beta()'s own
#     "High volatility" threshold (beta > 1.5).
#   - clean cohort profit factor: >=1.0 (breakeven or better on the clean,
#     non-quarantined cohort) -- the minimum bar for "not actively losing
#     money", distinct from and lower than the R0-v2/R3-v2 "preferred" PF
#     targets (1.20) used for the broader Go/No-Go decision.
DEFAULT_TOP5_CONCENTRATION_MAX_PCT = 40.0
DEFAULT_BETA_MAX = 1.5
DEFAULT_CLEAN_PF_MIN = 1.0
DEFAULT_MIN_CLEAN_TRADES = 20


@dataclass(frozen=True)
class PromotionCriterion:
    name: str
    passed: bool
    actual: Any
    required: str
    detail: str = ""


@dataclass(frozen=True)
class PromotionReadiness:
    criteria: list[PromotionCriterion] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return all(c.passed for c in self.criteria)

    @property
    def failing(self) -> list[str]:
        return [c.name for c in self.criteria if not c.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_pass": self.all_pass,
            "failing": self.failing,
            "criteria": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "actual": c.actual,
                    "required": c.required,
                    "detail": c.detail,
                }
                for c in self.criteria
            ],
        }


def _evaluate_cluster_cap(cluster_exposures: list[dict] | None) -> PromotionCriterion:
    """No correlation cluster currently exceeding its cap.

    Args:
        cluster_exposures: rows as returned by
            correlation_cluster.compute_cluster_exposures() (already
            dict-shaped when sourced via
            DashboardService._get_cluster_exposure()), or None/[] when
            unavailable.
    """
    if cluster_exposures is None:
        return PromotionCriterion(
            name="cluster_cap",
            passed=False,
            actual="unavailable",
            required="no cluster over cap",
            detail="cluster_exposures not provided",
        )
    over_cap = [
        c.get("cluster_name") for c in cluster_exposures
        if isinstance(c, dict) and c.get("over_cap")
    ]
    return PromotionCriterion(
        name="cluster_cap",
        passed=not over_cap,
        actual=over_cap if over_cap else "none over cap",
        required="no cluster over cap",
        detail=f"{len(over_cap)} cluster(s) over cap" if over_cap else "",
    )


def _evaluate_top5_concentration(
    top5_concentration: float | None,
    max_pct: float = DEFAULT_TOP5_CONCENTRATION_MAX_PCT,
) -> PromotionCriterion:
    """Top-5 position concentration (as a fraction, e.g. 0.35 = 35%) must be
    below max_pct.

    Args:
        top5_concentration: fraction (0.0-1.0), as produced by
            dashboard_service._summarize_positions()'s "top5_concentration"
            key. None when positions are unavailable.
    """
    if top5_concentration is None:
        return PromotionCriterion(
            name="top5_concentration",
            passed=False,
            actual="unavailable",
            required=f"<={max_pct:.0f}%",
            detail="position data not provided",
        )
    pct = top5_concentration * 100.0
    return PromotionCriterion(
        name="top5_concentration",
        passed=pct <= max_pct,
        actual=f"{pct:.1f}%",
        required=f"<={max_pct:.0f}%",
    )


def _evaluate_beta(
    beta_data: dict[str, Any] | None,
    max_beta: float = DEFAULT_BETA_MAX,
) -> PromotionCriterion:
    """Portfolio beta vs. benchmark must be <= max_beta.

    Args:
        beta_data: dict as returned by
            benchmark_service.BenchmarkService.calculate_beta(), i.e.
            {"available": bool, "beta": float, ...}. None when unavailable.
    """
    if not beta_data or not beta_data.get("available"):
        return PromotionCriterion(
            name="portfolio_beta",
            passed=False,
            actual="unavailable",
            required=f"<={max_beta}",
            detail=(beta_data or {}).get("error", "beta data not provided"),
        )
    beta = beta_data.get("beta")
    if beta is None:
        return PromotionCriterion(
            name="portfolio_beta",
            passed=False,
            actual="unavailable",
            required=f"<={max_beta}",
        )
    return PromotionCriterion(
        name="portfolio_beta",
        passed=beta <= max_beta,
        actual=round(beta, 3),
        required=f"<={max_beta}",
    )


def _evaluate_clean_cohort_pf(
    closed_trades: list[dict] | None,
    min_pf: float = DEFAULT_CLEAN_PF_MIN,
    min_trades: int = DEFAULT_MIN_CLEAN_TRADES,
) -> PromotionCriterion:
    """Clean (non-quarantined) cohort profit factor must be >= min_pf, with
    enough trades (min_trades) for the number to be meaningful.

    Args:
        closed_trades: already-filtered trades with status == "closed"
            (i.e. the clean cohort -- quarantined trades excluded upstream
            by pnl_tracker.py's F1 gate; this function does not re-check
            status itself). Each trade dict must have a numeric "pnl" key.
    """
    trades = [t for t in (closed_trades or []) if t.get("pnl") is not None]
    n = len(trades)
    if n < min_trades:
        return PromotionCriterion(
            name="clean_cohort_pf",
            passed=False,
            actual=f"n={n}",
            required=f">=1.0 PF with n>={min_trades}",
            detail="insufficient clean trade count for a meaningful PF",
        )
    gross_win = sum(float(t["pnl"]) for t in trades if float(t["pnl"]) > 0)
    gross_loss = abs(sum(float(t["pnl"]) for t in trades if float(t["pnl"]) < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    passed = pf >= min_pf
    return PromotionCriterion(
        name="clean_cohort_pf",
        passed=passed,
        actual=round(pf, 3) if pf != float("inf") else "inf",
        required=f">={min_pf} (n>={min_trades})",
        detail=f"n={n}",
    )


def evaluate_promotion_readiness(
    *,
    cluster_exposures: list[dict] | None = None,
    top5_concentration: float | None = None,
    beta_data: dict[str, Any] | None = None,
    closed_trades: list[dict] | None = None,
    top5_concentration_max_pct: float = DEFAULT_TOP5_CONCENTRATION_MAX_PCT,
    beta_max: float = DEFAULT_BETA_MAX,
    clean_pf_min: float = DEFAULT_CLEAN_PF_MIN,
    clean_pf_min_trades: int = DEFAULT_MIN_CLEAN_TRADES,
) -> PromotionReadiness:
    """Evaluate the R5-v2 promotion-gate criteria this module adds.

    This does NOT replace scripts/check_go_no_go.py's broader Required
    condition checklist (ledger validity, circuit breaker, attribution
    coverage, etc.) -- it specifically fills the previously-missing "market
    beta / cluster cap / top-5 concentration / clean cohort PF" gap called
    out in docs/console_improvement_tasks.md R5-v2.

    Any criterion with unavailable input data is reported as failing
    (fail-closed), not silently skipped, so a caller cannot mistake "we
    didn't check" for "it passed".
    """
    criteria = [
        _evaluate_cluster_cap(cluster_exposures),
        _evaluate_top5_concentration(top5_concentration, max_pct=top5_concentration_max_pct),
        _evaluate_beta(beta_data, max_beta=beta_max),
        _evaluate_clean_cohort_pf(closed_trades, min_pf=clean_pf_min, min_trades=clean_pf_min_trades),
    ]
    return PromotionReadiness(criteria=criteria)
