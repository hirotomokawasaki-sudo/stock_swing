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


def _needs_peak_price_fix(trade: dict) -> bool:
    """Detect missing or obviously mis-scaled peak prices on open trades."""
    if trade.get("status") != "open":
        return False
    peak = float(trade.get("peak_price") or 0)
    entry = float(trade.get("entry_price") or 0)
    if peak <= 0:
        return True
    if entry <= 0:
        return False
    ratio = peak / entry
    return ratio > 5 or ratio < 0.2


def _normalize_peak_price(peak: float | None, backup_entry: float, current_entry: float) -> float | None:
    """Scale a restored peak_price if the rebuilt entry was corrected by /10 or /100."""
    if peak is None:
        return None
    if peak <= 0 or backup_entry <= 0 or current_entry <= 0:
        if current_entry > 0:
            for factor in (10, 100):
                candidate = peak / factor
                if current_entry * 0.95 <= candidate <= current_entry * 3:
                    return round(candidate, 4)
        return peak

    entry_ratio = backup_entry / current_entry
    for factor in (10, 100):
        if abs(entry_ratio - factor) / factor > 0.05:
            continue
        candidate = peak / factor
        if candidate >= current_entry * 0.95:
            return round(candidate, 4)
    for factor in (10, 100):
        candidate = peak / factor
        if current_entry * 0.95 <= candidate <= current_entry * 3:
            return round(candidate, 4)
    return peak


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
    bad = [t.get("symbol", "?") for t in open_trades if _needs_peak_price_fix(t)]
    if bad:
        return [f"peak_price missing or mis-scaled on {len(bad)}/{len(open_trades)} open trades: {', '.join(dict.fromkeys(bad))}"]
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
        if not _needs_peak_price_fix(trade):
            continue
        sym = trade.get("symbol", "")
        idx = cursor[sym]
        bak_lots = backup_open.get(sym, [])
        peak = None
        backup_entry = 0.0
        if idx < len(bak_lots):
            peak = bak_lots[idx].get("peak_price")
            backup_entry = float(bak_lots[idx].get("entry_price") or 0)
        cursor[sym] += 1

        entry_price = float(trade.get("entry_price") or 0)
        normalized_peak = _normalize_peak_price(peak, backup_entry, entry_price)
        trade["peak_price"] = normalized_peak if normalized_peak else trade.get("entry_price", 0)
        source = "backup" if normalized_peak else "entry_price"
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
