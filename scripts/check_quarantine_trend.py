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

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from stock_swing.tracking.compatibility import read_analysis_snapshot
from stock_swing.tracking.ledger_transaction import LedgerConflict

STATE_PATH = ROOT / "data" / "tracking" / "pnl_state.json"
HISTORY_PATH = ROOT / "data" / "audits" / "quarantine_trend_history.jsonl"


def load_quarantine_snapshot() -> dict:
    """Return the current quarantine count and newest quarantined trade's
    entry_time, from data/tracking/pnl_state.json.
    """
    state, context = read_analysis_snapshot(STATE_PATH)
    quarantined = state.get("quarantined_trades", [])

    entry_times = [t.get("entry_time") for t in quarantined if t.get("entry_time") is not None]
    newest_entry_time = max(entry_times, key=_timestamp) if entry_times else None

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "quarantine_count": len(quarantined),
        "newest_quarantined_entry_time": newest_entry_time,
        "measurement_provenance": context,
    }


def _timestamp(value):
    if not isinstance(value, str) or not value:
        raise ValueError("quarantine entry_time must be an aware ISO timestamp or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("quarantine entry_time must be an aware ISO timestamp or null") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("quarantine entry_time must have timezone")
    return parsed


def _snapshot_revision(snapshot):
    if "measurement_provenance" not in snapshot:
        return "legacy"
    context = snapshot["measurement_provenance"]
    if not isinstance(context, dict) or not isinstance(context.get("ledger_revision"), str) or not context["ledger_revision"].strip():
        raise ValueError("quarantine snapshot has invalid measurement_provenance")
    return context["ledger_revision"]


def _validate_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("quarantine history row must be an object")
    count = snapshot.get("quarantine_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("quarantine_count must be a nonnegative integer")
    if "newest_quarantined_entry_time" not in snapshot:
        raise ValueError("quarantine snapshot missing newest_quarantined_entry_time")
    if snapshot["newest_quarantined_entry_time"] is not None:
        _timestamp(snapshot["newest_quarantined_entry_time"])
    _snapshot_revision(snapshot)


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    history = []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                _validate_snapshot(row)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"quarantine history unavailable: invalid row {line_number}: {exc}") from exc
            history.append(row)
    return history


def append_history(snapshot: dict) -> None:
    _validate_snapshot(snapshot)
    load_history()  # Never append a successful observation onto corrupt evidence.
    serialized = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(serialized + "\n")


def evaluate_trend(current: dict, history: list[dict]) -> dict:
    """Compare current snapshot against the most recent prior snapshot in
    history (if any). Returns a dict describing whether quarantine growth
    or a new (newer-than-baseline) quarantine event was detected.
    """
    _validate_snapshot(current)
    for row in history:
        _validate_snapshot(row)
    if not history:
        return {
            "status": "baseline",
            "message": "No prior snapshot to compare against; this becomes the baseline.",
            "count_delta": None,
            "new_quarantine_detected": False,
        }

    previous = history[-1]
    current_revision = _snapshot_revision(current)
    previous_revision = _snapshot_revision(previous)
    if current_revision != previous_revision:
        return {
            "status": "revision_changed",
            "message": f"Ledger revision changed: {previous_revision} -> {current_revision}; "
                       "no cross-revision count delta, growth, improvement, or repair-success inference.",
            "count_delta": None,
            "new_quarantine_detected": False,
        }
    count_delta = current["quarantine_count"] - previous["quarantine_count"]

    new_quarantine_detected = False
    if (
        current["newest_quarantined_entry_time"]
        and previous.get("newest_quarantined_entry_time")
        and _timestamp(current["newest_quarantined_entry_time"]) > _timestamp(previous["newest_quarantined_entry_time"])
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
    print(f"  Measurement revision: {_snapshot_revision(current)}; descriptive only; promotion_ready=False")
    print()
    print(f"  Status: {trend['status'].upper()}")
    print(f"  {trend['message']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Descriptive quarantine trend by ledger revision")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    try:
        current = load_quarantine_snapshot()
        history = load_history()
        trend = evaluate_trend(current, history)
    except (OSError, ValueError, TypeError, LedgerConflict) as exc:
        print(f"UNAVAILABLE: {exc}; quarantine history not refreshed", file=sys.stderr)
        return 2
    print_report(current, trend)

    if args.save:
        append_history(current)
        print(f"\n[saved] appended snapshot to {HISTORY_PATH}")

    return 1 if trend["status"] == "growing" else 0


if __name__ == "__main__":
    sys.exit(main())
