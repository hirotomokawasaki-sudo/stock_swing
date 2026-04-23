#!/usr/bin/env python3
"""Check if we can get order history from broker to reconstruct accurate P&L"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load env
with open(PROJECT_ROOT / '.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ[key] = value

from stock_swing.sources.broker_client import BrokerClient

broker = BrokerClient(
    api_key=os.environ['BROKER_API_KEY'],
    api_secret=os.environ['BROKER_API_SECRET'],
    paper_mode=True,
)

print("=" * 70)
print("Broker Order History Check")
print("=" * 70)
print()

# Check if broker client has order history method
if hasattr(broker, 'fetch_orders'):
    print("✅ fetch_orders() method exists")
    try:
        orders = broker.fetch_orders()
        print(f"✅ Fetched orders successfully")
        print(f"   Type: {type(orders)}")
        
        # Try to get payload
        if hasattr(orders, 'payload'):
            order_data = orders.payload
        else:
            order_data = orders
        
        print(f"   Orders count: {len(order_data) if isinstance(order_data, list) else 'N/A'}")
        
        if isinstance(order_data, list) and len(order_data) > 0:
            print()
            print("Sample order:")
            import json
            print(json.dumps(order_data[0], indent=2, default=str))
            
    except Exception as e:
        print(f"❌ Error fetching orders: {e}")
else:
    print("❌ fetch_orders() method not available")
    print()
    print("Checking available methods:")
    methods = [m for m in dir(broker) if not m.startswith('_') and callable(getattr(broker, m))]
    for method in methods:
        print(f"  - {method}")

