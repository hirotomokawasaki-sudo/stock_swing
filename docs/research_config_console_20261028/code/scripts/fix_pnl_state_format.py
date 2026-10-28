#!/usr/bin/env python3
"""
Fix pnl_state.json to be compatible with PnLState dataclass

Issue: merge_pnl_data.py created JSON with 'metadata' key
PnLState doesn't have this field, so loading fails
"""

import json
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent

print("=" * 70)
print("Fix pnl_state.json format for PnLState compatibility")
print("=" * 70)
print()

# Read current state
with open(PROJECT_ROOT / 'data/tracking/pnl_state.json') as f:
    data = json.load(f)

print("Current keys:", list(data.keys()))
print()

# Calculate missing fields from trades
trades = data.get('trades', [])
closed_trades = [t for t in trades if t.get('status') == 'closed']

cumulative_pnl = sum(t.get('pnl', 0) or 0 for t in closed_trades)
winning_trades = len([t for t in closed_trades if (t.get('pnl') or 0) > 0])
losing_trades = len([t for t in closed_trades if (t.get('pnl') or 0) < 0])
total_trades = len(trades)

# Get peak equity from snapshots
snapshots = data.get('daily_snapshots', [])
peak_equity = max([s.get('equity', 0) for s in snapshots], default=100000.0)

# Calculate max drawdown
max_dd = 0.0
for snap in snapshots:
    equity = snap.get('equity', 0)
    if peak_equity > 0:
        dd = (peak_equity - equity) / peak_equity
        max_dd = max(max_dd, dd)

print("Calculated fields:")
print(f"  cumulative_realized_pnl: ${cumulative_pnl:,.2f}")
print(f"  total_trades: {total_trades}")
print(f"  winning_trades: {winning_trades}")
print(f"  losing_trades: {losing_trades}")
print(f"  peak_equity: ${peak_equity:,.2f}")
print(f"  max_drawdown_pct: {max_dd:.4f}")
print()

# Create compatible state
fixed_state = {
    'created_at': data.get('created_at') or data.get('last_updated') or datetime.now(timezone.utc).isoformat(),
    'last_updated': data.get('last_updated') or datetime.now(timezone.utc).isoformat(),
    'trades': trades,
    'daily_snapshots': snapshots,
    'cumulative_realized_pnl': round(cumulative_pnl, 2),
    'total_trades': total_trades,
    'winning_trades': winning_trades,
    'losing_trades': losing_trades,
    'peak_equity': peak_equity,
    'max_drawdown_pct': round(max_dd, 4),
}

# Backup old file
backup_file = PROJECT_ROOT / 'data/tracking/pnl_state_before_fix.json'
with open(backup_file, 'w') as f:
    json.dump(data, f, indent=2)
print(f"Backed up to {backup_file}")

# Save fixed state
with open(PROJECT_ROOT / 'data/tracking/pnl_state.json', 'w') as f:
    json.dump(fixed_state, f, indent=2)

print("✅ Fixed pnl_state.json format")
print()
print("Summary:")
print(f"  Trades: {len(fixed_state['trades'])}")
print(f"  Snapshots: {len(fixed_state['daily_snapshots'])}")
print(f"  Total P&L: ${fixed_state['cumulative_realized_pnl']:,.2f}")
print(f"  Peak Equity: ${fixed_state['peak_equity']:,.2f}")
print()

