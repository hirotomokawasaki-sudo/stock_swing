#!/usr/bin/env python3
"""Reconcile recent broker orders and update PnL tracker for filled exits."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.cli.paper_demo import _load_env
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.pnl_tracker import PnLTracker


def parse_submission_line(line: str):
    parts = [p.strip() for p in line.split(" | ", 6)]
    if len(parts) < 7 or parts[2] != "submission":
        return None
    details = parts[6]
    if not details.startswith("Order submitted:"):
        return None
    tail = details.split(":", 1)[1].strip().split()
    if len(tail) < 3:
        return None
    side = tail[0].lower()
    qty = int(tail[1]) if tail[1].isdigit() else 0
    symbol = tail[2].upper()
    return {
        "ts": parts[0],
        "submission_id": parts[5],
        "side": side,
        "qty": qty,
        "symbol": symbol,
    }


def load_recent_submissions(audits_dir: Path, limit: int = 100):
    items = []
    for path in sorted(audits_dir.glob("paper_demo_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = parse_submission_line(line)
            if parsed:
                items.append(parsed)
                if len(items) >= limit:
                    return items
    return items


def main() -> int:
    _load_env(project_root / ".env")
    api_key = os.environ.get("BROKER_API_KEY", "")
    api_secret = os.environ.get("BROKER_API_SECRET", "")
    if not api_key or not api_secret:
        print("BROKER_API_KEY / BROKER_API_SECRET missing")
        return 1

    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
    tracker = PnLTracker(project_root)
    tracker.state = tracker._load_state()

    submissions = load_recent_submissions(project_root / "data" / "audits")
    filled_exits = 0
    checked = 0

    for sub in submissions:
        if sub["side"] != "sell":
            continue
        checked += 1
        try:
            # find broker order id from tracker open trades or audit context is not in plain line, so query broker recent orders by symbol
            orders_env = broker.fetch_orders(status="all")
            orders = orders_env.payload if hasattr(orders_env, "payload") else orders_env
            match = None
            if isinstance(orders, list):
                for order in orders:
                    if str(order.get("symbol", "")).upper() == sub["symbol"] and str(order.get("side", "")).lower() == "sell":
                        match = order
                        break
            if not match:
                continue
            status = str(match.get("status", "")).lower()
            filled_qty = float(match.get("filled_qty", 0) or 0)
            avg_price = match.get("filled_avg_price")
            if status in {"filled", "partially_filled"} and filled_qty > 0 and avg_price:
                # Pass filled_qty to support partial fills
                updated = tracker.record_exit(
                    symbol=sub["symbol"], 
                    exit_price=float(avg_price), 
                    exit_qty=int(filled_qty),
                    broker_order_id=match.get("id"),
                    exit_strategy_id="simple_exit_v1"
                )
                if updated:
                    filled_exits += 1
        except Exception:
            continue

    print(json.dumps({
        "checked_sell_submissions": checked,
        "filled_exits_recorded": filled_exits,
        "summary": tracker.get_summary(),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
