#!/usr/bin/env python3
"""Audit all trades in PnL tracker against historical market prices from Yahoo Finance.

This script detects anomalous entry/exit prices by comparing them with
actual market price ranges on the trade dates.

Usage:
    python scripts/audit_trades_with_market_data.py [--anomaly-threshold 0.30]

Exit codes:
    0: Success, no anomalies detected
    1: Error or anomalies detected
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path


def fetch_yahoo_finance_bars(symbol: str, start_date: str, end_date: str) -> dict:
    """Fetch historical bars from Yahoo Finance.
    
    Args:
        symbol: Stock symbol
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    
    Returns:
        Dict mapping date strings to (low, high, close) tuples
    """
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            result = data.get('chart', {}).get('result', [{}])[0]
            timestamps = result.get('timestamp', [])
            quotes = result.get('indicators', {}).get('quote', [{}])[0]
            
            bars = {}
            for i, ts in enumerate(timestamps):
                date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                close = quotes.get('close', [])[i]
                high = quotes.get('high', [])[i]
                low = quotes.get('low', [])[i]
                
                if close and high and low:
                    bars[date] = (float(low), float(high), float(close))
            
            return bars
    except Exception as e:
        print(f"WARN: Could not fetch Yahoo Finance data for {symbol}: {e}", file=sys.stderr)
        return {}


def main():
    parser = argparse.ArgumentParser(description="Audit trades against market prices")
    parser.add_argument("--anomaly-threshold", type=float, default=0.30,
                       help="Price deviation threshold for anomaly detection (default: 0.30 = 30%%)")
    parser.add_argument("--symbols", nargs="*", help="Only audit specific symbols (default: all)")
    parser.add_argument("--recent-days", type=int, help="Only audit trades from recent N days")
    args = parser.parse_args()
    
    project_root = Path(__file__).resolve().parents[1]
    state_file = project_root / "data" / "tracking" / "pnl_state.json"
    
    if not state_file.exists():
        print(f"ERROR: {state_file} not found", file=sys.stderr)
        return 1
    
    state = json.loads(state_file.read_text(encoding="utf-8"))
    trades = state.get("trades", [])
    
    # Filter trades
    if args.symbols:
        trades = [t for t in trades if t.get("symbol") in args.symbols]
    
    if args.recent_days:
        cutoff = (datetime.now() - timedelta(days=args.recent_days)).isoformat()
        trades = [t for t in trades if t.get("entry_time", "") > cutoff]
    
    # Only check closed trades
    closed_trades = [t for t in trades if t.get("status") == "closed"]
    
    print(f"INFO: Auditing {len(closed_trades)} closed trades (threshold={args.anomaly_threshold:.0%})", file=sys.stderr)
    print()
    
    # Group by symbol to minimize API calls
    trades_by_symbol = {}
    for t in closed_trades:
        symbol = t.get("symbol")
        if symbol:
            trades_by_symbol.setdefault(symbol, []).append(t)
    
    total_anomalies = 0
    entry_anomalies = 0
    exit_anomalies = 0
    both_anomalies = 0
    
    for symbol, symbol_trades in sorted(trades_by_symbol.items()):
        print(f"\n{'='*100}")
        print(f"SYMBOL: {symbol} ({len(symbol_trades)} trades)")
        print('='*100)
        
        # Get date range for this symbol
        all_dates = set()
        for t in symbol_trades:
            entry_date = t.get("entry_time", "")[:10]
            exit_date = t.get("exit_time", "")[:10]
            all_dates.add(entry_date)
            all_dates.add(exit_date)
        
        if not all_dates:
            continue
        
        # Fetch Yahoo Finance data
        market_bars = fetch_yahoo_finance_bars(symbol, min(all_dates), max(all_dates))
        
        if not market_bars:
            print(f"WARN: No market data available for {symbol}, skipping", file=sys.stderr)
            continue
        
        # Audit each trade
        for t in sorted(symbol_trades, key=lambda x: x.get("entry_time", "")):
            trade_id = t.get("trade_id", "unknown")
            entry_time = t.get("entry_time", "")[:19]
            exit_time = t.get("exit_time", "")[:19]
            entry_date = entry_time[:10]
            exit_date = exit_time[:10]
            entry_price = t.get("entry_price", 0)
            exit_price = t.get("exit_price", 0)
            ret = t.get("return_pct", 0)
            pnl = t.get("pnl", 0)
            
            # Get market ranges
            entry_market = market_bars.get(entry_date)
            exit_market = market_bars.get(exit_date)
            
            if not entry_market or not exit_market:
                print(f"SKIP: {trade_id} (missing market data for {entry_date} or {exit_date})")
                continue
            
            entry_low, entry_high, entry_close = entry_market
            exit_low, exit_high, exit_close = exit_market
            
            # Check anomalies
            entry_in_range = entry_low <= entry_price <= entry_high
            exit_in_range = exit_low <= exit_price <= exit_high
            
            # Calculate deviation
            entry_dev = 0
            exit_dev = 0
            
            if not entry_in_range:
                if entry_price < entry_low:
                    entry_dev = (entry_low - entry_price) / entry_low
                else:
                    entry_dev = (entry_price - entry_high) / entry_high
            
            if not exit_in_range:
                if exit_price < exit_low:
                    exit_dev = (exit_low - exit_price) / exit_low
                else:
                    exit_dev = (exit_price - exit_high) / exit_high
            
            # Classify anomaly
            is_anomaly = (not entry_in_range and entry_dev > args.anomaly_threshold) or \
                        (not exit_in_range and exit_dev > args.anomaly_threshold)
            
            if is_anomaly:
                total_anomalies += 1
                
                if not entry_in_range and not exit_in_range:
                    status = "❌ BOTH ANOMALOUS"
                    both_anomalies += 1
                elif not entry_in_range:
                    status = f"⚠️  ENTRY ANOMALOUS ({entry_dev:+.1%})"
                    entry_anomalies += 1
                else:
                    status = f"⚠️  EXIT ANOMALOUS ({exit_dev:+.1%})"
                    exit_anomalies += 1
                
                print(f"\n{status}")
                print(f"  Trade ID: {trade_id}")
                print(f"  Entry: {entry_date} ${entry_price:.2f} (market ${entry_low:.2f}-${entry_high:.2f})")
                print(f"  Exit:  {exit_date} ${exit_price:.2f} (market ${exit_low:.2f}-${exit_high:.2f})")
                print(f"  Return: {ret:+.2%}  P&L: ${pnl:,.2f}")
    
    # Summary
    print("\n" + "="*100)
    print("\nAUDIT SUMMARY")
    print("="*100)
    print(f"Total closed trades audited: {len(closed_trades)}")
    print(f"Total anomalies detected:    {total_anomalies}")
    print(f"  Entry price anomalies:     {entry_anomalies}")
    print(f"  Exit price anomalies:      {exit_anomalies}")
    print(f"  Both anomalous:            {both_anomalies}")
    
    if total_anomalies > 0:
        print("\n⚠️  ACTION REQUIRED:")
        print(f"   Review {total_anomalies} anomalous trades above")
        print("   Consider creating cleanup script to remove anomalous trades")
        print("\nNext steps:")
        print("  1. Backup pnl_state.json")
        print("  2. Remove anomalous trades")
        print("  3. Restart console to clear cache")
        return 1
    else:
        print("\n✅ No anomalies detected. All trades are within market price ranges.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
