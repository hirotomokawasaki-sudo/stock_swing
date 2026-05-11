#!/usr/bin/env python3
"""Adjust individual trade P&L to match cumulative_realized_pnl.

When cumulative_realized_pnl is synced with Broker but individual trades
are not updated, this script proportionally adjusts each trade's P&L.

Usage:
    python scripts/adjust_individual_pnl.py [--dry-run]
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Adjust individual trade P&L")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be changed without actually changing data")
    args = parser.parse_args()
    
    project_root = Path(__file__).resolve().parents[1]
    state_file = project_root / "data" / "tracking" / "pnl_state.json"
    
    if not state_file.exists():
        print(f"ERROR: {state_file} not found", file=sys.stderr)
        return 1
    
    # Load state
    state = json.loads(state_file.read_text(encoding="utf-8"))
    
    # Get cumulative and calculate current total
    cumulative = state.get('cumulative_realized_pnl', 0)
    closed = [t for t in state.get('trades', []) if t.get('status') == 'closed']
    
    current_total = sum(t.get('pnl', 0) for t in closed if t.get('pnl') is not None)
    
    print(f"Current state:")
    print(f"  cumulative_realized_pnl: ${cumulative:,.2f}")
    print(f"  closed trades: {len(closed)}")
    print(f"  calculated total P&L: ${current_total:,.2f}")
    print(f"  mismatch: ${current_total - cumulative:+,.2f}")
    print()
    
    if abs(current_total - cumulative) < 0.01:
        print("✅ No adjustment needed. P&L is already consistent.")
        return 0
    
    # Calculate scale factor
    if current_total == 0:
        print("ERROR: Cannot adjust when current_total is 0", file=sys.stderr)
        return 1
    
    scale_factor = cumulative / current_total
    
    print(f"Adjustment:")
    print(f"  scale_factor: {scale_factor:.6f}")
    print()
    
    if args.dry_run:
        print("DRY RUN: Would adjust P&L for each closed trade:")
        print()
        
        # Show a few examples
        examples = sorted(closed, key=lambda x: abs(x.get('pnl', 0)), reverse=True)[:5]
        
        print(f"{'Symbol':6} {'Old P&L':>15} {'New P&L':>15} {'Diff':>15}")
        print("=" * 60)
        
        for t in examples:
            old_pnl = t.get('pnl', 0)
            new_pnl = old_pnl * scale_factor
            diff = new_pnl - old_pnl
            
            print(f"{t.get('symbol', 'N/A'):6} ${old_pnl:>14,.2f} ${new_pnl:>14,.2f} ${diff:>14,.2f}")
        
        print()
        print(f"Total closed trades to adjust: {len(closed)}")
        print()
        print("Run without --dry-run to apply adjustments.")
        return 0
    
    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = state_file.parent / f"pnl_state_before_pnl_adjustment_{timestamp}.json"
    shutil.copy2(state_file, backup_file)
    print(f"✅ Created backup: {backup_file}")
    print()
    
    # Adjust each closed trade
    adjusted_count = 0
    
    for trade in state.get('trades', []):
        if trade.get('status') == 'closed':
            old_pnl = trade.get('pnl', 0)
            new_pnl = old_pnl * scale_factor
            
            trade['pnl'] = round(new_pnl, 2)
            
            # Also adjust return_pct if present
            if 'return_pct' in trade and 'entry_price' in trade and trade['entry_price'] > 0:
                old_return = trade.get('return_pct', 0)
                new_return = old_return * scale_factor
                trade['return_pct'] = round(new_return, 6)
            
            adjusted_count += 1
    
    # Update last_updated
    state['last_updated'] = datetime.now().isoformat()
    
    # Save
    state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    
    # Verify
    new_total = sum(t.get('pnl', 0) for t in state['trades'] if t.get('status') == 'closed')
    
    print(f"✅ Adjusted {adjusted_count} closed trades")
    print()
    print(f"Verification:")
    print(f"  old total: ${current_total:,.2f}")
    print(f"  new total: ${new_total:,.2f}")
    print(f"  target (cumulative): ${cumulative:,.2f}")
    print(f"  difference: ${new_total - cumulative:+,.2f}")
    print()
    print(f"✅ Saved to: {state_file}")
    print(f"📝 Backup: {backup_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
