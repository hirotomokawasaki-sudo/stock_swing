#!/usr/bin/env python3
"""Close HPE short position by buying back 13 shares."""

import sys
import os
from pathlib import Path

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load .env
env_file = PROJECT_ROOT / '.env'
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ[key] = value

from stock_swing.sources.broker_client import BrokerClient

def main():
    broker = BrokerClient(
        api_key=os.environ['BROKER_API_KEY'],
        api_secret=os.environ['BROKER_API_SECRET'],
        paper_mode=True
    )
    
    print("Checking HPE position...")
    positions = broker.fetch_positions()
    broker_data = positions.payload if hasattr(positions, 'payload') else positions
    
    hpe_pos = [p for p in broker_data if p.get('symbol') == 'HPE']
    
    if not hpe_pos:
        print("No HPE position found. Already closed?")
        return
    
    qty = int(float(hpe_pos[0].get('qty', 0)))
    print(f"Current HPE position: {qty} shares")
    
    if qty >= 0:
        print("HPE position is not short. No action needed.")
        return
    
    # Buy back to close short
    shares_to_buy = abs(qty)
    print(f"\nClosing short position: BUY {shares_to_buy} HPE")
    
    confirm = input(f"Confirm BUY {shares_to_buy} HPE to close short? (yes/no): ")
    if confirm.lower() != 'yes':
        print("Cancelled.")
        return
    
    # Submit order
    order = broker.submit_order(
        symbol='HPE',
        side='buy',
        qty=shares_to_buy,
        order_type='market',
        time_in_force='day'
    )
    
    print(f"\nOrder submitted:")
    print(f"  Order ID: {order.get('id')}")
    print(f"  Symbol: {order.get('symbol')}")
    print(f"  Side: {order.get('side')}")
    print(f"  Qty: {order.get('qty')}")
    print(f"  Status: {order.get('status')}")
    
    print("\nShort position should be closed after order fills.")

if __name__ == '__main__':
    main()
