#!/usr/bin/env python3
"""Risk3 mitigation: recover exit_reason for broker_fill trades.

Sources (in priority order):
  1. trade_events.jsonl  -- exit_reason saved at close time by record_exit
  2. sell decision JSONs -- exit_reason extracted from evidence.notes text
  3. pending_exit_reasons.json -- exit_reason written at sell submission

Usage:
    python scripts/recover_exit_reasons.py [--dry-run] [--backup]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))


UNKNOWN_REASONS = {"broker_fill", "broker_fill_unknown", None, ""}


def _atomic_write(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".recover_exit.", suffix=".tmp")
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


def _extract_reason_from_notes(notes: str) -> str | None:
    """Derive exit_reason from decision evidence.notes text."""
    if not notes:
        return None
    n = notes.lower()
    if "breakeven_stop" in n or "breakeven stop" in n:
        return "breakeven_stop"
    if "trailing_stop" in n or "trailing stop" in n:
        return "trailing_stop"
    if "hard_stop" in n:
        return "hard_stop"
    if "stop_loss" in n or "stop loss" in n:
        return "stop_loss"
    if "max_hold" in n or "hold days" in n:
        return "max_hold_days"
    if "sector_shock" in n:
        return "sector_shock_hold"
    return None


def build_event_map(project_root: Path) -> dict[str, str]:
    """Build broker_order_id → exit_reason from trade_events.jsonl."""
    events_path = project_root / "data" / "tracking" / "trade_events.jsonl"
    result: dict[str, str] = {}
    if not events_path.exists():
        return result
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("event_type") != "trade_closed":
            continue
        reason = (e.get("payload") or {}).get("exit_reason")
        if reason and reason not in UNKNOWN_REASONS:
            oid = e.get("broker_order_id")
            if oid:
                result[oid] = reason
    return result


def build_pending_map(project_root: Path) -> dict[str, str]:
    """Build broker_order_id → exit_reason from pending_exit_reasons.json."""
    path = project_root / "data" / "tracking" / "pending_exit_reasons.json"
    result: dict[str, str] = {}
    if not path.exists():
        return result
    try:
        store: dict = json.loads(path.read_text(encoding="utf-8"))
        for oid, entry in store.items():
            reason = entry.get("exit_reason")
            if reason and reason not in UNKNOWN_REASONS:
                result[oid] = reason
    except Exception:
        pass
    return result


def build_decision_map(project_root: Path) -> dict[tuple[str, str], str]:
    """Build (symbol, exit_date_YYYY-MM-DD) → exit_reason from sell decision JSONs."""
    result: dict[tuple[str, str], str] = {}
    patterns = [
        str(project_root / "data" / "decisions" / "**" / "*.json"),
        str(project_root / "data" / "archive" / "**" / "*.json"),
    ]
    for pattern in patterns:
        for f in glob.glob(pattern, recursive=True):
            try:
                raw = json.loads(Path(f).read_text(encoding="utf-8"))
                d = raw if isinstance(raw, dict) else {}
            except Exception:
                continue
            if d.get("action") != "sell":
                continue
            sym = d.get("symbol", "")
            notes = str((d.get("evidence") or {}).get("notes") or "")
            gen_at = str(d.get("generated_at") or "")[:10]
            reason = _extract_reason_from_notes(notes)
            if reason and sym and gen_at:
                key = (sym, gen_at)
                # Prefer more specific reasons
                existing = result.get(key)
                if existing is None or reason in ("trailing_stop", "breakeven_stop"):
                    result[key] = reason
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover exit_reason for broker_fill trades")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup", action="store_true", default=True)
    parser.add_argument("--no-backup", dest="backup", action="store_false")
    args = parser.parse_args()

    state_path = project_root / "data" / "tracking" / "pnl_state.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    trades: list[dict] = data.get("trades", [])

    event_map = build_event_map(project_root)
    pending_map = build_pending_map(project_root)
    decision_map = build_decision_map(project_root)

    print(f"\n=== recover_exit_reasons ===")
    print(f"Sources loaded:")
    print(f"  trade_events.jsonl:         {len(event_map)} recoverable exit reasons")
    print(f"  pending_exit_reasons.json:  {len(pending_map)} entries")
    print(f"  sell decision JSONs:        {len(decision_map)} (symbol, date) pairs")

    recovered = 0
    source_stats: dict[str, int] = {"trade_event": 0, "pending": 0, "decision_json": 0, "none": 0}

    for trade in trades:
        if trade.get("status") != "closed":
            continue
        if trade.get("exit_reason") not in UNKNOWN_REASONS:
            continue  # already has a meaningful reason

        oid = trade.get("exit_broker_order_id")
        sym = trade.get("symbol", "")
        exit_date = str(trade.get("exit_time") or "")[:10]

        new_reason = None
        source = None

        # Priority 1: trade_events
        if oid and oid in event_map:
            new_reason = event_map[oid]
            source = "trade_event"
        # Priority 2: pending_exit_reasons
        elif oid and oid in pending_map:
            new_reason = pending_map[oid]
            source = "pending"
        # Priority 3: decision JSON (symbol + exit date match)
        elif sym and exit_date and (sym, exit_date) in decision_map:
            new_reason = decision_map[(sym, exit_date)]
            source = "decision_json"

        if new_reason:
            if not args.dry_run:
                trade["exit_reason"] = new_reason
            recovered += 1
            source_stats[source] = source_stats.get(source, 0) + 1
        else:
            source_stats["none"] = source_stats.get("none", 0) + 1

    clean_closed = [t for t in trades if t.get("status") == "closed"]
    still_unknown_after = [
        t for t in clean_closed
        if t.get("exit_reason") in UNKNOWN_REASONS
    ]

    print(f"\nRecovery results:")
    print(f"  Total broker_fill/unknown in clean: {len([t for t in clean_closed if t.get('exit_reason') in UNKNOWN_REASONS]) + recovered}")
    print(f"  Recovered:     {recovered}")
    print(f"    from trade_events:    {source_stats.get('trade_event', 0)}")
    print(f"    from pending:         {source_stats.get('pending', 0)}")
    print(f"    from decision JSONs:  {source_stats.get('decision_json', 0)}")
    print(f"  Still unknown: {len(still_unknown_after)}")

    if recovered > 0:
        unknown_before = len(still_unknown_after) + (recovered if args.dry_run else 0)
        unknown_after  = unknown_before - recovered
        cov_before = round((len(clean_closed) - unknown_before) / len(clean_closed) * 100, 1) if clean_closed else 0
        cov_after  = round((len(clean_closed) - unknown_after)  / len(clean_closed) * 100, 1) if clean_closed else 0
        print(f"\n  Attribution coverage: {cov_before}% → {cov_after}%")

    if args.dry_run:
        print("\n[DRY RUN] No changes written.")
        return

    if not recovered:
        print("\nNo recoveries to write.")
        return

    if args.backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = state_path.parent / f"pnl_state.backup_recover_exit_{ts}.json"
        shutil.copy2(state_path, backup)
        print(f"\nBackup: {backup}")

    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(state_path, data)
    print(f"✅ Written: {state_path}")


if __name__ == "__main__":
    main()
