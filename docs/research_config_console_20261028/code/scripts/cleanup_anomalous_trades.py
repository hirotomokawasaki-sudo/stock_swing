#!/usr/bin/env python3
"""Clean up anomalous trades from pnl_state.json.

Removes trades with:
- Extreme return_pct (> 50% or < -50%)
- Invalid prices (entry_price or exit_price <= 0)
"""

import json
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).resolve().parents[1]
state_path = project_root / "data" / "tracking" / "pnl_state.json"

if not state_path.exists():
    print(f"ERROR: {state_path} not found")
    sys.exit(1)

# Backup first
backup_path = state_path.parent / f"pnl_state_before_cleanup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
backup_path.write_text(state_path.read_text(encoding="utf-8"), encoding="utf-8")
print(f"✅ Backup created: {backup_path}")

# Load state
data = json.loads(state_path.read_text(encoding="utf-8"))
original_trades = data.get("trades", [])
print(f"\n📊 Original trades: {len(original_trades)}")

# Filter anomalies
cleaned_trades = []
removed_count = 0
removed_trades = []

for trade in original_trades:
    is_anomaly = False
    reason = None
    
    # Check 1: Extreme return
    return_pct = trade.get("return_pct")
    if return_pct is not None and (return_pct > 0.5 or return_pct < -0.5):
        is_anomaly = True
        reason = f"extreme_return ({return_pct:.2%})"
    
    # Check 2: Invalid entry price
    entry_price = trade.get("entry_price")
    if entry_price is not None and entry_price <= 0:
        is_anomaly = True
        reason = f"invalid_entry_price ({entry_price})"
    
    # Check 3: Invalid exit price (for closed trades)
    if trade.get("status") == "closed":
        exit_price = trade.get("exit_price")
        if exit_price is not None and exit_price <= 0:
            is_anomaly = True
            reason = f"invalid_exit_price ({exit_price})"
    
    if is_anomaly:
        removed_count += 1
        removed_trades.append({
            "symbol": trade.get("symbol"),
            "entry_time": trade.get("entry_time"),
            "exit_time": trade.get("exit_time"),
            "pnl": trade.get("pnl"),
            "return_pct": trade.get("return_pct"),
            "reason": reason,
        })
    else:
        cleaned_trades.append(trade)

print(f"❌ Anomalous trades removed: {removed_count}")

if removed_count > 0:
    print("\n🔍 Removed trades:")
    for rt in removed_trades[:10]:  # Show first 10
        print(f"  {rt['symbol']:<6} {rt.get('entry_time', 'N/A')[:19]} → {rt.get('exit_time', 'N/A')[:19]}")
        print(f"         PnL: ${rt.get('pnl', 0):,.2f}  Return: {rt.get('return_pct', 0):.2%}  Reason: {rt['reason']}")
    
    if removed_count > 10:
        print(f"  ... and {removed_count - 10} more")

# Recalculate cumulative stats
closed_trades = [t for t in cleaned_trades if t.get("status") == "closed"]
winning_trades = [t for t in closed_trades if (t.get("pnl") or 0) > 0]
losing_trades = [t for t in closed_trades if (t.get("pnl") or 0) < 0]
cumulative_realized_pnl = sum(t.get("pnl", 0) or 0 for t in closed_trades)

data["trades"] = cleaned_trades
data["total_trades"] = len(cleaned_trades)
data["cumulative_realized_pnl"] = round(cumulative_realized_pnl, 2)
data["winning_trades"] = len(winning_trades)
data["losing_trades"] = len(losing_trades)
data["last_updated"] = datetime.utcnow().isoformat() + "+00:00"

# Recalculate max drawdown
max_dd = 0.0
peak = 100_000.0
running = 100_000.0
for t in sorted(closed_trades, key=lambda x: x.get("exit_time") or ""):
    running += t.get("pnl", 0) or 0
    if running > peak:
        peak = running
    if peak > 0:
        dd = (peak - running) / peak
        if dd > max_dd:
            max_dd = dd

data["peak_equity"] = round(peak, 2)
data["max_drawdown_pct"] = round(max_dd, 4)

# Save cleaned state
state_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"\n✅ Cleaned state saved: {state_path}")
print(f"\n📊 New stats:")
print(f"  Total trades: {len(cleaned_trades)}")
print(f"  Closed: {len(closed_trades)}")
print(f"  Wins: {len(winning_trades)}")
print(f"  Losses: {len(losing_trades)}")
print(f"  Cumulative PnL: ${cumulative_realized_pnl:,.2f}")
print(f"  Peak equity: ${peak:,.2f}")
print(f"  Max DD: {max_dd:.2%}")
