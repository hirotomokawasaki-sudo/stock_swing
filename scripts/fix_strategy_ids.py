#!/usr/bin/env python3
"""Fix strategy_id in PnL tracker by reading from decision files."""

import sys
import json
from pathlib import Path
from collections import defaultdict

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.tracking.pnl_tracker import PnLTracker

def find_strategy_and_time_for_symbol(symbol: str, decisions_dir: Path) -> tuple:
    """Find most common strategy and earliest entry time for a symbol from decision files."""
    strategies = []
    entry_times = []
    
    decision_files = sorted(
        decisions_dir.glob(f"decision_{symbol}_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=False  # Oldest first to find earliest entry
    )
    
    for df in decision_files[:20]:  # Check last 20 decisions
        try:
            decision = json.loads(df.read_text())
            if decision.get('action') == 'buy':
                strategy_id = decision.get('strategy_id')
                if strategy_id:
                    strategies.append(strategy_id)
                
                # Get timestamp from decision (try multiple fields)
                timestamp = decision.get('timestamp') or decision.get('generated_at')
                if timestamp and not entry_times:  # Only take first (earliest) entry
                    entry_times.append(timestamp)
        except:
            continue
    
    strategy = 'unknown'
    entry_time = None
    
    if strategies:
        # Return most common strategy
        from collections import Counter
        strategy = Counter(strategies).most_common(1)[0][0]
    
    if entry_times:
        entry_time = entry_times[0]  # Earliest entry
    
    return strategy, entry_time

def main():
    tracker = PnLTracker(PROJECT_ROOT)
    decisions_dir = PROJECT_ROOT / "data" / "decisions"
    
    if not decisions_dir.exists():
        print(f"Error: {decisions_dir} not found")
        return
    
    print("Fixing strategy_id in PnL tracker...")
    print(f"Total trades: {len(tracker.state.trades)}")
    print()
    
    # Build strategy and entry_time map for each symbol
    symbol_info = {}
    symbols = set(t.get('symbol') for t in tracker.state.trades if t.get('symbol'))
    
    for symbol in symbols:
        strategy, entry_time = find_strategy_and_time_for_symbol(symbol, decisions_dir)
        symbol_info[symbol] = {'strategy': strategy, 'entry_time': entry_time}
        print(f"  {symbol}: {strategy}, entry_time={entry_time}")
    
    print()
    print("Updating trades...")
    
    updated = 0
    for trade in tracker.state.trades:
        symbol = trade.get('symbol')
        if symbol and symbol in symbol_info:
            info = symbol_info[symbol]
            
            # Update strategy_id
            old_strategy = trade.get('strategy_id', 'N/A')
            new_strategy = info['strategy']
            if old_strategy in ['N/A', None, 'unknown', 'breakout_momentum_v1']:
                trade['strategy_id'] = new_strategy
                updated += 1
            
            # Update entry_time if available and trade is open
            if info['entry_time'] and trade.get('status') == 'open':
                trade['entry_time'] = info['entry_time']
    
    print(f"Updated {updated} trades")
    
    # Save
    print("Saving...")
    tracker._save_state()
    
    print("Done!")
    print()
    
    # Verify
    from collections import Counter
    strategies = Counter([t.get('strategy_id', 'N/A') for t in tracker.state.trades])
    print('Strategy breakdown (after fix):')
    for strategy, count in strategies.most_common():
        print(f'  {strategy}: {count} trades')

if __name__ == '__main__':
    main()
