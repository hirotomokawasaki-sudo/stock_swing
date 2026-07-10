#!/usr/bin/env python3
"""F1 migration: quarantine existing closed trades with negative holding_days.

Scans pnl_state.json for closed trades where entry_time > exit_time,
moves them to quarantined_trades, and saves atomically.

Usage:
    python scripts/migrate_quarantine_invalid_trades.py [--dry-run] [--backup]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.tracking.pnl_tracker import _compute_holding_days


def _load_raw(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".migrate_quar.", suffix=".tmp")
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Quarantine invalid closed trades")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--backup", action="store_true", default=True,
                        help="Create timestamped backup before writing (default: true)")
    parser.add_argument("--no-backup", action="store_false", dest="backup")
    args = parser.parse_args()

    state_path = project_root / "data" / "tracking" / "pnl_state.json"
    if not state_path.exists():
        print(f"ERROR: {state_path} not found")
        sys.exit(1)

    data = _load_raw(state_path)
    trades: list[dict] = data.get("trades", [])

    # Ensure quarantined_trades key exists
    if "quarantined_trades" not in data:
        data["quarantined_trades"] = []

    existing_quarantine_ids = {t.get("trade_id") for t in data["quarantined_trades"]}

    to_quarantine: list[dict] = []
    to_keep: list[dict] = []

    for trade in trades:
        if trade.get("status") != "closed":
            to_keep.append(trade)
            continue

        hd = _compute_holding_days(trade.get("entry_time"), trade.get("exit_time"))
        if hd is None or hd >= 0:
            # Backfill holding_days for valid trades too
            if hd is not None and trade.get("holding_days") is None:
                trade["holding_days"] = hd
            to_keep.append(trade)
        else:
            # Negative holding_days → quarantine candidate
            if trade.get("trade_id") in existing_quarantine_ids:
                # Already quarantined; still remove from main trades list
                trade["status"] = "quarantined"
                to_keep.append(trade)  # keep marker in trades list
            else:
                quarantine_entry = dict(trade)
                quarantine_entry["status"] = "quarantined"
                quarantine_entry["holding_days"] = hd
                quarantine_entry["quarantine_reason"] = (
                    f"migrate_quarantine_invalid_trades: "
                    f"entry_time={trade.get('entry_time', '')[:19]} "
                    f"exit_time={trade.get('exit_time', '')[:19]} "
                    f"holding_days={hd:.4f}"
                )
                to_quarantine.append(quarantine_entry)
                # Keep status marker in main trades list
                trade["status"] = "quarantined"
                trade["holding_days"] = hd
                to_keep.append(trade)

    print(f"\n=== migrate_quarantine_invalid_trades ===")
    print(f"Total trades:         {len(trades)}")
    print(f"To quarantine (new):  {len(to_quarantine)}")
    print(f"Already quarantined:  {len(existing_quarantine_ids)}")
    print(f"Clean closed remain:  {sum(1 for t in to_keep if t.get('status') == 'closed')}")

    if to_quarantine:
        print("\nQuarantining:")
        by_sym: dict[str, int] = {}
        for t in to_quarantine:
            by_sym[t.get("symbol", "?")] = by_sym.get(t.get("symbol", "?"), 0) + 1
            print(
                f"  {t.get('symbol','?'):8s} "
                f"entry={str(t.get('entry_time',''))[:19]} "
                f"exit={str(t.get('exit_time',''))[:19]} "
                f"hd={t.get('holding_days', '?'):.2f}d "
                f"pnl=${t.get('pnl', 0):.0f}"
            )
        print(f"\nBy symbol: {dict(sorted(by_sym.items(), key=lambda x: -x[1]))}")

    if args.dry_run:
        print("\n[DRY RUN] No changes written.")
        return

    if args.backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = state_path.parent / f"pnl_state.backup_quarantine_migrate_{ts}.json"
        shutil.copy2(state_path, backup_path)
        print(f"\nBackup: {backup_path}")

    # Update state
    data["trades"] = to_keep
    data["quarantined_trades"] = data["quarantined_trades"] + to_quarantine
    data["last_updated"] = datetime.now(timezone.utc).isoformat()

    _atomic_write(state_path, data)
    print(f"✅ Written: {state_path}")
    print(f"   quarantined_trades total: {len(data['quarantined_trades'])}")

    # Verification
    data2 = _load_raw(state_path)
    closed_after = [t for t in data2.get("trades", []) if t.get("status") == "closed"]
    neg_after = [
        t for t in closed_after
        if (_compute_holding_days(t.get("entry_time"), t.get("exit_time")) or 0) < 0
    ]
    print(f"\nVerification:")
    print(f"  clean closed: {len(closed_after)}")
    print(f"  remaining negative holding_days: {len(neg_after)}")
    if neg_after:
        print("  WARNING: still has negatives!")
        for t in neg_after[:5]:
            print(f"    {t.get('symbol')} hd={_compute_holding_days(t.get('entry_time'), t.get('exit_time')):.2f}")
    else:
        print("  ✅ No negative holding_days in clean closed trades")


if __name__ == "__main__":
    main()
