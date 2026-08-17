"""R4-v2 residual (2026-08-17): confidence-calibration readiness check.

Background
----------
R4-v2's "confidence" calibration plan (defining `confidence` as a calibration
-able probability, instead of the current fixed multipliers --
`signal_strength * 0.85` for breakout_momentum_v1, `signal_strength * 0.9`
for event_swing_v1, fixed `0.85`/`0.90` for exit strategies) requires a
population of decisions where `confidence`'s actual sizing effect
(`confidence_multiplier`, see `PositionSizingResult`/`DecisionRecord.sizing`)
was recorded, so the relationship between confidence and downstream sizing
-- and eventually PnL -- can be analyzed.

That recording only started on 2026-08-14 (see docs/console_improvement_
tasks.md "穴3" gap analysis and its `PositionSizingResult.confidence_
multiplier` field). Prior to that date, no decision record has this field
at all, so it cannot be backfilled retroactively.

The 2026-08-14 gap analysis explicitly recommended waiting for roughly 100
such decisions to accumulate before attempting the calibration work, since
attempting it on a handful of decisions would not be statistically
meaningful and confidence directly affects live position sizing (not a
pure-observability change).

This script is the single source of truth for "is there enough recorded
confidence_multiplier history to start R4-v2 confidence calibration",
exactly analogous to check_r8v2_ml_readiness.py's role for R8-v2 ML
readiness. It counts decision records (from data/decisions/*.json) that
have `evidence.sizing.confidence_multiplier` recorded, not just any
decision or trade count.

Usage:
    python scripts/check_confidence_calibration_readiness.py [--save]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent

# When confidence_multiplier recording began (see docs gap #3, 2026-08-14).
RECORDING_STARTED_DATE = "2026-08-14"

# Recommended minimum sample size before attempting calibration analysis
# (docs/console_improvement_tasks.md "穴3", 2026-08-14: "目安 100件程度").
CALIBRATION_SAMPLE_THRESHOLD = 100


def _load_decisions(decisions_dir: Path) -> list[dict]:
    decisions: list[dict] = []
    if not decisions_dir.exists():
        return decisions
    for path in sorted(decisions_dir.glob("*.json")):
        try:
            decisions.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return decisions


def check_readiness(decisions_dir: Path | None = None) -> dict:
    """Return confidence-calibration readiness based on the count of
    decision records with a recorded `confidence_multiplier`.

    Args:
        decisions_dir: Override for the decisions directory (for testing).
            Defaults to data/decisions/ under the project root.
    """
    decisions_dir = decisions_dir or (ROOT / "data" / "decisions")
    decisions = _load_decisions(decisions_dir)

    total_since_recording = 0
    with_multiplier = 0
    multiplier_counts: Counter = Counter()
    confidence_values: list[float] = []

    for d in decisions:
        generated_at = d.get("generated_at") or ""
        if generated_at < RECORDING_STARTED_DATE:
            continue
        total_since_recording += 1

        evidence = d.get("evidence")
        sizing = evidence.get("sizing") if isinstance(evidence, dict) else None
        confidence_multiplier = sizing.get("confidence_multiplier") if isinstance(sizing, dict) else None

        if confidence_multiplier is not None:
            with_multiplier += 1
            multiplier_counts[round(float(confidence_multiplier), 2)] += 1

        confidence = d.get("confidence")
        if confidence is not None:
            confidence_values.append(float(confidence))

    calibration_ready = with_multiplier >= CALIBRATION_SAMPLE_THRESHOLD

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "recording_started_date": RECORDING_STARTED_DATE,
        "decisions_since_recording_started": total_since_recording,
        "decisions_with_confidence_multiplier": with_multiplier,
        "calibration_sample_threshold": CALIBRATION_SAMPLE_THRESHOLD,
        "calibration_ready": calibration_ready,
        "confidence_multiplier_distribution": dict(multiplier_counts),
        "confidence_value_count": len(confidence_values),
        "confidence_min": round(min(confidence_values), 4) if confidence_values else None,
        "confidence_max": round(max(confidence_values), 4) if confidence_values else None,
    }


def print_report(result: dict) -> None:
    print("=" * 78)
    print("R4-v2 Confidence Calibration Readiness Check")
    print("=" * 78)
    print()
    print(f"  confidence_multiplier recording started: {result['recording_started_date']}")
    print(f"  Decisions since recording started:        {result['decisions_since_recording_started']}")
    print(f"  ...with confidence_multiplier recorded:   {result['decisions_with_confidence_multiplier']}")
    print()
    print(f"  confidence_multiplier distribution: {result['confidence_multiplier_distribution']}")
    print(f"  confidence value range: {result['confidence_min']} - {result['confidence_max']} "
          f"(n={result['confidence_value_count']})")
    print()
    print("-" * 78)
    mark = "✅" if result["calibration_ready"] else "❌"
    print(f"  {mark} Calibration ready (>= {result['calibration_sample_threshold']} recorded): "
          f"{result['decisions_with_confidence_multiplier']}/{result['calibration_sample_threshold']}")
    print("-" * 78)
    print()
    if not result["calibration_ready"]:
        remaining = result["calibration_sample_threshold"] - result["decisions_with_confidence_multiplier"]
        print(f"  ⚠️  R4-v2 confidence calibration remains NOT_READY. Need {remaining} more "
              f"decisions with confidence_multiplier recorded before this work should start.")
        print("  Note: confidence directly affects live position sizing via confidence_multiplier "
              "-- changing its definition before enough data accumulates would be an unvalidated "
              "behavior change, not a pure observability addition.")


if __name__ == "__main__":
    save = "--save" in sys.argv
    result = check_readiness()
    print_report(result)

    if save:
        out_path = ROOT / "reports" / "confidence_calibration_readiness.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[saved] {out_path}")

    sys.exit(0 if result["calibration_ready"] else 1)
