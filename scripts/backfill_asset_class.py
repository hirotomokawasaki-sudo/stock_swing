#!/usr/bin/env python3
"""R0-v2-B: Backfill asset_class on closed trades from symbol_registry.yaml.

Fills asset_class='stock' or 'etf' for closed trades that have
asset_class=None/'unknown'/missing. Uses symbol_registry.yaml as the
authoritative source. Only closed trades are touched; open/quarantined
trades are left unchanged.

Usage:
    python3 scripts/backfill_asset_class.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

STATE_PATH  = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
REGISTRY    = PROJECT_ROOT / "config" / "reference" / "symbol_registry.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    args = parser.parse_args()

    # Load registry
    reg_data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    syms_ac: dict[str, str] = {
        sym: info.get("asset_class", "unknown")
        for sym, info in reg_data.get("symbols", {}).items()
    }

    # Load state
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    trades = state.get("trades", [])

    fixed = 0
    skipped_no_reg = []
    for t in trades:
        if t.get("status") != "closed":
            continue
        ac = t.get("asset_class")
        if ac and ac != "unknown":
            continue  # already set

        sym = t.get("symbol", "")
        if sym not in syms_ac:
            skipped_no_reg.append(sym)
            continue

        new_ac = syms_ac[sym]
        if not args.dry_run:
            t["asset_class"] = new_ac
        fixed += 1

    # Summary
    still_unknown = sum(
        1 for t in trades
        if t.get("status") == "closed"
        and (not t.get("asset_class") or t.get("asset_class") == "unknown")
    )
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}asset_class backfill:")
    print(f"  fixed          : {fixed}")
    print(f"  not in registry: {len(skipped_no_reg)}{(' → ' + str(sorted(set(skipped_no_reg)))) if skipped_no_reg else ''}")
    print(f"  still unknown  : {still_unknown if not args.dry_run else '(dry-run)'}")

    if args.dry_run:
        print("  (no changes written)")
        return 0

    # Atomic write
    fd, tmp = tempfile.mkstemp(
        prefix=".pnl_state.", suffix=".tmp",
        dir=str(STATE_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STATE_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    print(f"  written to: {STATE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
