#!/usr/bin/env python3
"""
Rebuild pnl_state.json from broker order history.

This script fetches all filled orders from the broker and reconstructs
pnl_state.json with accurate entry/exit prices and P&L calculations.

Usage:
    python scripts/rebuild_pnl_state_from_broker.py [--dry-run] [--backup]
"""

import argparse
import json
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.sources.broker_client import BrokerClient


def load_env(env_file: Path):
    """Load environment variables from .env file."""
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


def load_existing_tracking_metadata(state_file: Path) -> dict[str, Any]:
    """Load reusable tracking metadata from current pnl_state.json if present."""
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return {
        'created_at': data.get('created_at'),
        'baseline_date': data.get('baseline_date'),
        'baseline_equity': data.get('baseline_equity'),
        'tracking_label': data.get('tracking_label'),
        'performance_scope': data.get('performance_scope'),
        'archived_from_account_id': data.get('archived_from_account_id'),
        'archive_path': data.get('archive_path'),
        'migration_note_path': data.get('migration_note_path'),
    }


def resolve_tracking_metadata(args: argparse.Namespace, existing: dict[str, Any], now_iso: str) -> dict[str, Any]:
    """Resolve tracking metadata for rebuilt pnl_state.

    Priority:
    1. Explicit CLI args
    2. Existing pnl_state metadata
    3. Safe defaults derived from current rebuild timestamp
    """
    baseline_date = args.baseline_date or existing.get('baseline_date') or now_iso[:10]
    baseline_equity = (
        args.baseline_equity
        if args.baseline_equity is not None
        else existing.get('baseline_equity')
        if existing.get('baseline_equity') is not None
        else 1000000.0
    )
    created_at = args.created_at or existing.get('created_at') or now_iso
    tracking_label = (
        args.tracking_label
        or existing.get('tracking_label')
        or f'alpaca_account_epoch_{baseline_date}'
    )
    performance_scope = (
        args.performance_scope
        or existing.get('performance_scope')
        or 'current_account_since_baseline'
    )
    return {
        'created_at': created_at,
        'baseline_date': baseline_date,
        'baseline_equity': float(baseline_equity),
        'tracking_label': tracking_label,
        'performance_scope': performance_scope,
        'archived_from_account_id': existing.get('archived_from_account_id'),
        'archive_path': args.archive_path or existing.get('archive_path'),
        'migration_note_path': args.migration_note_path or existing.get('migration_note_path'),
    }


def fetch_all_filled_orders(broker: BrokerClient) -> list:
    """Fetch all filled orders from broker."""
    print("Fetching filled orders from broker...")
    orders_env = broker.fetch_orders(status='all', limit=500)
    orders = orders_env.payload if hasattr(orders_env, 'payload') else orders_env
    
    filled_orders = [o for o in orders if o.get('status') == 'filled']
    print(f"  Found {len(filled_orders)} filled orders")
    
    return filled_orders


def fetch_broker_open_positions(broker: BrokerClient) -> dict[str, dict]:
    """Fetch current open positions from broker.
    
    Returns:
        Dictionary mapping symbol -> position info with qty and avg_entry_price.
    """
    print("Fetching current open positions from broker...")
    try:
        positions_env = broker.fetch_positions()
        positions = positions_env.payload if hasattr(positions_env, 'payload') else positions_env
        
        if not isinstance(positions, list):
            print("  WARN: broker.fetch_positions() did not return a list")
            return {}
        
        position_map = {}
        for pos in positions:
            symbol = pos.get('symbol')
            qty = float(pos.get('qty', 0) or 0)
            avg_price = float(pos.get('avg_entry_price', 0) or 0)
            
            if symbol and qty > 0 and avg_price > 0:
                position_map[symbol] = {
                    'qty': qty,
                    'avg_entry_price': avg_price,
                    'asset_id': pos.get('asset_id'),
                }
        
        print(f"  Found {len(position_map)} open positions at broker")
        return position_map
        
    except Exception as e:
        print(f"  WARN: Failed to fetch broker positions: {e}")
        return {}


def match_buy_sell_orders(filled_orders: list) -> tuple[list, list]:
    """Match buy and sell orders to create closed trades.
    
    Uses FIFO (First In, First Out) matching.
    Returns tuple of (closed_trades, open_positions_from_fills).
    """
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
    
    # Match buy/sell orders
    print("\nMatching buy/sell orders (FIFO)...")
    trades = []
    trade_num = 0
    open_positions = []
    
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
            return_pct = (exit_price - entry_price) / entry_price if entry_price else 0.0
            
            trade_num += 1
            trade = {
                'trade_id': f"broker_match_{trade_num:04d}_{symbol}",
                'symbol': symbol,
                'strategy_id': 'broker_reconstructed',
                'side': 'buy',
                'qty': int(qty),
                'entry_price': round(entry_price, 2),
                'exit_price': round(exit_price, 2),
                'entry_time': buy['time'],
                'exit_time': sell['time'],
                'pnl': round(pnl, 2),
                'return_pct': round(return_pct, 4),
                'status': 'closed',
                'account_id': None,
                'strategy_version_id': 'broker_reconstructed',
                'broker_order_id': sell['order_id'],
                'original_strategy_id': 'broker_reconstructed',
                'exit_strategy_id': 'broker_reconstructed',
                'exit_reason': 'broker_fill',
            }
            
            trades.append(trade)
            
            sign = '+' if pnl >= 0 else ''
            print(f"  {symbol:6} {int(qty):>4}株 ${entry_price:>7.2f}→${exit_price:>7.2f} = {sign}${pnl:>9.2f} ({return_pct*100:+.2f}%)")
            
            buy['qty'] -= qty
            sell['qty'] -= qty
            
            if buy['qty'] <= 0.01:
                buys.pop(0)
            if sell['qty'] <= 0.01:
                sells.pop(0)
        
        # Remaining buys are open positions
        for buy in buys:
            if buy['qty'] > 0.01:
                trade_num += 1
                open_trade = {
                    'trade_id': f"broker_open_{trade_num:04d}_{symbol}",
                    'symbol': symbol,
                    'strategy_id': 'broker_reconstructed',
                    'side': 'buy',
                    'qty': int(buy['qty']),
                    'entry_price': round(buy['price'], 2),
                    'exit_price': None,
                    'entry_time': buy['time'],
                    'exit_time': None,
                    'pnl': None,
                    'return_pct': None,
                    'status': 'open',
                    'account_id': None,
                    'strategy_version_id': 'broker_reconstructed',
                    'broker_order_id': buy['order_id'],
                    'original_strategy_id': 'broker_reconstructed',
                    'exit_strategy_id': None,
                    'exit_reason': None,
                }
                open_positions.append(open_trade)
                print(f"  {symbol:6} {int(buy['qty']):>4}株 open @ ${buy['price']:.2f}")
    
    return trades, open_positions


def reconcile_open_positions(
    open_from_fills: list,
    broker_positions: dict[str, dict],
    trade_num_offset: int,
) -> list:
    """Reconcile open positions from filled orders with broker truth.
    
    Broker positions are the source of truth. This function:
    1. Uses broker positions as baseline
    2. Enriches with order metadata from fills when available
    3. Creates new entries for broker positions not in fills
    
    Args:
        open_from_fills: Open positions calculated from filled orders.
        broker_positions: Current open positions from broker API.
        trade_num_offset: Starting trade number for new broker-only positions.
    
    Returns:
        Reconciled list of open position trades.
    """
    print("\nReconciling open positions with broker truth...")
    
    # Map fills by symbol
    fills_by_symbol = {}
    for pos in open_from_fills:
        symbol = pos['symbol']
        if symbol not in fills_by_symbol:
            fills_by_symbol[symbol] = []
        fills_by_symbol[symbol].append(pos)
    
    reconciled = []
    trade_num = trade_num_offset
    
    # Process each broker position
    for symbol in sorted(broker_positions.keys()):
        broker_pos = broker_positions[symbol]
        broker_qty = broker_pos['qty']
        broker_price = broker_pos['avg_entry_price']
        
        fills = fills_by_symbol.get(symbol, [])
        
        if fills:
            # Have fill history for this symbol - use it but verify qty
            total_fill_qty = sum(f['qty'] for f in fills)
            
            if abs(total_fill_qty - broker_qty) < 0.01:
                # Quantities match - use fill history as-is
                print(f"  ✓ {symbol:6} {int(broker_qty):>4}株 matched from fills")
                reconciled.extend(fills)
            else:
                # Quantity mismatch - trust broker and create new entry
                print(f"  ⚠ {symbol:6} qty mismatch: fills={int(total_fill_qty)} broker={int(broker_qty)} - using broker")
                trade_num += 1
                reconciled.append({
                    'trade_id': f"broker_open_{trade_num:04d}_{symbol}",
                    'symbol': symbol,
                    'strategy_id': 'broker_reconstructed',
                    'side': 'buy',
                    'qty': int(broker_qty),
                    'entry_price': round(broker_price, 2),
                    'exit_price': None,
                    'entry_time': None,  # Unknown from broker position
                    'exit_time': None,
                    'pnl': None,
                    'return_pct': None,
                    'status': 'open',
                    'account_id': None,
                    'strategy_version_id': 'broker_reconstructed',
                    'broker_order_id': None,
                    'original_strategy_id': 'broker_reconstructed',
                    'exit_strategy_id': None,
                    'exit_reason': None,
                })
        else:
            # No fill history - this is a broker-only position (likely filled after last rebuild)
            print(f"  + {symbol:6} {int(broker_qty):>4}株 broker-only position @ ${broker_price:.2f}")
            trade_num += 1
            reconciled.append({
                'trade_id': f"broker_open_{trade_num:04d}_{symbol}",
                'symbol': symbol,
                'strategy_id': 'broker_reconstructed',
                'side': 'buy',
                'qty': int(broker_qty),
                'entry_price': round(broker_price, 2),
                'exit_price': None,
                'entry_time': None,
                'exit_time': None,
                'pnl': None,
                'return_pct': None,
                'status': 'open',
                'account_id': None,
                'strategy_version_id': 'broker_reconstructed',
                'broker_order_id': None,
                'original_strategy_id': 'broker_reconstructed',
                'exit_strategy_id': None,
                'exit_reason': None,
            })
    
    # Warn about positions in fills but not at broker (already closed)
    for symbol in fills_by_symbol:
        if symbol not in broker_positions:
            fill_qty = sum(f['qty'] for f in fills_by_symbol[symbol])
            print(f"  ⚠ {symbol:6} {int(fill_qty):>4}株 in fills but NOT at broker (likely closed)")
    
    print(f"  Result: {len(reconciled)} open positions after reconciliation")
    return reconciled


def calculate_summary(trades: list, open_positions: list) -> dict:
    """Calculate summary statistics."""
    closed_trades = [t for t in trades if t['status'] == 'closed']
    wins = [t for t in closed_trades if t['pnl'] > 0]
    losses = [t for t in closed_trades if t['pnl'] < 0]
    
    total_pnl = sum(t['pnl'] for t in closed_trades)
    win_rate = len(wins) / len(closed_trades) if closed_trades else 0.0
    
    return {
        'total_trades': len(closed_trades) + len(open_positions),
        'closed_trades': len(closed_trades),
        'open_trades': len(open_positions),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': round(win_rate, 4),
        'cumulative_realized_pnl': round(total_pnl, 2),
        'avg_pnl_per_trade': round(total_pnl / len(closed_trades), 2) if closed_trades else 0.0,
    }


def rebuild_pnl_state(
    broker: BrokerClient,
    tracking_metadata: dict[str, Any] | None = None,
) -> dict:
    """Rebuild pnl_state.json from broker order history and current positions."""
    filled_orders = fetch_all_filled_orders(broker)
    closed_trades, open_from_fills = match_buy_sell_orders(filled_orders)
    
    # Fetch current broker positions and reconcile
    broker_positions = fetch_broker_open_positions(broker)
    trade_num_offset = len(closed_trades) + len(open_from_fills)
    open_positions = reconcile_open_positions(open_from_fills, broker_positions, trade_num_offset)

    all_trades = closed_trades + open_positions
    summary = calculate_summary(closed_trades, open_positions)

    now = datetime.now(timezone.utc).isoformat()
    tracking_metadata = tracking_metadata or {}
    baseline_equity = float(tracking_metadata.get('baseline_equity') or 1000000.0)

    # Get broker account info
    try:
        account_resp = broker.fetch_account()
        account = account_resp.payload if hasattr(account_resp, 'payload') else account_resp
        broker_account_id = account.get('account_number') or account.get('id')
    except Exception:
        broker_account_id = None

    pnl_state = {
        'created_at': tracking_metadata.get('created_at') or now,
        'last_updated': now,
        'trades': all_trades,
        'daily_snapshots': [],
        'strategy_daily_snapshots': [],
        'cumulative_realized_pnl': summary['cumulative_realized_pnl'],
        'total_trades': len(all_trades),
        'winning_trades': summary['winning_trades'],
        'losing_trades': summary['losing_trades'],
        'peak_equity': baseline_equity + summary['cumulative_realized_pnl'],
        'max_drawdown_pct': 0.0,
        'broker_account_id': broker_account_id,
        'baseline_date': tracking_metadata.get('baseline_date') or now[:10],
        'baseline_equity': baseline_equity,
        'tracking_label': tracking_metadata.get('tracking_label') or f'broker_rebuilt_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}',
        'performance_scope': tracking_metadata.get('performance_scope') or 'current_account_since_baseline',
        'archived_from_account_id': tracking_metadata.get('archived_from_account_id'),
        'archive_path': tracking_metadata.get('archive_path'),
        'migration_note_path': tracking_metadata.get('migration_note_path'),
    }

    return pnl_state


def main():
    parser = argparse.ArgumentParser(description="Rebuild pnl_state.json from broker order history")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without writing")
    parser.add_argument("--backup", action="store_true", help="Create backup of existing pnl_state.json")
    parser.add_argument("--baseline-equity", type=float, default=None, help="Override baseline equity")
    parser.add_argument("--baseline-date", type=str, default=None, help="Override baseline date (YYYY-MM-DD)")
    parser.add_argument("--created-at", type=str, default=None, help="Override tracking created_at (ISO-8601)")
    parser.add_argument("--tracking-label", type=str, default=None, help="Override tracking label")
    parser.add_argument("--performance-scope", type=str, default=None, help="Override performance scope")
    parser.add_argument("--archive-path", type=str, default=None, help="Override archive path metadata")
    parser.add_argument("--migration-note-path", type=str, default=None, help="Override migration note path metadata")
    args = parser.parse_args()
    
    # Load environment
    load_env(PROJECT_ROOT / '.env')
    api_key = os.environ.get('BROKER_API_KEY')
    api_secret = os.environ.get('BROKER_API_SECRET')
    
    if not api_key or not api_secret:
        print("ERROR: BROKER_API_KEY and BROKER_API_SECRET must be set", file=sys.stderr)
        return 1
    
    # Initialize broker client
    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
    state_file = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
    existing_meta = load_existing_tracking_metadata(state_file)
    resolved_meta = resolve_tracking_metadata(args, existing_meta, datetime.now(timezone.utc).isoformat())

    # Rebuild state
    print("=" * 70)
    print("Rebuilding pnl_state.json from Broker Order History")
    print("=" * 70)
    print()
    print("Tracking metadata:")
    print(json.dumps(resolved_meta, indent=2, ensure_ascii=False))
    print()

    pnl_state = rebuild_pnl_state(broker, tracking_metadata=resolved_meta)
    
    # Print summary
    print()
    print("=" * 70)
    print("Summary:")
    print("=" * 70)
    print(f"Total Trades: {pnl_state['total_trades']}")
    print(f"Closed: {len([t for t in pnl_state['trades'] if t['status'] == 'closed'])}")
    print(f"Open: {len([t for t in pnl_state['trades'] if t['status'] == 'open'])}")
    print(f"Wins: {pnl_state['winning_trades']}")
    print(f"Losses: {pnl_state['losing_trades']}")
    print(f"Win Rate: {pnl_state['winning_trades'] / (pnl_state['winning_trades'] + pnl_state['losing_trades']) * 100:.1f}%" if (pnl_state['winning_trades'] + pnl_state['losing_trades']) > 0 else "N/A")
    print(f"Cumulative Realized P&L: ${pnl_state['cumulative_realized_pnl']:+,.2f}")
    print()
    
    if args.dry_run:
        print("DRY RUN: Would write to data/tracking/pnl_state.json")
        print()
        print("Sample trades:")
        for trade in pnl_state['trades'][:10]:
            print(f"  {trade['symbol']:6} {trade['status']:6} qty={trade['qty']:>4} entry=${trade['entry_price']:>7.2f} exit={trade.get('exit_price') or 'open':>7} pnl={trade.get('pnl') or 'N/A':>10}")
        return 0
    
    # Backup if requested
    if args.backup and state_file.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = state_file.parent / f"pnl_state_backup_{timestamp}.json"
        shutil.copy2(state_file, backup_file)
        print(f"✅ Created backup: {backup_file}")
    
    # Write new state
    state_file.write_text(json.dumps(pnl_state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Wrote pnl_state.json: {state_file}")
    print()
    print("Next: Restart console to see accurate data")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
