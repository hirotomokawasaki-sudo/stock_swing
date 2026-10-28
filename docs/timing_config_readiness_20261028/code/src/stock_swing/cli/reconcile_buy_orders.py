#!/usr/bin/env python3
"""Verify BUY order filled prices against market prices to detect Alpaca API anomalies.

This script addresses the issue where Alpaca Paper Trading API returns
abnormally low filled_avg_price for BUY orders (e.g., 20-45% below market price).

Usage:
    python -m stock_swing.cli.reconcile_buy_orders

Exit codes:
    0: Success, no anomalies detected
    1: Error or anomalies detected
"""

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


def main() -> int:
    _load_env(project_root / ".env")
    api_key = os.environ.get("BROKER_API_KEY", "")
    api_secret = os.environ.get("BROKER_API_SECRET", "")
    if not api_key or not api_secret:
        print("ERROR: BROKER_API_KEY / BROKER_API_SECRET missing", file=sys.stderr)
        return 1

    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
    tracker = PnLTracker(project_root)
    tracker.state = tracker._load_state()

    # Fetch recent BUY orders
    orders_env = broker.fetch_orders(status="all", limit=500)
    orders = orders_env.payload if hasattr(orders_env, "payload") else orders_env
    if not isinstance(orders, list):
        print("ERROR: broker.fetch_orders() did not return a list", file=sys.stderr)
        return 1

    buy_orders = [o for o in orders if str(o.get("side", "")).lower() == "buy"]
    
    print(f"INFO: Checking {len(buy_orders)} BUY orders for price anomalies", file=sys.stderr)
    
    anomalies_detected = 0
    checked = 0

    for order in buy_orders:
        symbol = str(order.get("symbol", "")).upper()
        status = str(order.get("status", "")).lower()
        filled_qty = float(order.get("filled_qty", 0) or 0)
        filled_avg_price = order.get("filled_avg_price")
        
        if status not in {"filled", "partially_filled"} or filled_qty <= 0:
            continue
        
        if filled_avg_price is None:
            continue
        
        checked += 1
        filled_avg_price_float = float(filled_avg_price)
        
        # Sanity check 1: Price must be positive
        if filled_avg_price_float <= 0:
            print(f"ANOMALY: {symbol} BUY filled_avg_price=${filled_avg_price_float:.2f} (negative or zero)", file=sys.stderr)
            anomalies_detected += 1
            continue
        
        # Sanity check 2: Compare with current market price
        try:
            quote_resp = broker.fetch_latest_quote(symbol)
            quote = quote_resp.payload.get("quote", quote_resp.payload)
            bid = float(quote.get("bp", 0) or 0)
            ask = float(quote.get("ap", 0) or 0)
            
            if bid > 0 and ask > 0:
                mid_price = (bid + ask) / 2
                deviation = abs((filled_avg_price_float - mid_price) / mid_price)
                
                if deviation > 0.30:  # 30% deviation threshold
                    # Check if this is an old order (market may have moved)
                    filled_at = order.get("filled_at", "")
                    order_age_str = filled_at[:10] if filled_at else "unknown"
                    
                    print(
                        f"ANOMALY: {symbol} BUY filled=${filled_avg_price_float:.2f} "
                        f"market=${mid_price:.2f} ({deviation:.1%} deviation) "
                        f"filled_at={order_age_str}",
                        file=sys.stderr
                    )
                    anomalies_detected += 1
                    
                    # Check if this order is in our PnL tracker
                    matching_trades = [
                        t for t in tracker.state.trades
                        if t.get("symbol") == symbol 
                        and abs(t.get("entry_price", 0) - filled_avg_price_float) < 0.01
                    ]
                    
                    if matching_trades:
                        print(f"  WARNING: Found {len(matching_trades)} trades in PnL tracker with this anomalous entry price", file=sys.stderr)
                        for t in matching_trades:
                            trade_id = t.get("trade_id", "unknown")
                            entry_time = t.get("entry_time", "")[:19]
                            status_t = t.get("status", "unknown")
                            print(f"    trade_id={trade_id} entry_time={entry_time} status={status_t}", file=sys.stderr)
                else:
                    # Normal case
                    if checked <= 10:  # Log first 10 normal orders for verification
                        print(f"OK: {symbol} BUY filled=${filled_avg_price_float:.2f} market=${mid_price:.2f} ({deviation:.1%} deviation)", file=sys.stderr)
        
        except Exception as e:
            # Quote fetch failed, skip market comparison
            print(f"WARN: Could not fetch quote for {symbol}: {e}", file=sys.stderr)
            continue

    print(f"\nSUMMARY: Checked {checked} filled BUY orders", file=sys.stderr)
    print(f"         Anomalies detected: {anomalies_detected}", file=sys.stderr)
    
    if anomalies_detected > 0:
        print("\n⚠️  ACTION REQUIRED: Review anomalous BUY orders above", file=sys.stderr)
        print("   Consider removing trades with anomalous entry prices from PnL tracker", file=sys.stderr)
        return 1
    else:
        print("\n✅ No BUY order price anomalies detected", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
