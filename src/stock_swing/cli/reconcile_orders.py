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

    orders_env = broker.fetch_orders(status="all", limit=500)
    orders = orders_env.payload if hasattr(orders_env, "payload") else orders_env
    if not isinstance(orders, list):
        print("broker.fetch_orders() did not return a list")
        return 1

    latest_sell_orders_by_symbol = {}
    for order in orders:
        symbol = str(order.get("symbol", "")).upper()
        side = str(order.get("side", "")).lower()
        if side != "sell" or not symbol:
            continue
        latest_sell_orders_by_symbol.setdefault(symbol, order)

    submissions = load_recent_submissions(project_root / "data" / "audits")
    filled_exits = 0
    checked = 0

    for sub in submissions:
        if sub["side"] != "sell":
            continue
        checked += 1
        try:
            match = latest_sell_orders_by_symbol.get(sub["symbol"])
            if not match:
                continue
            status = str(match.get("status", "")).lower()
            filled_qty = float(match.get("filled_qty", 0) or 0)
            avg_price = match.get("filled_avg_price")
            
            # Sanity check: reject obviously wrong prices
            if avg_price is not None:
                avg_price_float = float(avg_price)
                
                # Check 1: Reject prices against entry price (30% threshold)
                open_trades = [t for t in tracker.state.trades if t["symbol"] == sub["symbol"] and t["status"] == "open"]
                if open_trades:
                    entry_price = open_trades[0].get("entry_price", 0)
                    if entry_price > 0:
                        price_change = abs((avg_price_float - entry_price) / entry_price)
                        if price_change > 0.30:  # 30% price change threshold (lowered from 50%)
                            print(f"WARN: Rejecting extreme price for {sub['symbol']}: entry=${entry_price:.2f} exit=${avg_price_float:.2f} ({price_change:.1%} change)", file=sys.stderr)
                            continue
                
                # Check 2: Verify against current market price
                try:
                    quote_resp = broker.fetch_latest_quote(sub["symbol"])
                    quote = quote_resp.payload.get("quote", quote_resp.payload)
                    bid = float(quote.get("bp", 0) or 0)
                    ask = float(quote.get("ap", 0) or 0)
                    if bid > 0 and ask > 0:
                        mid_price = (bid + ask) / 2
                        market_deviation = abs((avg_price_float - mid_price) / mid_price)
                        if market_deviation > 0.30:  # 30% deviation from market
                            print(f"WARN: Rejecting price far from market for {sub['symbol']}: filled=${avg_price_float:.2f} market=${mid_price:.2f} ({market_deviation:.1%} deviation)", file=sys.stderr)
                            continue
                except Exception:
                    # Market quote fetch failed, skip this check
                    pass
            
            if status in {"filled", "partially_filled"} and filled_qty > 0 and avg_price:
                avg_price_float = float(avg_price)
                # Final sanity check: price must be positive
                if avg_price_float <= 0:
                    print(f"WARN: Invalid exit price for {sub['symbol']}: ${avg_price_float}", file=sys.stderr)
                    continue
                    
                # Pass filled_qty to support partial fills
                updated = tracker.record_exit(
                    symbol=sub["symbol"], 
                    exit_price=avg_price_float, 
                    exit_qty=int(filled_qty),
                    broker_order_id=match.get("id"),
                    exit_strategy_id="simple_exit_v1",
                    exit_reason="strategy_exit"
                )
                if updated:
                    filled_exits += 1
                    print(f"INFO: Recorded exit for {sub['symbol']}: {int(filled_qty)} @ ${avg_price_float:.2f}", file=sys.stderr)
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
