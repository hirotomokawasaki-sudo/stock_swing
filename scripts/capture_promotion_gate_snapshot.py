"""R5-v2 (2026-08-14, roadmap gap #2): daily promotion-gate snapshot capture
for the 2026-08-24〜09-04 paper observation window.

Background
----------
docs/console_improvement_tasks.md flagged this as "穴2" (gap #2) in the
2026-08-14 roadmap gap analysis: the plan to "observe promotion_gate for
2 weeks" had no explicit rule for what "observe" should conclude. Two of
the five criteria were already failing at plan time (top5_concentration=
52.0% vs. 40% threshold; clean_cohort_pf=0.914 vs. 1.0 threshold), and
nothing in the plan defined what to do if they were *still* failing on
2026-09-05 -- there was no mechanism to even measure "improving" vs.
"stuck" without manually re-running check_promotion_readiness() and
comparing by memory each time.

This script closes that gap:
  1. Captures a timestamped JSON snapshot of promotion_gate.
     evaluate_promotion_readiness()'s output (reusing scripts/check_go_no_
     go.py's check_promotion_readiness() so the same code path is used).
  2. Appends to data/audits/promotion_gate_snapshots/ (one file per day).
  3. `--evaluate` mode reads all snapshots in the observation window and
     classifies the trend for each of the 5 numeric criteria
     (top5_concentration, clean_cohort_pf, portfolio_beta -- pairwise_
     correlation and cluster_cap are boolean/pass-fail and reported as-is)
     against explicit branch conditions defined in EVALUATE_BRANCH_RULES
     below, producing an explicit (a)/(b)/(c) recommendation instead of an
     open-ended "look at the numbers and decide".

Explicit branch conditions (see docs/console_improvement_tasks.md R5-v2
"穴2 対応" for the full rationale)
-----------------------------------------------------------------------
For each of top5_concentration and clean_cohort_pf (the two criteria that
were already failing at plan time):
  (a) IMPROVING & ON TRACK: trend is monotonically moving toward the
      threshold AND is within IMPROVING_TOLERANCE_PCT of passing by the
      final snapshot -> recommend extending observation, no gate change.
  (b) STUCK / NOT IMPROVING: value has not moved meaningfully (within
      STUCK_TOLERANCE of its first-snapshot value) across the whole
      window -> recommend actively addressing root cause (e.g. reducing
      new BUY concentration) rather than continuing to just observe.
  (c) WORSENING: trend is moving away from the threshold -> recommend
      immediate intervention before 09-15 real-trade launch decision.

Usage:
    # Run once per day during the observation window (cron):
    python scripts/capture_promotion_gate_snapshot.py

    # At the end of the window, evaluate the trend across all snapshots:
    python scripts/capture_promotion_gate_snapshot.py --evaluate
    python scripts/capture_promotion_gate_snapshot.py --evaluate --since 2026-08-24
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # for `console.*` imports

SNAPSHOT_DIR = ROOT / "data" / "audits" / "promotion_gate_snapshots"

# --- Branch-condition thresholds (see module docstring) --------------------
IMPROVING_TOLERANCE_PCT = 10.0  # within 10% of threshold-crossing counts as "on track"
STUCK_TOLERANCE_PCT = 3.0       # movement smaller than this (relative) counts as "no real change"


def capture_snapshot() -> dict:
    """Run check_promotion_readiness() (reusing scripts/check_go_no_go.py's
    implementation) and write a timestamped snapshot to SNAPSHOT_DIR.
    Returns the snapshot dict that was written (or an error-shaped dict on
    failure -- never raises, since this is meant to run unattended in cron).
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    try:
        import importlib.util
        _spec = importlib.util.spec_from_file_location(
            "check_go_no_go", ROOT / "scripts" / "check_go_no_go.py"
        )
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        promotion = _mod.check_promotion_readiness()
    except Exception as exc:
        promotion = {"error": {"label": "capture_error", "pass": False, "actual": str(exc)}}

    snapshot = {
        "captured_at": now.isoformat(),
        "date": now.date().isoformat(),
        "promotion": promotion,
    }

    out_path = SNAPSHOT_DIR / f"snapshot_{now.strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    return snapshot


def load_snapshots(since: str | None = None) -> list[dict]:
    """Load all captured snapshots, optionally filtered to date >= since
    (YYYY-MM-DD). Sorted ascending by captured_at."""
    if not SNAPSHOT_DIR.exists():
        return []
    snapshots = []
    for path in sorted(SNAPSHOT_DIR.glob("snapshot_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if since and data.get("date", "") < since:
            continue
        snapshots.append(data)
    snapshots.sort(key=lambda s: s.get("captured_at", ""))
    return snapshots


def _extract_numeric_actual(promotion: dict, criterion_name: str) -> float | None:
    """Extract a numeric value from a promotion criterion's 'actual' field
    for trend analysis. Handles the '52.0%' / '0.914' / '0.704' string/float
    formats used by promotion_gate.py's criteria. Returns None if the
    criterion is missing, unavailable, or its 'actual' isn't numeric
    (e.g. pairwise_correlation's list-of-pairs or cluster_cap's list)."""
    if criterion_name not in promotion:
        return None
    row = promotion[criterion_name]
    actual = row.get("actual")
    if actual is None or isinstance(actual, list):
        return None
    if isinstance(actual, (int, float)):
        return float(actual)
    if isinstance(actual, str):
        cleaned = actual.rstrip("%")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def classify_trend(
    values: list[float],
    threshold: float,
    direction: str,
) -> dict:
    """Classify a metric's trend against explicit branch conditions.

    Args:
        values: chronological list of the metric's value at each snapshot.
        threshold: the pass/fail threshold from promotion_gate.py.
        direction: "lower_is_better" (e.g. top5_concentration, must be
            <= threshold) or "higher_is_better" (e.g. clean_cohort_pf,
            must be >= threshold).

    Returns:
        {"classification": "improving"|"stuck"|"worsening"|"insufficient_data"|"passing",
         "first_value", "last_value", "delta", "gap_to_threshold_pct", "recommendation"}
    """
    if len(values) < 2:
        return {
            "classification": "insufficient_data",
            "first_value": values[0] if values else None,
            "last_value": values[0] if values else None,
            "delta": None,
            "gap_to_threshold_pct": None,
            "recommendation": "Need at least 2 snapshots to classify a trend; keep capturing daily.",
        }

    first_value = values[0]
    last_value = values[-1]
    delta = last_value - first_value

    if direction == "lower_is_better":
        is_passing = last_value <= threshold
        moving_toward_pass = delta < 0  # decreasing is good
        gap = last_value - threshold
    else:
        is_passing = last_value >= threshold
        moving_toward_pass = delta > 0  # increasing is good
        gap = threshold - last_value

    gap_to_threshold_pct = (abs(gap) / threshold * 100) if threshold else None

    if is_passing:
        classification = "passing"
        recommendation = "Criterion currently passing -- maintain, no action needed."
    else:
        relative_delta_pct = (abs(delta) / abs(first_value) * 100) if first_value else 0.0
        if relative_delta_pct < STUCK_TOLERANCE_PCT:
            classification = "stuck"
            recommendation = (
                "(b) STUCK: value has not moved meaningfully across the observation "
                "window. Recommend actively addressing root cause (e.g. reduce new "
                "BUY concentration / re-examine clean-cohort strategy performance) "
                "rather than continuing to just observe."
            )
        elif moving_toward_pass:
            if gap_to_threshold_pct is not None and gap_to_threshold_pct <= IMPROVING_TOLERANCE_PCT:
                classification = "improving"
                recommendation = (
                    "(a) IMPROVING & ON TRACK: trend is moving toward the threshold and "
                    "is within tolerance of passing. Recommend extending observation, "
                    "no gate change needed yet."
                )
            else:
                classification = "improving"
                recommendation = (
                    "(a) IMPROVING but not yet close to threshold: trend is moving in "
                    "the right direction. Recommend continuing observation through the "
                    "full window before deciding."
                )
        else:
            classification = "worsening"
            recommendation = (
                "(c) WORSENING: trend is moving away from the threshold. Recommend "
                "immediate intervention before the 09-15 real-trade launch decision "
                "(e.g. review new BUY allocation logic, do not treat this as "
                "self-correcting)."
            )

    return {
        "classification": classification,
        "first_value": first_value,
        "last_value": last_value,
        "delta": round(delta, 4),
        "gap_to_threshold_pct": round(gap_to_threshold_pct, 2) if gap_to_threshold_pct is not None else None,
        "recommendation": recommendation,
    }


# Criteria to trend-analyze, with their promotion_gate.py field name,
# threshold, and directionality. cluster_cap and pairwise_correlation are
# intentionally excluded -- they are boolean pass/fail with list-shaped
# "actual" fields (over-cap cluster names / high-correlation pairs), not
# continuous metrics with a meaningful trend to plot.
TREND_CRITERIA = [
    ("top5_concentration", 40.0, "lower_is_better"),
    ("clean_cohort_pf", 1.0, "higher_is_better"),
    ("portfolio_beta", 1.5, "lower_is_better"),
]


def evaluate_trend(snapshots: list[dict]) -> dict:
    """Run classify_trend() for each of TREND_CRITERIA across all snapshots.
    Returns {criterion_name: classify_trend() result}."""
    results = {}
    for criterion_name, threshold, direction in TREND_CRITERIA:
        values = []
        for snap in snapshots:
            promotion = snap.get("promotion") or {}
            val = _extract_numeric_actual(promotion, criterion_name)
            if val is not None:
                values.append(val)
        results[criterion_name] = classify_trend(values, threshold, direction)
    return results


def print_evaluation_report(snapshots: list[dict], trend_results: dict) -> None:
    print("=" * 78)
    print("R5-v2 Promotion Gate — Observation Window Trend Evaluation")
    print("=" * 78)
    print(f"\nSnapshots analyzed: {len(snapshots)}")
    if snapshots:
        print(f"  From: {snapshots[0].get('date')}  To: {snapshots[-1].get('date')}")
    print()

    for criterion_name, _, _ in TREND_CRITERIA:
        result = trend_results.get(criterion_name, {})
        print("-" * 78)
        print(f"{criterion_name}")
        print("-" * 78)
        print(f"  Classification: {result.get('classification', 'unknown').upper()}")
        print(f"  First value: {result.get('first_value')}   Last value: {result.get('last_value')}")
        print(f"  Delta: {result.get('delta')}")
        if result.get("gap_to_threshold_pct") is not None:
            print(f"  Gap to threshold: {result['gap_to_threshold_pct']}%")
        print(f"  Recommendation: {result.get('recommendation')}")
        print()

    print("=" * 78)
    print("Overall summary")
    print("=" * 78)
    worsening = [k for k, v in trend_results.items() if v.get("classification") == "worsening"]
    stuck = [k for k, v in trend_results.items() if v.get("classification") == "stuck"]
    improving = [k for k, v in trend_results.items() if v.get("classification") == "improving"]
    passing = [k for k, v in trend_results.items() if v.get("classification") == "passing"]

    if worsening:
        print(f"  ⚠️  WORSENING criteria (immediate attention): {', '.join(worsening)}")
    if stuck:
        print(f"  ⚠️  STUCK criteria (root-cause action needed): {', '.join(stuck)}")
    if improving:
        print(f"  ℹ️  IMPROVING criteria (continue observing): {', '.join(improving)}")
    if passing:
        print(f"  ✅ PASSING criteria: {', '.join(passing)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="R5-v2 promotion gate snapshot capture / trend evaluation")
    parser.add_argument("--evaluate", action="store_true", help="Evaluate trend across captured snapshots instead of capturing a new one")
    parser.add_argument("--since", type=str, default=None, help="Only include snapshots on/after YYYY-MM-DD (evaluate mode)")
    args = parser.parse_args()

    if args.evaluate:
        snaps = load_snapshots(since=args.since)
        if not snaps:
            print("No snapshots found. Run without --evaluate first to start capturing.")
            sys.exit(1)
        trend = evaluate_trend(snaps)
        print_evaluation_report(snaps, trend)
    else:
        snap = capture_snapshot()
        print(f"Captured snapshot: {snap.get('date')} {snap.get('captured_at')}")
        promotion = snap.get("promotion") or {}
        for name, row in promotion.items():
            mark = "✅" if row.get("pass") else "❌"
            print(f"  {mark} {name}: {row.get('actual')}")
