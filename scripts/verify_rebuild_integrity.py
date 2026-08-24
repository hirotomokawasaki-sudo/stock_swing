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


# ---------------------------------------------------------------------------
# R0-v2-B: Ledger Invariant Checks (added 2026-07-21)
# ---------------------------------------------------------------------------

def check_closed_quarantine_overlap(state: dict) -> list[str]:
    """INVARIANT: closed ∩ quarantined_trades = ∅

    Root cause of past violation: migrate_quarantine_invalid_trades added trades
    to quarantined_trades but forgot to remove them from state.trades (closed).

    BUG FIX (2026-08-24, found while investigating a 2026-08-24 rebuild that
    this function flagged as having 3 overlapping trades -- ADBE/AMAT -- which
    turned out to be a FALSE POSITIVE): this function used to key overlap
    detection on `trade_id` (e.g. "broker_match_0007_AMAT"), a sequential
    index string that rebuild_pnl_state_from_broker.py RE-ASSIGNS on every
    run based on iteration order over that run's fetched broker fills. After
    a rebuild whose fetched order set differs even slightly from a prior run
    (e.g. because a since-fixed bug like the 2026-08-23 pagination/partial-
    fill bugs changed which orders got matched), the SAME trade_id string can
    end up pointing to a COMPLETELY DIFFERENT real trade than the one
    recorded under that trade_id in quarantined_trades from a prior, buggy
    rebuild -- a coincidental string collision, not a genuine duplicate.
    scripts/audit_trades_with_market_data.py's check_ledger_invariants()
    already fixed this exact issue on 2026-07-28 (see its own docstring
    comment) by keying on the immutable broker-assigned
    (broker_order_id, exit_broker_order_id) pair instead -- this function was
    never updated to match at the time, so the fix regressed here. Now uses
    the same (broker_order_id, exit_broker_order_id) pair identity.
    """
    trades = state.get("trades", [])
    quar_pairs = {
        (
            t.get("broker_order_id") or t.get("entry_broker_order_id") or "",
            t.get("exit_broker_order_id") or "",
        )
        for t in state.get("quarantined_trades", [])
    }
    # Only a pair with both IDs present is a meaningful identity; two trades
    # that both happen to have empty broker_order_id/exit_broker_order_id
    # (e.g. malformed/legacy records) must never be treated as "the same
    # trade" merely because they share the key ("", "").
    quar_pairs.discard(("", ""))
    closed_overlap = [
        t for t in trades
        if t.get("status") == "closed"
        and (t.get("broker_order_id") or "", t.get("exit_broker_order_id") or "") in quar_pairs
    ]
    if closed_overlap:
        syms = ", ".join(sorted({t.get("symbol", "?") for t in closed_overlap}))
        return [
            f"INVARIANT FAIL: closed/quarantine overlap = {len(closed_overlap)} trades "
            f"({syms}). Remove these from state.trades (closed) — they are already quarantined."
        ]
    return []


def check_reversed_chronology(state: dict) -> list[str]:
    """INVARIANT: For all closed trades, entry_time ≤ exit_time (holding_days ≥ 0).

    Root cause of past violation: rebuild FIFO matching assigned wrong lot pairing,
    resulting in entry_time > exit_time (negative holding_days).
    """
    from datetime import datetime
    trades = state.get("trades", [])
    reversed_trades = []
    for t in trades:
        if t.get("status") != "closed":
            continue
        et, xt = t.get("entry_time", ""), t.get("exit_time", "")
        if not et or not xt:
            continue
        try:
            e = datetime.fromisoformat(str(et).replace("Z", "+00:00"))
            x = datetime.fromisoformat(str(xt).replace("Z", "+00:00"))
            if e > x:
                reversed_trades.append(t.get("trade_id", "?"))
        except Exception:
            pass
    if reversed_trades:
        return [
            f"INVARIANT FAIL: reversed chronology (entry > exit) = {len(reversed_trades)} trades. "
            f"These must be quarantined or have their FIFO lot assignment corrected."
        ]
    return []


def check_holding_days_missing(state: dict) -> list[str]:
    """WARNING (not hard fail): closed trades with holding_days = None.

    A small number may be acceptable if they are in the process of being fixed.
    Threshold: 0 after R0-v2-B, warn if > 0.
    """
    trades = state.get("trades", [])
    missing = [t for t in trades if t.get("status") == "closed" and t.get("holding_days") is None]
    if missing:
        return [
            f"WARNING: {len(missing)} closed trades have holding_days = None. "
            f"Run R0-v2-B fix to compute from entry_time/exit_time."
        ]
    return []


def check_pnl_consistency(state: dict) -> list[str]:
    """INVARIANT: sum(closed.pnl) ≈ state.cumulative_realized_pnl (tolerance $1).

    This catches double-counting or missed trades in the running total.
    """
    trades = state.get("trades", [])
    closed_sum = sum(t.get("pnl", 0) or 0 for t in trades if t.get("status") == "closed")
    cum = state.get("cumulative_realized_pnl", 0) or 0
    diff = abs(closed_sum - cum)
    if diff > 1.0:
        return [
            f"INVARIANT FAIL: sum(closed.pnl) = ${closed_sum:+,.2f} "
            f"but cumulative_realized_pnl = ${cum:+,.2f} (diff=${diff:,.2f}). "
            f"Rebuild may have corrupted the running total."
        ]
    return []


# Issue-prefix -> whether this script's --fix path can actually resolve it.
# BUG FIX (2026-08-24): previously main() computed `total_fixed` only from
# the two auto-fixable categories (daily_snapshots / peak_price) and then
# unconditionally `return 0`-ed once ANY fix was applied -- so a rebuild
# with, say, daily_snapshots wiped (auto-fixed) AND a genuine closed/
# quarantine overlap (NOT auto-fixable) would print "Saved ... N field(s)
# restored" followed by the CALLER (rebuild_pnl_state_from_broker.py)
# printing "✅ Post-rebuild integrity check passed", silently hiding the
# unresolved overlap/reversed-chronology/pnl-consistency invariant
# failures. Discovered 2026-08-24 investigating a rebuild that printed
# "passed" while 3 overlap + 1 reversed-chronology issues were still
# present in the written pnl_state.json (the overlap 3 were themselves a
# separate false-positive bug, see check_closed_quarantine_overlap()'s
# docstring -- but the reversed-chronology 1 was real and still got
# silently reported as "passed").
_AUTO_FIXABLE_PREFIXES = ("daily_snapshots", "peak_price")


def _is_auto_fixable(issue_msg: str) -> bool:
    return any(prefix in issue_msg for prefix in _AUTO_FIXABLE_PREFIXES)


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

    def run_all_checks(s: dict) -> list[str]:
        found: list[str] = []
        found += check_daily_snapshots(s, backup)
        found += check_peak_prices(s)
        # R0-v2-B: ledger invariant checks
        found += check_closed_quarantine_overlap(s)
        found += check_reversed_chronology(s)
        found += check_holding_days_missing(s)
        found += check_pnl_consistency(s)
        return found

    issues = run_all_checks(state)

    trades_all = state.get("trades", [])
    open_count = len([t for t in trades_all if t.get("status") == "open"])
    closed_count = len([t for t in trades_all if t.get("status") == "closed"])
    quar_count = len(state.get("quarantined_trades", []))
    snap_count = len(state.get("daily_snapshots", []))

    print()
    print("=" * 60)
    print("POST-REBUILD INTEGRITY CHECK")
    print("=" * 60)
    print(f"  Open trades      : {open_count}")
    print(f"  Closed trades    : {closed_count}")
    print(f"  Quarantined      : {quar_count}")
    print(f"  daily_snapshots  : {snap_count}")

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

    # --- Apply fixes (only for the auto-fixable categories) ---
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
        print("Nothing to save — no fields were actually fixable by this script.")

    # --- Re-check after fixing: only report success if EVERY issue that was
    # --- found is now gone (not just the auto-fixable subset) ---
    remaining = run_all_checks(state)
    remaining_hard = [msg for msg in remaining if "WARNING" not in msg]
    remaining_warnings = [msg for msg in remaining if "WARNING" in msg]

    print()
    if not remaining_hard:
        if remaining_warnings:
            print(f"✅ All INVARIANT-level checks passed ({len(remaining_warnings)} non-blocking warning(s) remain):")
            for msg in remaining_warnings:
                print(f"  - {msg}")
        else:
            print("✅ All checks passed after auto-fix — no issues remain.")
        return 0

    print(f"❌ {len(remaining_hard)} unresolved issue(s) require MANUAL action "
          f"(this script cannot auto-fix these):")
    for msg in remaining_hard:
        print(f"  - {msg}")
    print()
    print("Do NOT treat this rebuild as clean until these are resolved. See:")
    print("  - closed/quarantine overlap → investigate manually; verify with the")
    print("    (broker_order_id, exit_broker_order_id) pair, not trade_id, before")
    print("    assuming a real duplicate (see check_closed_quarantine_overlap docstring)")
    print("  - reversed chronology → python scripts/migrate_quarantine_invalid_trades.py")
    print("  - pnl consistency → investigate cumulative_realized_pnl computation")
    return 1


if __name__ == "__main__":
    sys.exit(main())
