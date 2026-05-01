#!/usr/bin/env python3
"""Test Broker API responses."""

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment manually
def load_env():
    env_file = PROJECT_ROOT / '.env'
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env()

from stock_swing.sources.broker_client import BrokerClient

def test_broker():
    """Test broker API calls."""
    api_key = os.environ.get("BROKER_API_KEY", "")
    api_secret = os.environ.get("BROKER_API_SECRET", "")
    
    if not api_key or not api_secret:
        print("❌ No API credentials found")
        return
    
    print(f"✅ API credentials found")
    print(f"   Key: {api_key[:10]}...")
    
    try:
        broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
        print("✅ BrokerClient initialized")
        
        # Test account info
        print("\n📊 Testing fetch_account()...")
        account = broker.fetch_account()
        print(f"   Type: {type(account)}")
        
        if hasattr(account, 'payload'):
            acc_data = account.payload
            print(f"   Payload: {acc_data}")
        else:
            acc_data = account
            print(f"   Direct: {acc_data}")
        
        if isinstance(acc_data, dict):
            print(f"   Keys: {list(acc_data.keys())}")
            print(f"   equity: {acc_data.get('equity')}")
            print(f"   cash: {acc_data.get('cash')}")
            print(f"   portfolio_value: {acc_data.get('portfolio_value')}")
        
        # Test positions
        print("\n📈 Testing fetch_positions()...")
        positions = broker.fetch_positions()
        print(f"   Type: {type(positions)}")
        
        if hasattr(positions, 'payload'):
            pos_data = positions.payload
            print(f"   Payload count: {len(pos_data) if pos_data else 0}")
        else:
            pos_data = positions
            print(f"   Direct count: {len(pos_data) if pos_data else 0}")
        
        if pos_data and len(pos_data) > 0:
            print(f"   First position: {pos_data[0]}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_broker()
