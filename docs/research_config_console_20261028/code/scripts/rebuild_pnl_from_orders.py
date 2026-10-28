#!/usr/bin/env python3
"""
Rebuild accurate P&L tracking from broker order history

Fixes the issue where all trades show Entry Price = $0.00
and P&L calculations are incorrect.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load env
with open(PROJECT_ROOT / '.env') as f:
    for line in f:
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            os.environ[k] = v

from stock_swing.sources.broker_client import BrokerClient

print("=" * 70)
print("P&L Data Reconstruction from Broker Order History")
print("=" * 70)
print()

# Initialize broker
broker = BrokerClient(
    api_key=os.environ['BROKER_API_KEY'],
    api_secret=os.environ['BROKER_API_SECRET'],
    paper_mode=True,
)

# Fetch orders
print("Fetching order history...")
orders_env = broker.fetch_orders()
orders = orders_env.payload

filled_orders = [o for o in orders if o.get('status') == 'filled']
print(f"  Total orders: {len(orders)}")
print(f"  Filled orders: {len(filled_orders)}")
print()

# Group by symbol and side
by_symbol = defaultdict(lambda: {'buy': [], 'sell': []})

for order in filled_orders:
    symbol = order.get('symbol')
    side = order.get('side')
    filled_qty = float(order.get('filled_qty', 0))
    filled_price = float(order.get('filled_avg_price', 0))
    filled_at = order.get('filled_at', '')
    order_id = order.get('id')
    
    if filled_qty > 0 and filled_price > 0:
        by_symbol[symbol][side].append({
            'qty': filled_qty,
            'price': filled_price,
            'time': filled_at,
            'order_id': order_id,
        })

# Sort by time
for symbol in by_symbol:
    by_symbol[symbol]['buy'].sort(key=lambda x: x['time'])
    by_symbol[symbol]['sell'].sort(key=lambda x: x['time'])

# Match and create trades
print("Matching buy/sell orders...")
print()

trades = []
trade_num = 0

for symbol in sorted(by_symbol.keys()):
    buys = by_symbol[symbol]['buy'][:]
    sells = by_symbol[symbol]['sell'][:]
    
    while buys and sells:
        buy = buys[0]
        sell = sells[0]
        
        qty = min(buy['qty'], sell['qty'])
        
        entry_price = buy['price']
        exit_price = sell['price']
        pnl = (exit_price - entry_price) * qty
        return_pct = (exit_price - entry_price) / entry_price
        
        trade_num += 1
        trade = {
            'trade_id': f"order_match_{trade_num}_{symbol}",
            'symbol': symbol,
            'quantity': int(qty),
            'entry_price': round(entry_price, 2),
            'exit_price': round(exit_price, 2),
            'entry_time': buy['time'],
            'exit_time': sell['time'],
            'pnl': round(pnl, 2),
            'return_pct': round(return_pct, 6),
            'status': 'closed',
            'strategy_id': 'unknown',
            'broker_order_id': sell['order_id'],
        }
        
        trades.append(trade)
        
        sign = '+' if pnl >= 0 else ''
        print(f"{symbol:6} {int(qty):>3}株 ${entry_price:.2f}→${exit_price:.2f} = {sign}${pnl:.2f} ({return_pct*100:+.2f}%)")
        
        buy['qty'] -= qty
        sell['qty'] -= qty
        
        if buy['qty'] <= 0.01:
            buys.pop(0)
        if sell['qty'] <= 0.01:
            sells.pop(0)

# Calculate summary
total_pnl = sum(t['pnl'] for t in trades)
wins = [t for t in trades if t['pnl'] > 0]
losses = [t for t in trades if t['pnl'] < 0]

print()
print("=" * 70)
print("Summary:")
print("=" * 70)
print(f"Total Trades: {len(trades)}")
print(f"Wins: {len(wins)}")
print(f"Losses: {len(losses)}")
print(f"Win Rate: {len(wins)/len(trades)*100:.1f}%")
print(f"Total P&L: ${total_pnl:+,.2f}")
print(f"Avg Win: ${sum(t['pnl'] for t in wins)/len(wins):.2f}" if wins else "N/A")
print(f"Avg Loss: ${sum(t['pnl'] for t in losses)/len(losses):.2f}" if losses else "N/A")
print()

# Save to pnl_state.json
pnl_state = {
    'trades': trades,
    'last_updated': datetime.now(timezone.utc).isoformat(),
    'metadata': {
        'source': 'broker_order_history',
        'rebuilt_at': datetime.now(timezone.utc).isoformat(),
        'total_trades': len(trades),
        'total_pnl': total_pnl,
    }
}

output_file = PROJECT_ROOT / 'data' / 'tracking' / 'pnl_state.json'
print(f"Saving to {output_file}...")

with open(output_file, 'w') as f:
    json.dump(pnl_state, f, indent=2)

print("✅ P&L data rebuilt successfully")
print()
print("Next: Restart console to see accurate data")
print()

