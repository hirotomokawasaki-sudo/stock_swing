"""R8-v2 (2026-08-14, roadmap gap #4): ML readiness check using
attributable-origin trade counts, not raw closed-trade counts.

Background
----------
docs/console_improvement_tasks.md's R8-v2 section defines its start
conditions as "clean joinable outcomes >= 300" (simple calibration) and
"clean labels >= 1,000" (ML training). Prior to 2026-08-14 these thresholds
were checked against raw `total_closed` trade counts, which does not
account for whether a trade's origin is even traceable to a strategy
decision in the first place.

Gap #1 of the 2026-08-14 roadmap analysis found that the majority of closed
trades (197/228 as of 2026-08-14) carry original_strategy_id=
"broker_reconstructed" -- reconstructed purely from broker fill history
with no decision_id/run_id/entry_signal_strength, i.e. legitimate realized
P&L with unknown cause. A "clean label" for calibration/ML purposes must be
attributable to an actual strategy decision (so the label's *input features*
can be reconstructed), not just any closed trade with a PnL sign. Simply
waiting for total_closed >= 300 could be satisfied entirely by more
untracked-origin trades accumulating, which would not actually unblock a
meaningful calibration or ML effort.

This script is the single source of truth for R8-v2 readiness going
forward: it counts trades using PnlTracker.get_attribution_quality_
breakdown()'s "attributable" bucket, not the raw "all" count.

Usage:
    python scripts/check_r8v2_ml_readiness.py [--save]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from stock_swing.tracking.pnl_tracker import PnLTracker

CALIBRATION_THRESHOLD = 300
ML_TRAINING_THRESHOLD = 1000


def check_readiness() -> dict:
    """Return R8-v2 readiness status based on attributable (not raw) closed
    trade counts.
    """
    tracker = PnLTracker(ROOT)
    breakdown = tracker.get_attribution_quality_breakdown()

    attributable_count = breakdown["attributable"]["count"]
    untracked_count = breakdown["untracked_origin"]["count"]
    total_count = breakdown["all"]["count"]

    attributable_ratio = (attributable_count / total_count * 100) if total_count else 0.0

    calibration_ready = attributable_count >= CALIBRATION_THRESHOLD
    ml_training_ready = attributable_count >= ML_TRAINING_THRESHOLD

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "attributable_count": attributable_count,
        "untracked_origin_count": untracked_count,
        "total_closed_count": total_count,
        "attributable_ratio_pct": round(attributable_ratio, 1),
        "calibration_threshold": CALIBRATION_THRESHOLD,
        "ml_training_threshold": ML_TRAINING_THRESHOLD,
        "calibration_ready": calibration_ready,
        "ml_training_ready": ml_training_ready,
        "attributable_pf": breakdown["attributable"]["profit_factor"],
        "untracked_origin_pf": breakdown["untracked_origin"]["profit_factor"],
    }


def print_report(result: dict) -> None:
    print("=" * 78)
    print("R8-v2 ML Readiness Check (attributable-origin trades only)")
    print("=" * 78)
    print()
    print(f"  Attributable (clean origin) closed trades: {result['attributable_count']}")
    print(f"  Untracked-origin closed trades:             {result['untracked_origin_count']}")
    print(f"  Total closed trades:                        {result['total_closed_count']}")
    print(f"  Attributable ratio:                         {result['attributable_ratio_pct']}%")
    print()
    print(f"  Attributable PF:      {result['attributable_pf']}")
    print(f"  Untracked-origin PF:  {result['untracked_origin_pf']}")
    print()
    print("-" * 78)
    cal_mark = "✅" if result["calibration_ready"] else "❌"
    ml_mark = "✅" if result["ml_training_ready"] else "❌"
    print(f"  {cal_mark} Calibration ready (attributable >= {result['calibration_threshold']}): "
          f"{result['attributable_count']}/{result['calibration_threshold']}")
    print(f"  {ml_mark} ML training ready (attributable >= {result['ml_training_threshold']}): "
          f"{result['attributable_count']}/{result['ml_training_threshold']}")
    print("-" * 78)
    print()
    if not result["calibration_ready"]:
        remaining = result["calibration_threshold"] - result["attributable_count"]
        print(f"  ⚠️  R8-v2 remains BLOCKED_BY_DATA. Need {remaining} more attributable "
              f"trades before even simple calibration can start.")
        print(f"  Note: total_closed_count reaching {result['calibration_threshold']} is NOT "
              f"sufficient on its own -- only trades attributable to an actual strategy "
              f"decision count (see module docstring).")


if __name__ == "__main__":
    save = "--save" in sys.argv
    result = check_readiness()
    print_report(result)

    if save:
        out_path = ROOT / "reports" / "r8v2_ml_readiness.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[saved] {out_path}")

    sys.exit(0 if result["calibration_ready"] else 1)
