#!/usr/bin/env python3
"""Backfill open_position_count on existing daily_snapshots.

Bug fix (2026-08-13): the console's Open Positions chart was rendering the
*current live* position count for every historical data point instead of
the actual count at that point in time, because DailySnapshot never
recorded it. New snapshots (recorded via PnLTracker.record_daily_snapshot)
now populate this field automatically; this script reconstructs the value
for all pre-existing snapshots from trade entry/exit timestamps so the
chart shows real history instead of gaps for older dates.

For each snapshot's date, a trade counts as "open" on that date if:
  entry_time.date() <= snapshot_date  AND  (exit_time is None OR exit_time.date() > snapshot_date)

This treats the snapshot as an end-of-day reading (consistent with how
record_daily_snapshot computes unrealized_pnl from status == "open" trades,
and how trade_count/realized_pnl are already recomputed per-date in
_enrich_daily_snapshots on the console side).

Usage:
    python scripts/backfill_open_position_count.py [--dry-run] [--backup]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

PNL_STATE_PATH = project_root / "data" / "tracking" / "pnl_state.json"


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def active_on_date(trade: dict[str, Any], date_str: str) -> bool:
    entry_dt = parse_dt(trade.get("entry_time"))
    if entry_dt is None or entry_dt.date().isoformat() > date_str:
        return False
    exit_dt = parse_dt(trade.get("exit_time"))
    return exit_dt is None or exit_dt.date().isoformat() > date_str


def compute_open_counts(trades: list[dict[str, Any]], dates: list[str]) -> dict[str, int]:
    # Exclude quarantined records; they are not real open/closed positions
    # for reporting purposes (consistent with pnl_tracker treatment elsewhere).
    relevant = [t for t in trades if t.get("status") in ("open", "closed")]
    counts: dict[str, int] = {}
    for date_str in dates:
        counts[date_str] = sum(1 for t in relevant if active_on_date(t, date_str))
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing")
    parser.add_argument("--backup", action="store_true", help="Write a timestamped backup before saving")
    parser.add_argument("--state-path", default=str(PNL_STATE_PATH), help="Path to pnl_state.json")
    args = parser.parse_args()

    state_path = Path(args.state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    snapshots = state.get("daily_snapshots", [])
    trades = state.get("trades", [])
    if not snapshots:
        print("No daily_snapshots found; nothing to backfill.")
        return 0

    dates = sorted({str(s.get("date") or "") for s in snapshots if s.get("date")})
    counts = compute_open_counts(trades, dates)

    updated = 0
    already_set = 0
    for snap in snapshots:
        date_str = str(snap.get("date") or "")
        if snap.get("open_position_count") is not None:
            already_set += 1
            continue
        snap["open_position_count"] = counts.get(date_str, 0)
        updated += 1

    print(f"Snapshots total: {len(snapshots)}")
    print(f"Already had open_position_count: {already_set}")
    print(f"Backfilled: {updated}")
    if dates:
        print(f"Date range: {dates[0]} .. {dates[-1]}")

    if args.dry_run:
        print("--dry-run: no changes written.")
        return 0

    if updated == 0:
        print("Nothing to write.")
        return 0

    if args.backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = state_path.with_name(f"{state_path.stem}_backup_open_pos_backfill_{ts}{state_path.suffix}")
        shutil.copy2(state_path, backup_path)
        print(f"Backup written: {backup_path}")

    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote updated state to {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
