#!/usr/bin/env python3
"""
Sync broker positions to PnL tracker

Fixes the issue where PnL tracker shows 0 open positions
while broker has 9 actual positions.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.pnl_tracker import PnLTracker

# Load credentials
with open(PROJECT_ROOT / '.env') as f:
    for line in f:
        if line.startswith('BROKER_API_KEY='):
            os.environ['BROKER_API_KEY'] = line.split('=', 1)[1].strip()
        elif line.startswith('BROKER_API_SECRET='):
            os.environ['BROKER_API_SECRET'] = line.split('=', 1)[1].strip()

print("=" * 70)
print("Sync Broker Positions to P&L Tracker")
print("=" * 70)
print()

# Initialize clients
broker = BrokerClient(
    api_key=os.environ['BROKER_API_KEY'],
    api_secret=os.environ['BROKER_API_SECRET'],
    paper_mode=True,
)

tracker = PnLTracker(PROJECT_ROOT)

# Fetch broker positions
print("Fetching broker positions...")
positions_env = broker.fetch_positions()
positions = positions_env.payload if hasattr(positions_env, 'payload') else positions_env

print(f"Found {len(positions)} broker positions")
print()

# Get current tracker state
current_trades = tracker.state.get('trades', [])
print(f"Current tracker trades: {len(current_trades)}")
open_trades = [t for t in current_trades if t.get('status') == 'open']
print(f"Current open trades: {len(open_trades)}")
print()

# Sync each broker position
print("Syncing positions...")
print("-" * 70)

synced = 0
created = 0

for pos in positions:
    symbol = pos.get('symbol')
    qty = int(float(pos.get('qty', 0)))
    avg_entry = float(pos.get('avg_entry_price', 0))
    current_price = float(pos.get('current_price', 0))
    
    if qty <= 0:
        continue
    
    # Check if already exists in tracker
    existing = None
    for trade in current_trades:
        if (trade.get('symbol') == symbol and 
            trade.get('status') in ['open', 'accepted']):
            existing = trade
            break
    
    if existing:
        # Update existing
        existing['quantity'] = qty
        existing['entry_price'] = avg_entry
        existing['status'] = 'open'
        existing['synced_at'] = datetime.now(timezone.utc).isoformat()
        synced += 1
        print(f"✅ Updated {symbol}: {qty} shares @ ${avg_entry:.2f}")
    else:
        # Create new trade entry
        new_trade = {
            'trade_id': f"sync_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            'symbol': symbol,
            'quantity': qty,
            'entry_price': avg_entry,
            'entry_time': datetime.now(timezone.utc).isoformat(),
            'status': 'open',
            'strategy_id': 'unknown',
            'broker_order_id': None,
            'synced_at': datetime.now(timezone.utc).isoformat(),
            'note': 'Created by sync_broker_to_tracker.py',
        }
        current_trades.append(new_trade)
        created += 1
        print(f"🆕 Created {symbol}: {qty} shares @ ${avg_entry:.2f}")

# Update tracker state
tracker.state['trades'] = current_trades
tracker.save()

print()
print("=" * 70)
print("Sync Complete")
print("=" * 70)
print(f"  Updated: {synced} trades")
print(f"  Created: {created} trades")
print(f"  Total open: {synced + created} trades")
print()
print("✅ Console should now show positions correctly")
print()

