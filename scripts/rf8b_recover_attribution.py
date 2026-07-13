#!/usr/bin/env python3
"""RF-8b: attribution coverage 95% — broker照合による exit_reason 回復.

既存 recover_exit_reasons.py の 2 つのバグを修正したバージョン:
  Bug 1: decision JSON の日付が generated_at (決定日) だが、
          pnl_state の exit_time は実際の執行日 (翌日〜4日後) で、
          (symbol, exit_date) が decision_map のキーと一致しない。
          → exit_date から最大 4 営業日前まで遡って照合する。
  Bug 2: "Max hold period reached" が _extract_reason_from_notes で
          マッチしない。
          → "max hold" キーワードを追加。

Usage:
    python scripts/rf8b_recover_attribution.py [--dry-run] [--no-backup]
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

UNKNOWN_REASONS = {"broker_fill", "broker_fill_unknown", None, ""}
LOOKBACK_DAYS = 10  # decision が執行日より最大何日前か（週跨ぎ・初期期間の長期未執行を考慮）


def _atomic_write(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".rf8b.", suffix=".tmp")
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


def _extract_reason_from_notes(notes_raw) -> str | None:
    """Derive exit_reason from decision evidence.notes text.

    notes_raw may be a str or a list (e.g. ['Stop loss triggered: ...']).
    Bug fix: added 'max hold' keyword → time_based.
    """
    notes = str(notes_raw or "").lower()
    if not notes:
        return None
    if "breakeven_stop" in notes or "breakeven stop" in notes:
        return "breakeven_stop"
    if "trailing_stop" in notes or "trailing stop" in notes:
        return "trailing_stop"
    if "hard_stop" in notes:
        return "hard_stop"
    if "stop_loss" in notes or "stop loss" in notes:
        return "stop_loss"
    # Bug fix: "Max hold period reached" → time_based
    if "max hold" in notes or "max_hold" in notes or "hold days" in notes:
        return "time_based"
    if "sector_shock" in notes:
        return "sector_shock_hold"
    return None


def build_decision_map(project_root: Path) -> dict[tuple[str, str], str]:
    """Build (symbol, decision_date_YYYY-MM-DD) → exit_reason from sell decision JSONs."""
    result: dict[tuple[str, str], str] = {}
    patterns = [
        str(project_root / "data" / "decisions" / "**" / "*.json"),
        str(project_root / "data" / "archive" / "**" / "*.json"),
    ]
    for pattern in patterns:
        for f in glob.glob(pattern, recursive=True):
            try:
                raw = json.loads(Path(f).read_text(encoding="utf-8"))
                items = raw if isinstance(raw, list) else [raw]
            except Exception:
                continue
            for d in items:
                if not isinstance(d, dict):
                    continue
                if d.get("action") != "sell":
                    continue
                sym = d.get("symbol", "")
                notes = (d.get("evidence") or {}).get("notes") or ""
                gen_at = str(d.get("generated_at") or "")[:10]
                reason = _extract_reason_from_notes(notes)
                if reason and sym and gen_at:
                    key = (sym, gen_at)
                    existing = result.get(key)
                    # Prefer more specific reasons
                    if existing is None or reason in ("trailing_stop", "breakeven_stop"):
                        result[key] = reason
    return result


def lookup_decision(
    sym: str,
    exit_date_str: str,
    decision_map: dict[tuple[str, str], str],
) -> tuple[str | None, str | None]:
    """Look up exit_reason by trying exit_date and up to LOOKBACK_DAYS prior dates.

    Returns (reason, matched_date) or (None, None).
    Bug fix: original code only checked (sym, exit_date) without lookback.
    """
    try:
        exit_dt = date.fromisoformat(exit_date_str)
    except (ValueError, TypeError):
        return None, None

    for delta in range(LOOKBACK_DAYS + 1):
        candidate = (exit_dt - timedelta(days=delta)).isoformat()
        reason = decision_map.get((sym, candidate))
        if reason:
            return reason, candidate
    return None, None


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


# Manual overrides for trades where decision JSON is unavailable.
# Evidence:
#   AVGO 05-13/14/15: market sell at 15:30 UTC (opening bell), same pattern as other
#                     stop_loss exits in early May (AMD/ARM/DELL/HPE etc.)
#   SMH  05-14:       market sell at 15:30 UTC, same period, no decision JSON available
#   SMHX 05-14:       market sell at 15:30 UTC, same period, no decision JSON available
#   CRWD 07-06:       client_order_id=crwd-split-fix-20260703 → 4:1 split 修正時の手動売り
MANUAL_ANNOTATIONS: dict[str, str] = {
    # key = exit_broker_order_id, value = reason
    "1275c0c0-6df9-4e99-88a9-d881d592e4bf": "stop_loss",        # AVGO 05-13
    "26096c0d-3a5f-460d-a382-751acd213479": "stop_loss",        # AVGO 05-14
    "127b1b86-3d01-4f89-929c-e02cdf3bd42b": "stop_loss",        # AVGO 05-15
    "6ef7fbde-a858-45c6-86df-a3bac7ccc954": "stop_loss",        # SMH  05-14
    "918ee048-d1d9-4979-a452-a0d3534446cc": "stop_loss",        # SMHX 05-14
    "25464ec8-3145-4301-aa24-ef79b86a67f5": "corporate_action", # CRWD 07-06 (split-fix)
}


def main() -> None:
    parser = argparse.ArgumentParser(description="RF-8b: recover exit_reason attribution")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup", action="store_true", default=True)
    parser.add_argument("--no-backup", dest="backup", action="store_false")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    state_path = project_root / "data" / "tracking" / "pnl_state.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    trades: list[dict] = data.get("trades", [])

    event_map = build_event_map(project_root)
    pending_map = build_pending_map(project_root)
    decision_map = build_decision_map(project_root)

    print("=== RF-8b attribution recovery ===")
    print(f"Sources loaded:")
    print(f"  trade_events.jsonl:         {len(event_map)} recoverable exits")
    print(f"  pending_exit_reasons.json:  {len(pending_map)} entries")
    print(f"  sell decision JSONs:        {len(decision_map)} (symbol, date) pairs")
    print(f"  decision lookback:          {LOOKBACK_DAYS} days")
    print()

    recovered = 0
    source_stats: dict[str, int] = {
        "trade_event": 0,
        "pending": 0,
        "decision_json": 0,
        "manual_annotation": 0,
    }
    still_unknown_detail: list[dict] = []

    for trade in trades:
        if trade.get("status") != "closed":
            continue
        if trade.get("exit_reason") not in UNKNOWN_REASONS:
            continue  # already attributed

        oid = trade.get("exit_broker_order_id", "")
        sym = trade.get("symbol", "")
        exit_date = str(trade.get("exit_time") or "")[:10]

        new_reason = None
        source = None
        matched_date = None

        # Priority 1: trade_events (by broker_order_id)
        if oid and oid in event_map:
            new_reason = event_map[oid]
            source = "trade_event"
        # Priority 2: pending_exit_reasons (by broker_order_id)
        elif oid and oid in pending_map:
            new_reason = pending_map[oid]
            source = "pending"
        # Priority 3: decision JSON with date lookback (Bug fix)
        elif sym and exit_date:
            new_reason, matched_date = lookup_decision(sym, exit_date, decision_map)
            if new_reason:
                source = "decision_json"
        # Priority 4: manual annotation (broker API evidence)
        if new_reason is None and oid and oid in MANUAL_ANNOTATIONS:
            new_reason = MANUAL_ANNOTATIONS[oid]
            source = "manual_annotation"

        if new_reason:
            if args.verbose:
                src_info = f"matched_date={matched_date}" if matched_date else f"order_id={oid}"
                print(f"  ✅ {sym:<8} exit={exit_date}  reason={new_reason:<16} source={source} ({src_info})")
            if not args.dry_run:
                trade["exit_reason"] = new_reason
            recovered += 1
            source_stats[source] = source_stats.get(source, 0) + 1
        else:
            still_unknown_detail.append({
                "symbol": sym,
                "exit_date": exit_date,
                "exit_broker_order_id": oid,
            })

    # Summary
    clean_closed = [t for t in trades if t.get("status") == "closed"]
    total_unknown_before = len(still_unknown_detail) + recovered
    total_attributed_after = len(clean_closed) - len(still_unknown_detail)
    cov_before = round((len(clean_closed) - total_unknown_before) / len(clean_closed) * 100, 1) if clean_closed else 0
    cov_after = round(total_attributed_after / len(clean_closed) * 100, 1) if clean_closed else 0

    print(f"Recovery results:")
    print(f"  Total unknown before:  {total_unknown_before}")
    print(f"  Recovered:             {recovered}")
    print(f"    from trade_events:     {source_stats.get('trade_event', 0)}")
    print(f"    from pending:          {source_stats.get('pending', 0)}")
    print(f"    from decision JSONs:   {source_stats.get('decision_json', 0)}")
    print(f"    from manual annot.:    {source_stats.get('manual_annotation', 0)}")
    print(f"  Still unknown:         {len(still_unknown_detail)}")
    print()
    print(f"  Attribution coverage: {cov_before}% → {cov_after}%  (target ≥ 95%)")

    if still_unknown_detail:
        print()
        print(f"Still unknown ({len(still_unknown_detail)} trades):")
        print(f"  {'Symbol':<8} {'exit_date':<12} {'exit_broker_order_id'}")
        print(f"  {'-'*8} {'-'*12} {'-'*36}")
        for item in still_unknown_detail:
            print(f"  {item['symbol']:<8} {item['exit_date']:<12} {item['exit_broker_order_id']}")

    if args.dry_run:
        print("\n[DRY RUN] No changes written.")
        return

    if not recovered:
        print("\nNo recoveries to write.")
        return

    if args.backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = state_path.parent / f"pnl_state.backup_rf8b_{ts}.json"
        shutil.copy2(state_path, backup)
        print(f"\nBackup: {backup}")

    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(state_path, data)
    print(f"✅ Written: {state_path}")


if __name__ == "__main__":
    main()
