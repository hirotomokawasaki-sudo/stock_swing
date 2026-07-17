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
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.sources.broker_client import BrokerClient


def fetch_yahoo_daily_bars(symbol: str) -> dict[str, tuple[float, float, float]]:
    """Fetch recent daily bars from Yahoo Finance keyed by date."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return {}

    try:
        result = data.get("chart", {}).get("result", [{}])[0]
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
    except Exception:
        return {}

    bars: dict[str, tuple[float, float, float]] = {}
    for ts, high, low, close in zip(timestamps, highs, lows, closes):
        if high is None or low is None or close is None:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        bars[day] = (float(low), float(high), float(close))
    return bars


def maybe_correct_scaled_price(
    symbol: str,
    price: float,
    fill_time: str,
    market_cache: dict[str, dict[str, tuple[float, float, float]]],
) -> tuple[float, int | None]:
    """Correct obvious scale errors in broker fill prices using market data.

    Some broker paper fills have been observed at 10x/100x market price.
    If dividing by 10 or 100 places the fill back near the day's market range,
    apply that correction.
    """
    if price <= 0 or not fill_time:
        return price, None

    day = fill_time[:10]
    bars = market_cache.get(symbol)
    if bars is None:
        bars = fetch_yahoo_daily_bars(symbol)
        market_cache[symbol] = bars
    market_bar = bars.get(day) if bars else None
    if not market_bar:
        return price, None

    low, high, close = market_bar
    if low <= price <= high:
        return price, None

    for factor in (10, 100):
        candidate = price / factor
        # Allow a small cushion around the daily range to tolerate minute-level fills.
        if (low * 0.97) <= candidate <= (high * 1.03):
            return round(candidate, 4), factor
        if close > 0 and abs(candidate - close) / close <= 0.08:
            return round(candidate, 4), factor

    return price, None


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
        # Preserve chart history — do NOT reset on rebuild
        'daily_snapshots': data.get('daily_snapshots', []),
        'strategy_daily_snapshots': data.get('strategy_daily_snapshots', []),
    }


def load_existing_attribution(state_file: Path) -> dict[str, Any]:
    """Extract exit_reason attribution and quarantined_trades from current pnl_state.

    Returns a dict with:
      'by_exit_order_id'  : exit_broker_order_id -> exit_reason   (highest priority)
      'by_key'            : (symbol, exit_time[:19], pnl_int) -> exit_reason  (fallback)
      'quarantined_trades': list of quarantined trade dicts

    Only non-broker_fill reasons are indexed (broker_fill is the rebuild default).
    Added 2026-07-17 to prevent attribution loss on rebuild.
    """
    if not state_file.exists():
        return {'by_exit_order_id': {}, 'by_key': {}, 'quarantined_trades': []}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {'by_exit_order_id': {}, 'by_key': {}, 'quarantined_trades': []}

    by_exit_order_id: dict[str, str] = {}
    by_key: dict[tuple, str] = {}
    collisions: set = set()

    for trade in data.get('trades', []):
        if trade.get('status') == 'open':
            continue
        reason = trade.get('exit_reason', '')
        if not reason or reason == 'broker_fill':
            continue

        # Primary: exit_broker_order_id (sell order id)
        eid = trade.get('exit_broker_order_id', '')
        if eid:
            by_exit_order_id[eid] = reason

        # Secondary: (symbol, exit_time[:19], pnl rounded to int)
        sym = trade.get('symbol', '')
        et = str(trade.get('exit_time', ''))[:19]
        pnl_i = int(round(float(trade.get('pnl', 0) or 0)))
        key = (sym, et, pnl_i)
        if key in by_key and by_key[key] != reason:
            collisions.add(key)   # ambiguous; skip
        else:
            by_key[key] = reason

    # Remove ambiguous keys
    for k in collisions:
        by_key.pop(k, None)

    return {
        'by_exit_order_id': by_exit_order_id,
        'by_key': by_key,
        'quarantined_trades': data.get('quarantined_trades', []),
    }


def apply_attribution(pnl_state: dict, attribution: dict[str, Any]) -> dict[str, int]:
    """Merge saved attribution back onto freshly rebuilt trades.

    Mutates pnl_state['trades'] in-place and sets pnl_state['quarantined_trades'].
    Returns stats dict: {'by_exit_order': N, 'by_key': N, 'kept_broker_fill': N}.
    Added 2026-07-17.
    """
    by_exit_order_id = attribution.get('by_exit_order_id', {})
    by_key = attribution.get('by_key', {})
    quarantined = attribution.get('quarantined_trades', [])

    stats = {'by_exit_order': 0, 'by_key': 0, 'kept_broker_fill': 0}

    for trade in pnl_state.get('trades', []):
        if trade.get('status') == 'open':
            continue
        if trade.get('exit_reason') != 'broker_fill':
            continue

        # Try primary key: exit_broker_order_id
        eid = trade.get('exit_broker_order_id', '')
        if eid and eid in by_exit_order_id:
            trade['exit_reason'] = by_exit_order_id[eid]
            stats['by_exit_order'] += 1
            continue

        # Try secondary key: (symbol, exit_time[:19], pnl_int)
        sym = trade.get('symbol', '')
        et = str(trade.get('exit_time', ''))[:19]
        pnl_i = int(round(float(trade.get('pnl', 0) or 0)))
        key = (sym, et, pnl_i)
        if key in by_key:
            trade['exit_reason'] = by_key[key]
            stats['by_key'] += 1
            continue

        stats['kept_broker_fill'] += 1

    pnl_state['quarantined_trades'] = quarantined
    return stats


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


def load_corporate_actions(project_root: Path) -> list[dict]:
    """Load corporate actions registry from data/corporate_actions.json."""
    ca_path = project_root / "data" / "corporate_actions.json"
    try:
        with open(ca_path) as f:
            data = json.load(f)
        return data.get("actions", [])
    except Exception:
        return []


def apply_split_adjustment(
    symbol: str,
    entry_price: float,
    entry_time: str,
    exit_time: str,
    corporate_actions: list[dict],
) -> tuple[float, float | None]:
    """Adjust entry price for splits that occurred between buy and sell.

    If a forward split ex_date falls between the buy fill date and the sell
    fill date, the recorded buy price is pre-split while the sell price is
    post-split.  Dividing the entry price by the split ratio makes both
    prices comparable on a post-split basis.

    Returns (adjusted_entry_price, split_ratio_applied | None).
    """
    for action in corporate_actions:
        if action.get("symbol") != symbol:
            continue
        if action.get("type") != "split" or action.get("direction") != "forward":
            continue
        ex_date = action.get("ex_date", "")[:10]  # YYYY-MM-DD
        if not ex_date:
            continue
        ratio = float(action.get("ratio", 1))
        if ratio <= 1:
            continue
        buy_date = entry_time[:10]
        sell_date = exit_time[:10]
        # Buy is pre-split, sell is post-split
        if buy_date < ex_date <= sell_date:
            adjusted = round(entry_price / ratio, 4)
            return adjusted, ratio
    return entry_price, None


def match_buy_sell_orders(
    filled_orders: list,
    corporate_actions: list[dict] | None = None,
) -> tuple[list, list]:
    """Match buy and sell orders to create closed trades.
    
    Uses FIFO (First In, First Out) matching.
    Corporate actions (splits) are applied when buy/sell straddle an ex_date.
    Returns tuple of (closed_trades, open_positions_from_fills).
    """
    if corporate_actions is None:
        corporate_actions = []
    by_symbol = defaultdict(lambda: {'buy': [], 'sell': []})
    market_cache: dict[str, dict[str, tuple[float, float, float]]] = {}
    
    for order in filled_orders:
        symbol = order.get('symbol')
        side = order.get('side')
        filled_qty = float(order.get('filled_qty', 0))
        raw_filled_price = float(order.get('filled_avg_price', 0))
        filled_at = order.get('filled_at', '')
        order_id = order.get('id')

        filled_price, correction_factor = maybe_correct_scaled_price(
            symbol,
            raw_filled_price,
            filled_at,
            market_cache,
        )
        if correction_factor:
            print(
                f"  ↺ {symbol:6} corrected {side} fill price "
                f"${raw_filled_price:.4f} -> ${filled_price:.4f} (/ {correction_factor})"
            )

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

            # Apply split adjustment when buy/sell straddle a split ex_date
            adjusted_entry, split_ratio = apply_split_adjustment(
                symbol, entry_price, buy['time'], sell['time'], corporate_actions
            )
            if split_ratio is not None:
                print(
                    f"  ✂ {symbol:6} split {split_ratio:.0f}:1 adjusted entry "
                    f"${entry_price:.2f} -> ${adjusted_entry:.2f} (ex_date straddle)"
                )
                entry_price = adjusted_entry

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
                'broker_order_id': buy['order_id'],
                'exit_broker_order_id': sell['order_id'],
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
    corporate_actions = load_corporate_actions(PROJECT_ROOT)
    closed_trades, open_from_fills = match_buy_sell_orders(filled_orders, corporate_actions)
    
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
        'daily_snapshots': tracking_metadata.get('daily_snapshots', []),
        'strategy_daily_snapshots': tracking_metadata.get('strategy_daily_snapshots', []),
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
    parser.add_argument(
        "--preserve-attribution",
        action="store_true",
        help=(
            "Restore exit_reason / quarantined_trades from the current pnl_state after rebuild. "
            "Prevents attribution loss caused by rebuild resetting all exit_reason to broker_fill. "
            "Recommended for routine HALT-recovery rebuilds."
        ),
    )
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

    # Load attribution BEFORE rebuild (if --preserve-attribution)
    attribution: dict[str, Any] = {'by_exit_order_id': {}, 'by_key': {}, 'quarantined_trades': []}
    if args.preserve_attribution:
        attribution = load_existing_attribution(state_file)
        n_attr = len(attribution['by_exit_order_id']) + len(attribution['by_key'])
        n_q = len(attribution['quarantined_trades'])
        print(f"ℹ️  --preserve-attribution: loaded {n_attr} attribution entries, "
              f"{n_q} quarantined trades from existing pnl_state.")
    else:
        # Warn operator that attribution will be lost
        if state_file.exists():
            try:
                _existing = json.loads(state_file.read_text(encoding="utf-8"))
                _closed = [t for t in _existing.get('trades', []) if t.get('status') != 'open']
                _non_bf = sum(1 for t in _closed if t.get('exit_reason', 'broker_fill') != 'broker_fill')
                _q_count = len(_existing.get('quarantined_trades', []))
                if _non_bf > 0 or _q_count > 0:
                    print()
                    print("⚠️  WARNING: --preserve-attribution was NOT specified.")
                    print(f"   Current pnl_state has {_non_bf} attributed exits "
                          f"and {_q_count} quarantined trades.")
                    print("   These will be LOST after rebuild.")
                    print("   To preserve them, re-run with:  --preserve-attribution")
                    print()
            except Exception:
                pass

    # Rebuild state
    print("=" * 70)
    print("Rebuilding pnl_state.json from Broker Order History")
    print("=" * 70)
    print()
    print("Tracking metadata:")
    print(json.dumps(resolved_meta, indent=2, ensure_ascii=False))
    print()

    pnl_state = rebuild_pnl_state(broker, tracking_metadata=resolved_meta)

    # Merge attribution back (if --preserve-attribution)
    if args.preserve_attribution:
        attr_stats = apply_attribution(pnl_state, attribution)
        print()
        print("✅ Attribution restored:")
        print(f"   by exit_broker_order_id : {attr_stats['by_exit_order']}")
        print(f"   by (symbol,exit_time,pnl): {attr_stats['by_key']}")
        print(f"   kept as broker_fill      : {attr_stats['kept_broker_fill']}")
        print(f"   quarantined_trades       : {len(pnl_state.get('quarantined_trades', []))}")

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
    backup_file = None
    if args.backup and state_file.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = state_file.parent / f"pnl_state_backup_{timestamp}.json"
        shutil.copy2(state_file, backup_file)
        print(f"✅ Created backup: {backup_file}")
    
    # Write new state
    state_file.write_text(json.dumps(pnl_state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Wrote pnl_state.json: {state_file}")
    print()

    # --- Post-rebuild integrity check (auto-fix if backup was created) ---
    print("Running post-rebuild integrity check...")
    try:
        import subprocess
        verify_args = [sys.executable, str(PROJECT_ROOT / "scripts" / "verify_rebuild_integrity.py")]
        if backup_file and backup_file.exists():
            verify_args += ["--backup", str(backup_file), "--fix"]
        else:
            verify_args += ["--fix"]
        result = subprocess.run(verify_args, capture_output=True, text=True)
        print(result.stdout)
        if result.returncode != 0:
            print(f"⚠️  Post-check detected issues — auto-fix applied.")
            if result.stderr:
                print(result.stderr)
        else:
            print("✅ Post-rebuild integrity check passed.")
    except Exception as e:
        print(f"WARN: Could not run post-rebuild check: {e}")

    print("Next: Restart console to see accurate data")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
