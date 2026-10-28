"""2026-08-14 (roadmap gap #6): quarantine count trend tracking.

Background
----------
docs/console_improvement_tasks.md's 2026-08-14 roadmap gap analysis flagged
that quarantine count (102 trades as of that date) is displayed in console
health output on every run, but nothing distinguishes "new quarantines
being created by ongoing trading" from "the same historical batch of
101-102 trades sitting there since the 2026-07 ledger repair work"
(RF-1/R0-v2-B etc.). Without that distinction, a genuinely new quarantine
being created today would be invisible -- it would just look like "the
usual number" in the health display.

Real-data finding at implementation time (2026-08-14): all quarantined
trades have entry_time <= 2026-07-22 -- i.e. zero new quarantines have been
created since R0-v2-B's ledger integrity work landed. This script makes
that finding continuously checkable, rather than a one-time manual
observation, by tracking quarantine count + the newest quarantined trade's
entry_time over time (via saved snapshots) and flagging when either the
total count increases OR a trade newer than the last known baseline gets
quarantined.

Usage:
    python scripts/check_quarantine_trend.py [--save]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

STATE_PATH = ROOT / "data" / "tracking" / "pnl_state.json"
HISTORY_PATH = ROOT / "data" / "audits" / "quarantine_trend_history.jsonl"


def load_quarantine_snapshot() -> dict:
    """Return the current quarantine count and newest quarantined trade's
    entry_time, from data/tracking/pnl_state.json.
    """
    with open(STATE_PATH) as f:
        state = json.load(f)
    quarantined = state.get("quarantined_trades", [])

    entry_times = sorted(
        t.get("entry_time") for t in quarantined if t.get("entry_time")
    )
    newest_entry_time = entry_times[-1] if entry_times else None

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "quarantine_count": len(quarantined),
        "newest_quarantined_entry_time": newest_entry_time,
    }


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    history = []
    with open(HISTORY_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                history.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return history


def append_history(snapshot: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")


def evaluate_trend(current: dict, history: list[dict]) -> dict:
    """Compare current snapshot against the most recent prior snapshot in
    history (if any). Returns a dict describing whether quarantine growth
    or a new (newer-than-baseline) quarantine event was detected.
    """
    if not history:
        return {
            "status": "baseline",
            "message": "No prior snapshot to compare against; this becomes the baseline.",
            "count_delta": None,
            "new_quarantine_detected": False,
        }

    previous = history[-1]
    count_delta = current["quarantine_count"] - previous["quarantine_count"]

    new_quarantine_detected = False
    if (
        current["newest_quarantined_entry_time"]
        and previous.get("newest_quarantined_entry_time")
        and current["newest_quarantined_entry_time"] > previous["newest_quarantined_entry_time"]
    ):
        new_quarantine_detected = True
    elif (
        current["newest_quarantined_entry_time"]
        and not previous.get("newest_quarantined_entry_time")
    ):
        new_quarantine_detected = True

    if count_delta > 0 or new_quarantine_detected:
        status = "growing"
        message = (
            f"⚠️ Quarantine count changed: {previous['quarantine_count']} -> "
            f"{current['quarantine_count']} (delta={count_delta:+d}). "
            f"Newest quarantined entry_time: {current['newest_quarantined_entry_time']}. "
            f"This suggests NEW trades are being quarantined by ongoing "
            f"trading, not just the historical 2026-07 batch -- investigate "
            f"the root cause (see pnl_tracker.py's quarantine gate logic)."
        )
    elif count_delta < 0:
        status = "decreased"
        message = (
            f"Quarantine count decreased: {previous['quarantine_count']} -> "
            f"{current['quarantine_count']} (delta={count_delta:+d}). "
            f"Likely a manual data repair / rebuild ran."
        )
    else:
        status = "stable"
        message = "No change since last snapshot -- consistent with the historical-batch-only hypothesis."

    return {
        "status": status,
        "message": message,
        "count_delta": count_delta,
        "new_quarantine_detected": new_quarantine_detected,
        "previous_count": previous["quarantine_count"],
        "previous_newest_entry_time": previous.get("newest_quarantined_entry_time"),
    }


def print_report(current: dict, trend: dict) -> None:
    print("=" * 70)
    print("Quarantine Trend Check")
    print("=" * 70)
    print(f"\n  Current quarantine count: {current['quarantine_count']}")
    print(f"  Newest quarantined entry_time: {current['newest_quarantined_entry_time']}")
    print()
    print(f"  Status: {trend['status'].upper()}")
    print(f"  {trend['message']}")


if __name__ == "__main__":
    save = "--save" in sys.argv

    current = load_quarantine_snapshot()
    history = load_history()
    trend = evaluate_trend(current, history)
    print_report(current, trend)

    if save:
        append_history(current)
        print(f"\n[saved] appended snapshot to {HISTORY_PATH}")

    sys.exit(1 if trend["status"] == "growing" else 0)
