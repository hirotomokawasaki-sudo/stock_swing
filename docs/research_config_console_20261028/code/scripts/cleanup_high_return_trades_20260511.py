#!/usr/bin/env python3
"""Clean up trades with 30-50% returns (likely Alpaca API anomalies).

These trades are less extreme than the >50% ones, but still unrealistic
for short-term paper trading given the market conditions.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

def main():
    project_root = Path(__file__).resolve().parents[1]
    state_file = project_root / "data" / "tracking" / "pnl_state.json"
    
    if not state_file.exists():
        print(f"Error: {state_file} not found")
        return 1
    
    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = state_file.parent / f"pnl_state_before_high_return_cleanup_{timestamp}.json"
    shutil.copy2(state_file, backup_file)
    print(f"✅ Created backup: {backup_file}")
    
    # Load state
    data = json.loads(state_file.read_text(encoding="utf-8"))
    trades = data.get("trades", [])
    
    print(f"\nTotal trades before cleanup: {len(trades)}")
    
    # Find high return trades (30-50%)
    high_return = []
    for t in trades:
        if t.get("status") == "closed":
            ret = t.get("return_pct", 0)
            if abs(ret) > 0.30 and abs(ret) <= 0.50:  # 30-50%
                high_return.append(t)
    
    print(f"High return trades (30-50%): {len(high_return)}")
    
    if not high_return:
        print("No high return trades found. Exiting.")
        return 0
    
    # Show details
    print("\nHigh return trades to be removed:")
    print("=" * 100)
    for t in sorted(high_return, key=lambda x: abs(x.get("return_pct", 0)), reverse=True)[:20]:
        symbol = t.get("symbol")
        entry_p = t.get("entry_price", 0)
        exit_p = t.get("exit_price", 0)
        ret = t.get("return_pct", 0)
        pnl = t.get("pnl", 0)
        qty = t.get("qty", 0)
        exit_time = t.get("exit_time", "")[:19]
        trade_id = t.get("trade_id", "")
        print(f"{symbol:6} {trade_id:20} {exit_time} entry=${entry_p:>7.2f} exit=${exit_p:>7.2f} return={ret:>+7.2%} pnl=${pnl:>12,.2f} qty={qty:>4}")
    
    if len(high_return) > 20:
        print(f"... and {len(high_return) - 20} more")
    
    total_high_pnl = sum(t.get("pnl", 0) for t in high_return)
    print(f"\nTotal P&L from high-return trades: ${total_high_pnl:,.2f}")
    
    # Current cumulative P&L
    closed_trades = [t for t in trades if t.get("status") == "closed"]
    current_pnl = sum(t.get("pnl", 0) for t in closed_trades if t.get("pnl") is not None)
    expected_pnl = current_pnl - total_high_pnl
    
    print(f"\nCurrent cumulative P&L: ${current_pnl:,.2f}")
    print(f"Expected after cleanup: ${expected_pnl:,.2f}")
    
    # Confirm
    print("\n" + "="*100)
    response = input(f"Remove {len(high_return)} high-return trades? (yes/no): ")
    if response.lower() != "yes":
        print("Aborted.")
        return 0
    
    # Remove high return trades
    high_return_ids = {t["trade_id"] for t in high_return}
    cleaned_trades = [t for t in trades if t["trade_id"] not in high_return_ids]
    
    data["trades"] = cleaned_trades
    
    # Save
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    print(f"\n✅ Removed {len(high_return)} high-return trades")
    print(f"✅ Remaining trades: {len(cleaned_trades)}")
    print(f"✅ Saved to: {state_file}")
    print(f"\n📝 Backup saved to: {backup_file}")
    
    # Recalculate summary
    closed_trades_new = [t for t in cleaned_trades if t.get("status") == "closed"]
    new_cumulative_pnl = sum(t.get("pnl", 0) for t in closed_trades_new if t.get("pnl") is not None)
    
    print(f"\n📊 New summary:")
    print(f"  Total trades: {len(cleaned_trades)}")
    print(f"  Closed trades: {len(closed_trades_new)}")
    print(f"  Cumulative P&L: ${new_cumulative_pnl:,.2f}")
    
    return 0

if __name__ == "__main__":
    exit(main())
