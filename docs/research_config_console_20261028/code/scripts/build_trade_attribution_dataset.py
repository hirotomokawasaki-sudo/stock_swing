#!/usr/bin/env python3
"""Build trade attribution dataset joining decisions, trades, and outcomes (P3-E)."""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.tracking.pnl_tracker import PnLTracker

OUT_CSV = PROJECT_ROOT / "data" / "analysis" / "trade_attribution.csv"

FIELDS = [
    "trade_id", "symbol", "entry_time", "exit_time", "qty",
    "entry_price", "exit_price", "pnl", "return_pct", "holding_days",
    "entry_strategy_id", "entry_strategy_version_id",
    "entry_signal_strength", "entry_confidence",
    "entry_reason", "entry_price_source",
    "exit_reason", "exit_strategy_id", "exit_trigger",
    "market_regime", "outcome_label",
]


def outcome_label(return_pct: float | None) -> str:
    if return_pct is None:
        return "unknown"
    if return_pct >= 0.05:
        return "good"
    if return_pct <= -0.05:
        return "bad"
    return "neutral"


def load_decisions_index(dec_dir: Path) -> dict[tuple[str, str], list[dict]]:
    index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    if not dec_dir.exists():
        return index
    for df in sorted(dec_dir.glob("decision_*.json")):
        try:
            d = json.loads(df.read_text(encoding="utf-8"))
            sym = str(d.get("symbol", "")).upper()
            gen_at = str(d.get("generated_at", ""))
            if sym and gen_at:
                index[(sym, gen_at[:10])].append(d)
        except Exception:
            continue
    return index


def enrich_from_decision(trade: dict, decision: dict | None) -> dict:
    if not decision:
        return {
            "entry_strategy_id": trade.get("strategy_id", ""),
            "entry_strategy_version_id": trade.get("strategy_version_id", ""),
            "entry_signal_strength": trade.get("entry_signal_strength", ""),
            "entry_confidence": "",
            "entry_reason": "",
            "entry_price_source": "",
            "market_regime": "",
        }
    evidence = decision.get("evidence") or {}
    sizing = decision.get("sizing") or {}
    notes = evidence.get("notes") or []
    return {
        "entry_strategy_id": decision.get("strategy_id") or trade.get("strategy_id", ""),
        "entry_strategy_version_id": decision.get("strategy_version_id") or trade.get("strategy_version_id", ""),
        "entry_signal_strength": trade.get("entry_signal_strength") or decision.get("signal_strength", ""),
        "entry_confidence": decision.get("confidence", ""),
        "entry_reason": notes[0] if isinstance(notes, list) and notes else "",
        "entry_price_source": sizing.get("price_source") or evidence.get("price_source", ""),
        "market_regime": sizing.get("regime_used") or evidence.get("market_regime", ""),
    }


def main() -> None:
    tracker = PnLTracker(PROJECT_ROOT)
    dec_index = load_decisions_index(PROJECT_ROOT / "data" / "decisions")
    closed = [t for t in tracker.state.trades if t.get("status") == "closed"]

    rows = []
    for t in sorted(closed, key=lambda x: x.get("entry_time") or ""):
        sym = str(t.get("symbol", "")).upper()
        entry_time = str(t.get("entry_time", ""))
        date_prefix = entry_time[:10]
        candidates = [
            d for d in dec_index.get((sym, date_prefix), [])
            if d.get("action") == "buy"
        ]
        decision = candidates[0] if candidates else None
        enriched = enrich_from_decision(t, decision)

        exit_sid = str(t.get("exit_strategy_id") or "")
        exit_trigger = ""
        if "trailing_stop" in exit_sid:
            exit_trigger = "trailing_stop"
        elif "stop_loss" in exit_sid:
            exit_trigger = "stop_loss"
        elif "breakeven" in exit_sid:
            exit_trigger = "breakeven_stop"

        holding_days = None
        et, xt = t.get("entry_time", ""), t.get("exit_time", "")
        if et and xt:
            try:
                holding_days = (
                    datetime.fromisoformat(xt.replace("Z", "+00:00")) -
                    datetime.fromisoformat(et.replace("Z", "+00:00"))
                ).days
            except Exception:
                pass

        rows.append({
            "trade_id": t.get("trade_id", ""),
            "symbol": sym,
            "entry_time": et,
            "exit_time": xt,
            "qty": t.get("qty", ""),
            "entry_price": t.get("entry_price", ""),
            "exit_price": t.get("exit_price", ""),
            "pnl": t.get("pnl", ""),
            "return_pct": t.get("return_pct", ""),
            "holding_days": holding_days,
            "exit_reason": t.get("exit_reason", ""),
            "exit_strategy_id": exit_sid,
            "exit_trigger": exit_trigger,
            "outcome_label": outcome_label(t.get("return_pct")),
            **enriched,
        })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    with_ess = sum(1 for r in rows if r.get("entry_signal_strength") not in ("", None))
    without_broker_fill = sum(
        1 for r in rows
        if r.get("exit_reason") not in ("broker_fill", "", None)
    )
    print(f"Trade attribution dataset: {len(rows)} rows")
    print(f"  entry_signal_strength coverage: {with_ess}/{len(rows)} ({with_ess / max(len(rows), 1) * 100:.0f}%)")
    print(f"  exit_reason (non broker_fill): {without_broker_fill}/{len(rows)} ({without_broker_fill / max(len(rows), 1) * 100:.0f}%)")
    print(f"  Saved to: {OUT_CSV}")


if __name__ == "__main__":
    main()
