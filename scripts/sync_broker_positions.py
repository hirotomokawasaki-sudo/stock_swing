#!/usr/bin/env python3
"""Sync broker positions to PnL tracker as open trades."""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
env_file = PROJECT_ROOT / '.env'
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ[key] = value

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.pnl_tracker import PnLTracker

def main():
    # Get broker positions
    broker = BrokerClient(
        api_key=os.environ['BROKER_API_KEY'],
        api_secret=os.environ['BROKER_API_SECRET'],
        paper_mode=True
    )
    
    positions_resp = broker.fetch_positions()
    broker_positions = positions_resp.payload if hasattr(positions_resp, 'payload') else positions_resp
    
    print(f"Broker positions: {len(broker_positions)}")
    print()
    
    # Load PnL tracker
    tracker = PnLTracker(PROJECT_ROOT)
    
    print("Current open trades in PnL tracker:")
    open_trades = [t for t in tracker.state.trades if t.get('status') == 'open']
    print(f"  Count: {len(open_trades)}")
    print()
    
    # Sync positions
    print("Syncing broker positions to PnL tracker...")
    
    for pos in broker_positions:
        symbol = pos['symbol']
        qty = int(float(pos['qty']))
        avg_entry = float(pos['avg_entry_price'])
        
        # Check if already exists
        existing = [t for t in tracker.state.trades 
                   if t.get('symbol') == symbol and t.get('status') == 'open']
        
        if existing:
            print(f"  {symbol}: Already exists (qty={sum(t.get('qty', 0) for t in existing)})")
            continue
        
        # Add new open trade
        now = datetime.now(timezone.utc)
        trade = {
            'symbol': symbol,
            'qty': qty,
            'entry_price': avg_entry,
            'entry_time': now.isoformat(),
            'status': 'open',
            'strategy_id': 'breakout_momentum_v1',  # Default, will be overwritten by fix_strategy_ids.py
        }
        
        tracker.state.trades.append(trade)
        print(f"  {symbol}: Added (qty={qty}, entry_price=${avg_entry:.2f})")
    
    # Save
    print()
    print("Saving...")
    tracker._save_state()
    
    print("Done!")
    print()
    
    # Verify
    tracker.state = tracker._load_state()
    open_trades = [t for t in tracker.state.trades if t.get('status') == 'open']
    print(f"Open trades after sync: {len(open_trades)}")
    for t in open_trades:
        print(f"  {t['symbol']}: qty={t['qty']}, entry_price=${t['entry_price']:.2f}")

if __name__ == '__main__':
    main()
