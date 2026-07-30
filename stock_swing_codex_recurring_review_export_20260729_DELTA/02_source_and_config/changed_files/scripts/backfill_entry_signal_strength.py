#!/usr/bin/env python3
"""Backfill entry_signal_strength for existing trades in pnl_state.json.

Restoration priority (highest first):
  1. trade_events.jsonl payload.signal_strength   (future events post-2026-07-28)
  2. data/decisions/<decision_id>.json signal_strength  (historical decision files)

The trade_id format is "{symbol}-{decision_id[:8]}", so we can decode the
decision_id prefix from the trade_opened event and find the matching decision file.

Usage:
    python scripts/backfill_entry_signal_strength.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

STATE_FILE = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
EVENTS_FILE = PROJECT_ROOT / "data" / "tracking" / "trade_events.jsonl"
DECISIONS_DIR = PROJECT_ROOT / "data" / "decisions"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_ess_from_events() -> dict[str, float]:
    """broker_order_id -> signal_strength from trade_events.jsonl payload."""
    result: dict[str, float] = {}
    if not EVENTS_FILE.exists():
        return result
    with EVENTS_FILE.open(encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "trade_opened":
                continue
            bid = ev.get("broker_order_id", "")
            if not bid:
                continue
            ss = ev.get("payload", {}).get("signal_strength")
            if ss is not None:
                try:
                    result[bid] = float(ss)
                except (TypeError, ValueError):
                    pass
    return result


def _build_decision_index(decisions_dir: Path | None = None) -> dict[str, Path]:
    """Map decision_id[:8] prefix -> decision file path.

    Scans data/decisions/*.json and indexes by 8-char prefix.
    If multiple files share the same prefix, the most recent is kept.
    """
    decisions_dir = decisions_dir or DECISIONS_DIR
    index: dict[str, Path] = {}
    if not decisions_dir.exists():
        return index
    for f in sorted(decisions_dir.glob("decision_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            did = data.get("decision_id", "")
            if len(did) >= 8:
                prefix = did[:8]
                # Later (sorted) file wins for same prefix (should be rare/none)
                index[prefix] = f
        except Exception:
            pass
    return index


def _load_ess_from_decisions(events_file: Path, decisions_dir: Path) -> dict[str, float]:
    """broker_order_id -> signal_strength via trade_events trade_id + decision files.

    trade_id = "{symbol}-{decision_id[:8]}"
    So we can extract the decision_id prefix from each trade_opened event's trade_id.
    """
    if not events_file.exists() or not decisions_dir.exists():
        return {}

    decision_index = _build_decision_index(decisions_dir)

    result: dict[str, float] = {}
    with events_file.open(encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "trade_opened":
                continue
            bid = ev.get("broker_order_id", "")
            if not bid:
                continue
            trade_id = ev.get("trade_id", "")
            if not trade_id:
                continue
            # trade_id = SYMBOL-decisionprefix (e.g. "KLAC-4bb67819")
            parts = trade_id.split("-", 1)
            if len(parts) < 2:
                continue
            prefix = parts[1]
            if len(prefix) < 8:
                continue
            prefix8 = prefix[:8]
            dec_file = decision_index.get(prefix8)
            if dec_file is None:
                continue
            try:
                dec = json.loads(dec_file.read_text(encoding="utf-8"))
                ss = dec.get("signal_strength")
                if ss is not None:
                    result[bid] = float(ss)
            except Exception:
                pass

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill entry_signal_strength in pnl_state.json")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    if not STATE_FILE.exists():
        print(f"ERROR: {STATE_FILE} not found")
        return

    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    trades = data.get("trades", [])

    print(f"Trades in pnl_state.json: {len(trades)}")

    # Build ESS lookup: events payload first (priority 1)
    ess_from_events = _load_ess_from_events()
    print(f"  ESS from trade_events payload: {len(ess_from_events)} entries")

    # Decision file lookup (priority 2 — fills gaps not covered by events payload)
    ess_from_decisions = _load_ess_from_decisions(EVENTS_FILE, DECISIONS_DIR)
    print(f"  ESS from decision files:        {len(ess_from_decisions)} entries")

    # Merge: events payload wins
    ess_merged: dict[str, float] = {**ess_from_decisions, **ess_from_events}
    print(f"  ESS merged total:               {len(ess_merged)} unique broker_order_ids")

    # Count current state
    already_set = sum(1 for t in trades if t.get("entry_signal_strength") is not None)
    print(f"\nCurrently set:  {already_set}/{len(trades)}")

    updated = 0
    skipped_no_match = 0
    for trade in trades:
        if trade.get("entry_signal_strength") is not None:
            continue  # already has a value — do not overwrite
        bid = trade.get("broker_order_id", "")
        if not bid or bid not in ess_merged:
            skipped_no_match += 1
            continue
        ess = round(ess_merged[bid], 4)
        if not args.dry_run:
            trade["entry_signal_strength"] = ess
        else:
            print(f"  [dry-run] Would set {trade.get('symbol')} broker={bid[:8]} → ESS={ess}")
        updated += 1

    print(f"Updated:        {updated}")
    print(f"No match found: {skipped_no_match}")

    if args.dry_run:
        print("\n[dry-run] No changes written.")
        return

    if updated == 0:
        print("Nothing to update.")
        return

    # Backup before writing
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = STATE_FILE.parent / f"pnl_state.backup_ess_backfill_{ts}.json"
    shutil.copy2(STATE_FILE, backup)
    print(f"\nBackup: {backup.name}")

    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Wrote pnl_state.json ({updated} trades updated)")


if __name__ == "__main__":
    main()
