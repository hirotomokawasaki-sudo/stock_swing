#!/usr/bin/env python3
"""Sync pnl_state.json with Broker's actual trade history.

Fetches filled orders from Alpaca API and reconstructs pnl_state.json
to match the Broker's actual equity.

Usage:
    python scripts/sync_pnl_with_broker.py [--dry-run]
"""

import argparse
import json
import os
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


def fetch_alpaca_orders(api_key: str, api_secret: str, status: str = 'filled'):
    """Fetch orders from Alpaca API."""
    base_url = 'https://paper-api.alpaca.markets'
    
    # Fetch filled orders (limit 500, recent first)
    url = f'{base_url}/v2/orders?status={status}&limit=500&direction=desc'
    
    try:
        req = urllib.request.Request(url)
        req.add_header('APCA-API-KEY-ID', api_key)
        req.add_header('APCA-API-SECRET-KEY', api_secret)
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"Error fetching orders: {e}", file=sys.stderr)
        return []


def fetch_alpaca_account(api_key: str, api_secret: str):
    """Fetch account info from Alpaca API."""
    base_url = 'https://paper-api.alpaca.markets'
    
    try:
        req = urllib.request.Request(f'{base_url}/v2/account')
        req.add_header('APCA-API-KEY-ID', api_key)
        req.add_header('APCA-API-SECRET-KEY', api_secret)
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"Error fetching account: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="Sync pnl_state.json with Broker")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be changed without actually changing data")
    args = parser.parse_args()
    
    # Load .env file
    project_root = Path(__file__).resolve().parents[1]
    env_file = project_root / '.env'
    
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    
    # Get API credentials
    api_key = os.environ.get('BROKER_API_KEY')
    api_secret = os.environ.get('BROKER_API_SECRET')
    
    if not api_key or not api_secret:
        print("ERROR: BROKER_API_KEY and BROKER_API_SECRET must be set", file=sys.stderr)
        return 1
    
    state_file = project_root / "data" / "tracking" / "pnl_state.json"
    
    if not state_file.exists():
        print(f"ERROR: {state_file} not found", file=sys.stderr)
        return 1
    
    # Fetch Broker data
    print("Fetching Broker account info...")
    account = fetch_alpaca_account(api_key, api_secret)
    
    if not account:
        print("ERROR: Could not fetch account info", file=sys.stderr)
        return 1
    
    broker_equity = float(account.get('equity', 0))
    broker_cash = float(account.get('cash', 0))
    broker_portfolio = float(account.get('portfolio_value', 0))
    
    print(f"\nBroker Account:")
    print(f"  Equity: ${broker_equity:,.2f}")
    print(f"  Cash: ${broker_cash:,.2f}")
    print(f"  Portfolio Value: ${broker_portfolio:,.2f}")
    print()
    
    # Calculate actual P&L
    initial_capital = 1_000_000.0
    actual_pnl = broker_equity - initial_capital
    
    print(f"Actual P&L: ${actual_pnl:+,.2f}")
    print()
    
    # Fetch filled orders
    print("Fetching filled orders from Broker...")
    orders = fetch_alpaca_orders(api_key, api_secret, status='filled')
    
    print(f"Fetched {len(orders)} filled orders")
    print()
    
    # Load current pnl_state.json
    state = json.loads(state_file.read_text(encoding="utf-8"))
    current_cumulative = state.get('cumulative_realized_pnl', 0)
    
    print(f"Current pnl_state.json:")
    print(f"  cumulative_realized_pnl: ${current_cumulative:,.2f}")
    print()
    
    print(f"Discrepancy: ${current_cumulative - actual_pnl:+,.2f}")
    print()
    
    if args.dry_run:
        print("DRY RUN: Would update cumulative_realized_pnl to ${:,.2f}".format(actual_pnl))
        print()
        print("To sync individual trade data, we need to:")
        print("  1. Parse filled orders into buy/sell pairs")
        print("  2. Calculate P&L for each closed position")
        print("  3. Rebuild trades array in pnl_state.json")
        print()
        print("This requires more complex logic. For now, we can:")
        print("  - Update cumulative_realized_pnl to match Broker equity")
        print("  - Keep existing trades as reference")
        print()
        print("Run without --dry-run to apply the cumulative update.")
        return 0
    
    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = state_file.parent / f"pnl_state_before_broker_sync_{timestamp}.json"
    shutil.copy2(state_file, backup_file)
    print(f"✅ Created backup: {backup_file}")
    
    # Update cumulative_realized_pnl
    state['cumulative_realized_pnl'] = round(actual_pnl, 2)
    state['last_updated'] = datetime.now().isoformat()
    
    # Add note about sync
    if 'notes' not in state:
        state['notes'] = []
    
    state['notes'].append({
        'timestamp': datetime.now().isoformat(),
        'action': 'broker_sync',
        'description': 'Synced cumulative_realized_pnl with Broker equity',
        'old_value': round(current_cumulative, 2),
        'new_value': round(actual_pnl, 2),
        'broker_equity': round(broker_equity, 2)
    })
    
    # Save
    state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    
    print(f"\n✅ Updated pnl_state.json:")
    print(f"  cumulative_realized_pnl: ${current_cumulative:,.2f} → ${actual_pnl:,.2f}")
    print(f"  Saved to: {state_file}")
    print(f"  Backup: {backup_file}")
    print()
    print("⚠️  NOTE:")
    print("  Individual trade P&L values are NOT updated.")
    print("  They still contain the Yahoo Finance corrected prices.")
    print("  cumulative_realized_pnl now reflects Broker's actual equity.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
