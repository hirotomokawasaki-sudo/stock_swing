#!/usr/bin/env python3
"""Backfill entry/exit metadata for closed trades from decision files (P1-C)."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.tracking.pnl_tracker import PnLTracker


def load_decisions_index(dec_dir: Path) -> dict[tuple[str, str], list[dict]]:
    """Index decision files by (symbol, date_prefix)."""
    index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for decision_file in sorted(dec_dir.glob("decision_*.json")):
        try:
            decision = json.loads(decision_file.read_text(encoding="utf-8"))
            sym = str(decision.get("symbol", "")).upper()
            generated_at = str(decision.get("generated_at", ""))
            if sym and generated_at:
                index[(sym, generated_at[:10])].append(decision)
        except Exception:
            continue
    return index


def main() -> None:
    tracker = PnLTracker(PROJECT_ROOT)
    dec_dir = PROJECT_ROOT / "data" / "decisions"

    if not dec_dir.exists():
        print("No decisions directory found.")
        return

    decisions_index = load_decisions_index(dec_dir)
    stats = {
        "total_closed": 0,
        "strategy_id_backfilled": 0,
        "entry_signal_strength_backfilled": 0,
        "exit_reason_backfilled": 0,
        "no_decision_match": 0,
    }

    for trade in tracker.state.trades:
        if trade.get("status") != "closed":
            continue
        stats["total_closed"] += 1

        sym = str(trade.get("symbol", "")).upper()
        entry_time = str(trade.get("entry_time", ""))
        candidates = decisions_index.get((sym, entry_time[:10]), [])
        if not candidates:
            stats["no_decision_match"] += 1
            continue

        buy_candidates = [d for d in candidates if d.get("action") == "buy"]
        if not buy_candidates:
            stats["no_decision_match"] += 1
            continue
        decision = buy_candidates[0]

        if not trade.get("strategy_id") or trade["strategy_id"] == "broker_reconstructed":
            strategy_id = decision.get("strategy_id") or decision.get("strategy_version_id")
            if strategy_id:
                trade["strategy_id"] = strategy_id
                stats["strategy_id_backfilled"] += 1

        if trade.get("entry_signal_strength") is None:
            signal_strength = decision.get("signal_strength")
            if signal_strength is not None:
                trade["entry_signal_strength"] = round(float(signal_strength), 4)
                stats["entry_signal_strength_backfilled"] += 1

        if not trade.get("exit_reason") or trade["exit_reason"] in ("", "broker_fill", None):
            exit_sid = str(trade.get("exit_strategy_id", ""))
            if "trailing_stop" in exit_sid:
                trade["exit_reason"] = "trailing_stop"
                stats["exit_reason_backfilled"] += 1
            elif "stop_loss" in exit_sid:
                trade["exit_reason"] = "stop_loss"
                stats["exit_reason_backfilled"] += 1
            elif "breakeven" in exit_sid:
                trade["exit_reason"] = "breakeven_stop"
                stats["exit_reason_backfilled"] += 1

    tracker._save_state()

    print(json.dumps(stats, indent=2))
    out = PROJECT_ROOT / "data" / "analysis" / "metadata_backfill_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "stats": stats,
                "missing_count": stats["no_decision_match"],
                "missing_pct": round(
                    stats["no_decision_match"] / max(stats["total_closed"], 1) * 100,
                    1,
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\nBackfill complete. Stats above.")
    print(f"Report saved to: {out}")


if __name__ == "__main__":
    main()
