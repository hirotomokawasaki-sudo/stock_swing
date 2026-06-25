#!/usr/bin/env python3
"""Build broker/tracker reconciliation report with weighted average (P1-A)."""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.cli.paper_demo import _load_env

_load_env(PROJECT_ROOT / ".env")

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.pnl_tracker import PnLTracker


def main() -> None:
    broker = BrokerClient(
        api_key=os.environ["BROKER_API_KEY"],
        api_secret=os.environ["BROKER_API_SECRET"],
        paper_mode=True,
    )
    tracker = PnLTracker(PROJECT_ROOT)

    pos_env = broker.fetch_positions()
    positions = pos_env.payload if hasattr(pos_env, "payload") else pos_env
    broker_by_sym = {}
    if isinstance(positions, list):
        for pos in positions:
            sym = str(pos.get("symbol", "")).upper()
            broker_by_sym[sym] = {
                "qty": int(abs(float(pos.get("qty", 0)))),
                "avg_entry": float(pos.get("avg_entry_price", 0) or 0),
            }

    lots_by_sym: dict[str, list[dict]] = defaultdict(list)
    for trade in tracker.get_open_positions():
        sym = str(trade.get("symbol", "")).upper()
        if sym:
            lots_by_sym[sym].append(trade)

    tracker_by_sym = {}
    for sym, lots in lots_by_sym.items():
        total_qty = sum(int(trade.get("qty", 0)) for trade in lots)
        if total_qty > 0:
            weighted_avg = sum(
                int(trade.get("qty", 0)) * float(trade.get("entry_price", 0))
                for trade in lots
            ) / total_qty
        else:
            weighted_avg = 0.0
        tracker_by_sym[sym] = {
            "lot_count": len(lots),
            "total_qty": total_qty,
            "weighted_avg_entry": round(weighted_avg, 4),
        }

    lines = [
        "# Broker/Tracker Reconciliation (Weighted Average)",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"Broker positions: {len(broker_by_sym)}",
        f"Tracker open symbols: {len(tracker_by_sym)}",
        "",
        "| Symbol | Lots | Tracker Qty | Broker Qty | Qty Match | Tracker W.Avg | Broker Avg | Price Delta | Status |",
        "|--------|------|-------------|-----------|-----------|--------------|-----------|-------------|--------|",
    ]
    all_syms = sorted(set(broker_by_sym) | set(tracker_by_sym))
    issues = []
    for sym in all_syms:
        broker_pos = broker_by_sym.get(sym, {"qty": 0, "avg_entry": 0.0})
        tracker_pos = tracker_by_sym.get(
            sym,
            {"lot_count": 0, "total_qty": 0, "weighted_avg_entry": 0.0},
        )
        qty_ok = "OK" if broker_pos["qty"] == tracker_pos["total_qty"] else "NG"
        price_ok = "OK"
        price_delta = ""
        if broker_pos["avg_entry"] > 0 and tracker_pos["weighted_avg_entry"] > 0:
            delta = (
                tracker_pos["weighted_avg_entry"] - broker_pos["avg_entry"]
            ) / broker_pos["avg_entry"]
            price_delta = f"{delta:+.1%}"
            if abs(delta) > 0.05:
                price_ok = f"WARN({delta:+.1%})"
                issues.append(sym)
        status = "OK" if qty_ok == "OK" and price_ok == "OK" else "WARN"
        lines.append(
            f"| {sym} | {tracker_pos['lot_count']} | {tracker_pos['total_qty']} | "
            f"{broker_pos['qty']} | {qty_ok} | ${tracker_pos['weighted_avg_entry']:.2f} | "
            f"${broker_pos['avg_entry']:.2f} | {price_delta} | {status} |"
        )

    lines += ["", f"Issues ({len(issues)}): {', '.join(issues) or 'None'}"]
    report = "\n".join(lines)
    out = PROJECT_ROOT / "data" / "analysis" / "broker_tracker_reconciliation.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nSaved to: {out}")


if __name__ == "__main__":
    main()
