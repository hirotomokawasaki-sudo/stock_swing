#!/usr/bin/env python3
"""Post-rebuild integrity verifier for pnl_state.json.

Checks that a rebuild preserved critical fields that are easy to silently lose:
  1. daily_snapshots  — equity curve history must not be wiped
  2. peak_price       — all open trades must have peak_price set

When run after a rebuild it compares the new state against the most recent
backup and auto-restores any fields that were silently dropped.

Usage
-----
  # Check-only (exit non-zero if issues found):
  python scripts/verify_rebuild_integrity.py

  # Auto-fix: restore missing fields from the latest backup:
  python scripts/verify_rebuild_integrity.py --fix

  # Compare against a specific backup:
  python scripts/verify_rebuild_integrity.py --backup path/to/backup.json --fix
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
BACKUP_DIR = PROJECT_ROOT / "data" / "tracking"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _latest_backup() -> Path | None:
    """Return the most recently created pnl_state_backup_*.json file."""
    backups = sorted(
        BACKUP_DIR.glob("pnl_state_backup_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return backups[0] if backups else None


# ---------------------------------------------------------------------------
# Check functions (return list of issue strings, empty = OK)
# ---------------------------------------------------------------------------

def check_daily_snapshots(state: dict, backup: dict | None) -> list[str]:
    current = state.get("daily_snapshots", [])
    if current:
        return []
    backup_count = len((backup or {}).get("daily_snapshots", []))
    if backup_count > 0:
        return [f"daily_snapshots is EMPTY — backup had {backup_count} entries (silently wiped by rebuild)"]
    return ["daily_snapshots is EMPTY — no backup to compare; may be first run"]


def check_peak_prices(state: dict) -> list[str]:
    open_trades = [t for t in state.get("trades", []) if t.get("status") == "open"]
    missing = [t.get("symbol", "?") for t in open_trades if not t.get("peak_price")]
    if missing:
        return [f"peak_price missing on {len(missing)}/{len(open_trades)} open trades: {', '.join(dict.fromkeys(missing))}"]
    return []


# ---------------------------------------------------------------------------
# Fix functions
# ---------------------------------------------------------------------------

def fix_daily_snapshots(state: dict, backup: dict) -> int:
    """Restore daily_snapshots from backup. Returns count restored."""
    snaps = backup.get("daily_snapshots", [])
    if not snaps:
        print("  WARN: backup has no daily_snapshots either — cannot restore")
        return 0
    state["daily_snapshots"] = snaps
    state["strategy_daily_snapshots"] = backup.get("strategy_daily_snapshots", [])
    print(f"  ✓ Restored daily_snapshots: {len(snaps)} entries")
    return len(snaps)


def fix_peak_prices(state: dict, backup: dict) -> int:
    """
    Restore peak_price for open trades using FIFO match against backup.
    Falls back to entry_price when the backup has no matching lot.
    Returns count of trades fixed.
    """
    # Index backup open trades by symbol (FIFO order by entry_time)
    backup_open: dict[str, list[dict]] = defaultdict(list)
    for t in backup.get("trades", []):
        if t.get("status") == "open":
            backup_open[t["symbol"]].append(t)
    for sym in backup_open:
        backup_open[sym].sort(key=lambda x: x.get("entry_time", ""))

    cursor: dict[str, int] = defaultdict(int)
    fixed = 0

    for trade in state.get("trades", []):
        if trade.get("status") != "open" or trade.get("peak_price"):
            continue
        sym = trade.get("symbol", "")
        idx = cursor[sym]
        bak_lots = backup_open.get(sym, [])
        peak = None
        if idx < len(bak_lots):
            peak = bak_lots[idx].get("peak_price")
        cursor[sym] += 1

        trade["peak_price"] = peak if peak else trade.get("entry_price", 0)
        source = "backup" if peak else "entry_price"
        print(f"  ✓ {sym}: peak_price = {trade['peak_price']:.2f} (from {source})")
        fixed += 1

    return fixed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fix", action="store_true", help="Auto-restore missing fields from latest backup")
    parser.add_argument("--backup", metavar="PATH", help="Backup file to compare/restore from")
    args = parser.parse_args()

    if not STATE_FILE.exists():
        print(f"ERROR: state file not found: {STATE_FILE}")
        return 1

    state = _load_json(STATE_FILE)

    # Resolve backup
    backup_path: Path | None = Path(args.backup) if args.backup else _latest_backup()
    backup: dict | None = _load_json(backup_path) if backup_path else None
    if backup_path:
        print(f"Comparing against backup: {backup_path.name}")
    else:
        print("No backup found — running checks without comparison")

    # --- Run checks ---
    issues: list[str] = []
    issues += check_daily_snapshots(state, backup)
    issues += check_peak_prices(state)

    open_count = len([t for t in state.get("trades", []) if t.get("status") == "open"])
    snap_count = len(state.get("daily_snapshots", []))

    print()
    print("=" * 60)
    print("POST-REBUILD INTEGRITY CHECK")
    print("=" * 60)
    print(f"  Open trades   : {open_count}")
    print(f"  daily_snapshots: {snap_count}")

    if not issues:
        print()
        print("✅ All checks passed — rebuild preserved all critical fields.")
        return 0

    print()
    print(f"⚠️  {len(issues)} issue(s) found:")
    for i, msg in enumerate(issues, 1):
        print(f"  [{i}] {msg}")

    if not args.fix:
        print()
        print("Run with --fix to auto-restore from the latest backup.")
        return 1

    if not backup:
        print()
        print("ERROR: --fix requested but no backup available. Run rebuild with --backup first.")
        return 1

    # --- Apply fixes ---
    print()
    print("Applying fixes...")
    total_fixed = 0

    if any("daily_snapshots" in msg for msg in issues):
        total_fixed += fix_daily_snapshots(state, backup)

    if any("peak_price" in msg for msg in issues):
        total_fixed += fix_peak_prices(state, backup)

    if total_fixed > 0:
        _save_json(STATE_FILE, state)
        print()
        print(f"✅ Saved pnl_state.json ({total_fixed} field(s) restored)")
    else:
        print("Nothing to save — no fields were actually fixable.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
