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
# R5-v2 (2026-08-14): pairwise correlation threshold. Mirrors the
# "high_correlation_threshold" default in pairwise_correlation.
# summarize_high_correlation_pairs() -- kept as a separate constant here
# (rather than importing that module's default) so promotion_gate.py's
# thresholds stay self-contained and independently overridable.
DEFAULT_HIGH_CORRELATION_MAX_PCT = 0.80


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
    top5_concentration_equity_pct: float | None,
    max_pct: float = DEFAULT_TOP5_CONCENTRATION_MAX_PCT,
    *,
    top5_concentration_gross_pct: float | None = None,
    gross_exposure_pct_of_equity: float | None = None,
    hhi: float | None = None,
) -> PromotionCriterion:
    """Top-5 position concentration, as a fraction of ACCOUNT EQUITY (e.g.
    0.35 = 35% of equity), must be below max_pct.

    AUDIT FIX (2026-08-23): this criterion previously received
    dashboard_service._summarize_positions()'s "top5_concentration" key,
    which is top5 weight / GROSS EXPOSURE (portfolio_weight is computed as
    market_value/gross_exposure, so weights always sum to 100% across all
    positions regardless of how much of equity is actually invested). That
    was compared against max_pct=40%, a threshold whose own historical
    comment ties it to AllocationConfig.correlated_cluster_cap_pct -- an
    EQUITY-based cap. A portfolio can look "fine" on a gross basis (top5/
    gross shrinks toward 0 as position count grows, independent of equity
    utilization) while still being concentrated relative to actual account
    equity, or vice versa. This function now takes the EQUITY-based
    percentage as its primary evaluated metric, matching the threshold's
    apparent intent.

    Args:
        top5_concentration_equity_pct: fraction (0.0-1.0) of ACCOUNT EQUITY,
            as produced by dashboard_service._summarize_positions()'s
            "top5_concentration_equity_pct" key. None when positions or
            equity are unavailable.
        top5_concentration_gross_pct: fraction (0.0-1.0) of GROSS EXPOSURE
            (the old/legacy basis), included in `detail` for visibility only
            -- not itself evaluated against max_pct.
        gross_exposure_pct_of_equity: gross exposure as a fraction of
            equity, included in `detail` for visibility (e.g. a portfolio
            near or above 100% here is using most/all of its capital
            regardless of top5 concentration).
        hhi: Herfindahl-Hirschman Index (sum of squared gross-exposure
            weights) as an alternate, cutoff-independent concentration
            measure, included in `detail` for visibility only.
    """
    _detail_parts = []
    if top5_concentration_gross_pct is not None:
        _detail_parts.append(f"gross_basis={top5_concentration_gross_pct * 100:.1f}%")
    if gross_exposure_pct_of_equity is not None:
        _detail_parts.append(f"gross_exposure/equity={gross_exposure_pct_of_equity * 100:.1f}%")
    if hhi is not None:
        _detail_parts.append(f"hhi={hhi:.4f}")
    _detail = ", ".join(_detail_parts)

    if top5_concentration_equity_pct is None:
        return PromotionCriterion(
            name="top5_concentration",
            passed=False,
            actual="unavailable",
            required=f"<={max_pct:.0f}% of equity",
            detail=_detail or "position data not provided",
        )
    pct = top5_concentration_equity_pct * 100.0
    return PromotionCriterion(
        name="top5_concentration",
        passed=pct <= max_pct,
        actual=f"{pct:.1f}% of equity",
        required=f"<={max_pct:.0f}% of equity",
        detail=_detail,
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


def _evaluate_pairwise_correlation(
    correlation_summary: dict[str, Any] | None,
    max_pct: float = DEFAULT_HIGH_CORRELATION_MAX_PCT,
) -> PromotionCriterion:
    """No held-symbol pair currently has |correlation| >= max_pct.

    Args:
        correlation_summary: dict as returned by
            pairwise_correlation.summarize_high_correlation_pairs(), i.e.
            {"available": bool, "high_correlation_pairs": [...], ...}.
            None when unavailable.
        max_pct: threshold passed to summarize_high_correlation_pairs()
            when the caller built correlation_summary (informational only
            here -- this function just reports what's in the dict).
    """
    if correlation_summary is None or not correlation_summary.get("available"):
        return PromotionCriterion(
            name="pairwise_correlation",
            passed=False,
            actual="unavailable",
            required=f"no pair with |correlation|>={max_pct}",
            detail=(correlation_summary or {}).get("reason", "correlation_summary not provided"),
        )
    high_pairs = correlation_summary.get("high_correlation_pairs") or []
    return PromotionCriterion(
        name="pairwise_correlation",
        passed=not high_pairs,
        actual=(
            [f"{p['symbol_a']}/{p['symbol_b']}={p['correlation']}" for p in high_pairs]
            if high_pairs else "none"
        ),
        required=f"no pair with |correlation|>={max_pct}",
        detail=f"checked {correlation_summary.get('checked_pairs', 0)} pair(s)",
    )


def evaluate_promotion_readiness(
    *,
    cluster_exposures: list[dict] | None = None,
    top5_concentration: float | None = None,
    top5_concentration_gross_pct: float | None = None,
    gross_exposure_pct_of_equity: float | None = None,
    top5_hhi: float | None = None,
    beta_data: dict[str, Any] | None = None,
    closed_trades: list[dict] | None = None,
    correlation_summary: dict[str, Any] | None = None,
    top5_concentration_max_pct: float = DEFAULT_TOP5_CONCENTRATION_MAX_PCT,
    beta_max: float = DEFAULT_BETA_MAX,
    clean_pf_min: float = DEFAULT_CLEAN_PF_MIN,
    clean_pf_min_trades: int = DEFAULT_MIN_CLEAN_TRADES,
    high_correlation_max_pct: float = DEFAULT_HIGH_CORRELATION_MAX_PCT,
) -> PromotionReadiness:
    """Evaluate the R5-v2 promotion-gate criteria this module adds.

    This does NOT replace scripts/check_go_no_go.py's broader Required
    condition checklist (ledger validity, circuit breaker, attribution
    coverage, etc.) -- it specifically fills the previously-missing "market
    beta / cluster cap / pairwise correlation / top-5 concentration / clean
    cohort PF" gap called out in docs/console_improvement_tasks.md R5-v2.

    Any criterion with unavailable input data is reported as failing
    (fail-closed), not silently skipped, so a caller cannot mistake "we
    didn't check" for "it passed".

    Args:
        correlation_summary: optional output of
            pairwise_correlation.summarize_high_correlation_pairs(). When
            omitted (None), the pairwise_correlation criterion fails
            closed (same "unavailable" treatment as the other criteria),
            it is NOT silently skipped from the readiness verdict.
    """
    criteria = [
        _evaluate_cluster_cap(cluster_exposures),
        # AUDIT FIX (2026-08-23): `top5_concentration` (the legacy
        # gross-exposure-based fraction) is accepted for backward
        # compatibility with older callers, but the equity-based fraction is
        # now the metric actually evaluated against max_pct when both are
        # provided. See _evaluate_top5_concentration()'s docstring.
        _evaluate_top5_concentration(
            top5_concentration,
            max_pct=top5_concentration_max_pct,
            top5_concentration_gross_pct=top5_concentration_gross_pct,
            gross_exposure_pct_of_equity=gross_exposure_pct_of_equity,
            hhi=top5_hhi,
        ),
        _evaluate_beta(beta_data, max_beta=beta_max),
        _evaluate_clean_cohort_pf(closed_trades, min_pf=clean_pf_min, min_trades=clean_pf_min_trades),
        _evaluate_pairwise_correlation(correlation_summary, max_pct=high_correlation_max_pct),
    ]
    return PromotionReadiness(criteria=criteria)
