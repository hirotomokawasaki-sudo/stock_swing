#!/usr/bin/env python3
"""Correct anomalous entry/exit prices using Yahoo Finance historical market data.

Instead of deleting trades with anomalous prices, this script corrects
the prices to match the actual market ranges on the trade dates.

Correction rules:
- If entry price < market low - 10%: use market low
- If entry price > market high + 10%: use market high
- If exit price < market low - 10%: use market low
- If exit price > market high + 10%: use market high

Then recalculate P&L based on corrected prices.

Usage:
    python scripts/correct_anomalous_prices_with_market_data.py [--threshold 0.10] [--dry-run]
"""

import argparse
import json
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


def fetch_yahoo_finance_bars(symbol: str) -> dict:
    """Fetch historical bars from Yahoo Finance."""
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


def correct_price(price: float, market_low: float, market_high: float, threshold: float, price_type: str) -> tuple:
    """Correct a price if it's outside market range by more than threshold.
    
    Returns: (corrected_price, was_corrected, correction_note)
    """
    # Check if price is within acceptable range
    lower_bound = market_low * (1 - threshold)
    upper_bound = market_high * (1 + threshold)
    
    if lower_bound <= price <= upper_bound:
        return (price, False, None)
    
    # Price is anomalous, correct it
    if price < lower_bound:
        corrected = market_low
        note = f"{price_type} ${price:.2f} < market ${market_low:.2f} → corrected to ${corrected:.2f}"
        return (corrected, True, note)
    else:
        corrected = market_high
        note = f"{price_type} ${price:.2f} > market ${market_high:.2f} → corrected to ${corrected:.2f}"
        return (corrected, True, note)


def main():
    parser = argparse.ArgumentParser(description="Correct anomalous prices with market data")
    parser.add_argument("--threshold", type=float, default=0.10,
                       help="Price deviation threshold for correction (default: 0.10 = 10%%)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be corrected without actually changing data")
    args = parser.parse_args()
    
    project_root = Path(__file__).resolve().parents[1]
    state_file = project_root / "data" / "tracking" / "pnl_state.json"
    
    if not state_file.exists():
        print(f"ERROR: {state_file} not found", file=sys.stderr)
        return 1
    
    # Create backup
    if not args.dry_run:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = state_file.parent / f"pnl_state_before_price_correction_{timestamp}.json"
        shutil.copy2(state_file, backup_file)
        print(f"✅ Created backup: {backup_file}")
    
    # Load state
    state = json.loads(state_file.read_text(encoding="utf-8"))
    trades = state.get("trades", [])
    closed_trades = [t for t in trades if t.get("status") == "closed"]
    
    print(f"\nCorrecting prices with threshold={args.threshold:.0%}")
    print(f"Total closed trades: {len(closed_trades)}")
    print()
    
    # Group by symbol to minimize API calls
    trades_by_symbol = {}
    for t in closed_trades:
        symbol = t.get("symbol")
        if symbol:
            trades_by_symbol.setdefault(symbol, []).append(t)
    
    total_corrected = 0
    entry_corrections = 0
    exit_corrections = 0
    market_data_cache = {}
    
    for symbol, symbol_trades in sorted(trades_by_symbol.items()):
        # Fetch market data for this symbol
        if symbol not in market_data_cache:
            market_data_cache[symbol] = fetch_yahoo_finance_bars(symbol)
        
        market_bars = market_data_cache[symbol]
        
        if not market_bars:
            print(f"SKIP: {symbol} (no market data available)")
            continue
        
        symbol_corrections = 0
        
        for trade in symbol_trades:
            trade_id = trade.get("trade_id", "unknown")
            entry_date = trade.get("entry_time", "")[:10]
            exit_date = trade.get("exit_time", "")[:10]
            entry_price = trade.get("entry_price", 0)
            exit_price = trade.get("exit_price", 0)
            qty = trade.get("qty", 0)
            
            # Get market ranges
            entry_market = market_bars.get(entry_date)
            exit_market = market_bars.get(exit_date)
            
            if not entry_market or not exit_market:
                continue
            
            entry_low, entry_high, _ = entry_market
            exit_low, exit_high, _ = exit_market
            
            # Correct entry price
            corrected_entry, entry_changed, entry_note = correct_price(
                entry_price, entry_low, entry_high, args.threshold, "Entry"
            )
            
            # Correct exit price
            corrected_exit, exit_changed, exit_note = correct_price(
                exit_price, exit_low, exit_high, args.threshold, "Exit"
            )
            
            if entry_changed or exit_changed:
                # Recalculate P&L
                old_pnl = trade.get("pnl", 0)
                new_pnl = (corrected_exit - corrected_entry) * qty
                old_return = trade.get("return_pct", 0)
                new_return = (corrected_exit - corrected_entry) / corrected_entry if corrected_entry > 0 else 0
                
                print(f"\n{symbol} {trade_id} ({entry_date}→{exit_date}):")
                if entry_note:
                    print(f"  {entry_note}")
                if exit_note:
                    print(f"  {exit_note}")
                print(f"  P&L: ${old_pnl:,.2f} → ${new_pnl:,.2f} (Δ ${new_pnl - old_pnl:+,.2f})")
                print(f"  Return: {old_return:+.2%} → {new_return:+.2%}")
                
                if not args.dry_run:
                    # Update trade
                    trade["entry_price"] = round(corrected_entry, 2)
                    trade["exit_price"] = round(corrected_exit, 2)
                    trade["pnl"] = round(new_pnl, 2)
                    trade["return_pct"] = round(new_return, 4)
                
                total_corrected += 1
                symbol_corrections += 1
                if entry_changed:
                    entry_corrections += 1
                if exit_changed:
                    exit_corrections += 1
        
        if symbol_corrections > 0:
            print(f"\n{symbol}: {symbol_corrections} trades corrected")
    
    # Recalculate cumulative P&L
    if not args.dry_run and total_corrected > 0:
        closed_trades = [t for t in trades if t.get("status") == "closed"]
        new_cumulative_pnl = sum(t.get("pnl", 0) for t in closed_trades if t.get("pnl") is not None)
        
        old_cumulative = state.get("cumulative_realized_pnl", 0)
        state["cumulative_realized_pnl"] = round(new_cumulative_pnl, 2)
        state["last_updated"] = datetime.now().isoformat()
        
        # Save
        state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        
        print("\n" + "="*100)
        print("\nSUMMARY:")
        print(f"  Total corrections: {total_corrected} trades")
        print(f"    Entry corrections: {entry_corrections}")
        print(f"    Exit corrections: {exit_corrections}")
        print()
        print(f"  Cumulative P&L: ${old_cumulative:,.2f} → ${new_cumulative_pnl:,.2f}")
        print(f"  Difference: ${new_cumulative_pnl - old_cumulative:+,.2f}")
        print()
        print(f"✅ Saved corrected data to: {state_file}")
        print(f"📝 Backup: {backup_file}")
        
        return 0
    elif args.dry_run:
        print("\n" + "="*100)
        print("\nDRY RUN SUMMARY:")
        print(f"  Would correct: {total_corrected} trades")
        print(f"    Entry corrections: {entry_corrections}")
        print(f"    Exit corrections: {exit_corrections}")
        print()
        print("Run without --dry-run to apply changes.")
        return 0
    else:
        print("\n✅ No price corrections needed. All prices are within market ranges.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
