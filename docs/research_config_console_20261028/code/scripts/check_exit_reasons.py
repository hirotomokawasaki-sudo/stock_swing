#!/usr/bin/env python3
"""Check exit reasons from pnl_state.json"""

import json
from pathlib import Path
from collections import Counter

project_root = Path(__file__).resolve().parents[1]
pnl_path = project_root / 'data' / 'tracking' / 'pnl_state.json'

with open(pnl_path, 'r') as f:
    data = json.load(f)

trades = data.get('trades', [])
closed_trades = [t for t in trades if t.get('status') == 'closed']

print(f"\n=== EXIT REASON ANALYSIS ===")
print(f"Total closed trades: {len(closed_trades)}")

# Group by exit_reason
reason_data = {}
for trade in closed_trades:
    reason = trade.get('exit_reason', 'unknown')
    pnl = float(trade.get('pnl', 0) or 0)
    
    if reason not in reason_data:
        reason_data[reason] = {
            'count': 0,
            'winning': 0,
            'losing': 0,
            'total_pnl': 0.0,
        }
    
    row = reason_data[reason]
    row['count'] += 1
    row['total_pnl'] += pnl
    if pnl > 0:
        row['winning'] += 1
    elif pnl < 0:
        row['losing'] += 1

# Calculate metrics and display
print(f"\n{'Reason':<15} {'Count':<8} {'Win%':<8} {'Avg P&L':<12} {'Total P&L':<12}")
print("=" * 65)

for reason, row in sorted(reason_data.items(), key=lambda x: x[1]['count'], reverse=True):
    count = row['count']
    win_rate = (row['winning'] / count * 100) if count else 0
    avg_pnl = row['total_pnl'] / count if count else 0
    total_pnl = row['total_pnl']
    
    print(f"{reason:<15} {count:<8} {win_rate:>6.1f}% ${avg_pnl:>9.2f}  ${total_pnl:>10.2f}")

# Filter for simple_exit_v1 only
simple_exit_trades = [t for t in closed_trades if t.get('exit_strategy_id') == 'simple_exit_v1']
print(f"\n=== SIMPLE_EXIT_V1 BREAKDOWN ===")
print(f"Total simple_exit_v1 trades: {len(simple_exit_trades)}")

reason_data_exit = {}
for trade in simple_exit_trades:
    reason = trade.get('exit_reason', 'unknown')
    pnl = float(trade.get('pnl', 0) or 0)
    
    if reason not in reason_data_exit:
        reason_data_exit[reason] = {
            'count': 0,
            'winning': 0,
            'losing': 0,
            'total_pnl': 0.0,
        }
    
    row = reason_data_exit[reason]
    row['count'] += 1
    row['total_pnl'] += pnl
    if pnl > 0:
        row['winning'] += 1
    elif pnl < 0:
        row['losing'] += 1

print(f"\n{'Reason':<15} {'Count':<8} {'Win%':<8} {'Avg P&L':<12} {'Total P&L':<12}")
print("=" * 65)

for reason, row in sorted(reason_data_exit.items(), key=lambda x: x[1]['count'], reverse=True):
    count = row['count']
    win_rate = (row['winning'] / count * 100) if count else 0
    avg_pnl = row['total_pnl'] / count if count else 0
    total_pnl = row['total_pnl']
    
    print(f"{reason:<15} {count:<8} {win_rate:>6.1f}% ${avg_pnl:>9.2f}  ${total_pnl:>10.2f}")

