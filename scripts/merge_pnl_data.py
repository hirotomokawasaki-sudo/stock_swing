#!/usr/bin/env python3
"""
Merge historical daily_snapshots from backup with accurate trades from order history

Restores:
- Historical daily snapshots (equity timeline)
- Accurate trade P&L from order matching
"""

import json
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent

print("=" * 70)
print("P&L Data Merge: Historical + Accurate Trades")
print("=" * 70)
print()

# Load historical data (4/22 backup)
print("Loading historical data (2026-04-22 backup)...")
with open(PROJECT_ROOT / 'data/tracking/pnl_state_backup_20260422_122731.json') as f:
    historical = json.load(f)

historical_snapshots = historical.get('daily_snapshots', [])
historical_equity = historical.get('equity', 0)
print(f"  Daily snapshots: {len(historical_snapshots)} 件")
print(f"  Historical equity: ${historical_equity:,.2f}")

# Load accurate trades (current)
print()
print("Loading accurate trades (rebuilt from orders)...")
with open(PROJECT_ROOT / 'data/tracking/pnl_state.json') as f:
    current = json.load(f)

accurate_trades = current.get('trades', [])
print(f"  Accurate trades: {len(accurate_trades)} 件")
print(f"  Total P&L: ${sum(t.get('pnl', 0) for t in accurate_trades):,.2f}")

# Merge
print()
print("Merging data...")

merged = {
    'trades': accurate_trades,
    'daily_snapshots': historical_snapshots,
    'equity': historical_equity,
    'last_updated': datetime.now(timezone.utc).isoformat(),
    'metadata': {
        'source': 'merged',
        'trades_source': 'broker_order_history',
        'snapshots_source': 'backup_20260422',
        'merged_at': datetime.now(timezone.utc).isoformat(),
    }
}

# Add current broker positions to latest snapshot
print("Adding current positions snapshot...")

# Get current date
today = datetime.now().strftime('%Y-%m-%d')

# Check if today already has a snapshot
existing_today = [s for s in merged['daily_snapshots'] if s.get('date') == today]

if not existing_today:
    # Add new snapshot for today
    import os, sys
    sys.path.insert(0, str(PROJECT_ROOT))
    
    # Load env
    with open(PROJECT_ROOT / '.env') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v
    
    from stock_swing.sources.broker_client import BrokerClient
    
    broker = BrokerClient(
        api_key=os.environ['BROKER_API_KEY'],
        api_secret=os.environ['BROKER_API_SECRET'],
        paper_mode=True,
    )
    
    account = broker.fetch_account()
    acc_data = account.payload if hasattr(account, 'payload') else account
    
    current_equity = float(acc_data.get('equity', 0))
    
    new_snapshot = {
        'date': today,
        'equity': current_equity,
        'realized_pnl': 0,
        'unrealized_pnl': 0,
        'total_pnl': 0,
        'trade_count': len(accurate_trades),
        'win_count': len([t for t in accurate_trades if t.get('pnl', 0) > 0]),
        'loss_count': len([t for t in accurate_trades if t.get('pnl', 0) < 0]),
        'signals_generated': 0,
        'orders_submitted': 0,
    }
    
    merged['daily_snapshots'].append(new_snapshot)
    merged['equity'] = current_equity
    
    print(f"  Added snapshot for {today}: ${current_equity:,.2f}")

# Save merged data
output_file = PROJECT_ROOT / 'data/tracking/pnl_state.json'
print()
print(f"Saving merged data to {output_file}...")

with open(output_file, 'w') as f:
    json.dump(merged, f, indent=2)

print("✅ Merge complete")
print()
print("Summary:")
print(f"  Trades: {len(merged['trades'])} 件 (accurate from orders)")
print(f"  Daily snapshots: {len(merged['daily_snapshots'])} 件 (historical + today)")
print(f"  Current equity: ${merged['equity']:,.2f}")
print()
print("Next: Restart console to see full historical data")
print()

