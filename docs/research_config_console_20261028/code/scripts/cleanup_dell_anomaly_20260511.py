#!/usr/bin/env python3
"""Clean up DELL trades with exit price $215.02 (out of market range).

Market range on 2026-05-06: $219.60 - $239.45
Exit price $215.02 is below the daily low, indicating data error.
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
    backup_file = state_file.parent / f"pnl_state_before_dell_cleanup_{timestamp}.json"
    shutil.copy2(state_file, backup_file)
    print(f"✅ Created backup: {backup_file}")
    
    # Load state
    data = json.loads(state_file.read_text(encoding="utf-8"))
    trades = data.get("trades", [])
    
    print(f"\nTotal trades before cleanup: {len(trades)}")
    
    # Find DELL trades with exit price $215.02
    dell_anomalies = []
    for t in trades:
        if t.get("status") == "closed" and t.get("symbol") == "DELL":
            exit_p = t.get("exit_price", 0)
            if abs(exit_p - 215.02) < 0.01:  # floating point comparison
                dell_anomalies.append(t)
    
    print(f"DELL trades with exit price $215.02: {len(dell_anomalies)}件")
    
    if not dell_anomalies:
        print("No anomalous DELL trades found. Exiting.")
        return 0
    
    # Show details
    print("\nDELL anomalous trades to be removed:")
    print("=" * 100)
    for t in dell_anomalies:
        entry_p = t.get("entry_price", 0)
        exit_p = t.get("exit_price", 0)
        ret = t.get("return_pct", 0)
        pnl = t.get("pnl", 0)
        qty = t.get("qty", 0)
        exit_time = t.get("exit_time", "")[:19]
        trade_id = t.get("trade_id", "")
        print(f"DELL   {trade_id:20} {exit_time} entry=${entry_p:>7.2f} exit=${exit_p:>7.2f} return={ret:>+7.2%} pnl=${pnl:>12,.2f} qty={qty:>4}")
    
    total_pnl = sum(t.get("pnl", 0) for t in dell_anomalies)
    print(f"\nTotal P&L from anomalous trades: ${total_pnl:,.2f}")
    print(f"\nNote: Exit price $215.02 is below market low $219.60 on 2026-05-06")
    
    # Current cumulative P&L
    closed_trades = [t for t in trades if t.get("status") == "closed"]
    current_pnl = sum(t.get("pnl", 0) for t in closed_trades if t.get("pnl") is not None)
    expected_pnl = current_pnl - total_pnl
    
    print(f"\nCurrent cumulative P&L: ${current_pnl:,.2f}")
    print(f"Expected after cleanup: ${expected_pnl:,.2f}")
    
    # Confirm
    print("\n" + "="*100)
    response = input(f"Remove {len(dell_anomalies)} DELL anomalous trades? (yes/no): ")
    if response.lower() != "yes":
        print("Aborted.")
        return 0
    
    # Remove anomalous trades
    anomaly_ids = {t["trade_id"] for t in dell_anomalies}
    cleaned_trades = [t for t in trades if t["trade_id"] not in anomaly_ids]
    
    data["trades"] = cleaned_trades
    
    # Save
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    print(f"\n✅ Removed {len(dell_anomalies)} DELL anomalous trades")
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
