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

def find_strategy_for_symbol(symbol: str, decisions_dir: Path) -> str:
    """Find most common strategy for a symbol from decision files."""
    strategies = []
    
    decision_files = sorted(
        decisions_dir.glob(f"decision_{symbol}_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    
    for df in decision_files[:20]:  # Check last 20 decisions
        try:
            decision = json.loads(df.read_text())
            if decision.get('action') == 'buy':
                strategy_id = decision.get('strategy_id')
                if strategy_id:
                    strategies.append(strategy_id)
        except:
            continue
    
    if strategies:
        # Return most common strategy
        from collections import Counter
        return Counter(strategies).most_common(1)[0][0]
    
    return 'unknown'

def main():
    tracker = PnLTracker(PROJECT_ROOT)
    decisions_dir = PROJECT_ROOT / "data" / "decisions"
    
    if not decisions_dir.exists():
        print(f"Error: {decisions_dir} not found")
        return
    
    print("Fixing strategy_id in PnL tracker...")
    print(f"Total trades: {len(tracker.state.trades)}")
    print()
    
    # Build strategy map for each symbol
    symbol_strategies = {}
    symbols = set(t.get('symbol') for t in tracker.state.trades if t.get('symbol'))
    
    for symbol in symbols:
        strategy = find_strategy_for_symbol(symbol, decisions_dir)
        symbol_strategies[symbol] = strategy
        print(f"  {symbol}: {strategy}")
    
    print()
    print("Updating trades...")
    
    updated = 0
    for trade in tracker.state.trades:
        symbol = trade.get('symbol')
        if symbol and symbol in symbol_strategies:
            old_strategy = trade.get('strategy_id', 'N/A')
            new_strategy = symbol_strategies[symbol]
            if old_strategy in ['N/A', None, 'unknown']:
                trade['strategy_id'] = new_strategy
                updated += 1
    
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
