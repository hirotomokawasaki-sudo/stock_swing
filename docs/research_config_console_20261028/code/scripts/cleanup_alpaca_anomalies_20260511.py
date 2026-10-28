#!/usr/bin/env python3
"""Clean up anomalous trades caused by Alpaca Paper Trading API bugs.

This script identifies and removes trades with unrealistic returns (>50% or <-50%)
which are caused by Alpaca returning incorrect filled_avg_price values.

Issue: Alpaca Paper Trading API returns prices like $443 for AMD when market price is $236.
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
    backup_file = state_file.parent / f"pnl_state_before_alpaca_cleanup_{timestamp}.json"
    shutil.copy2(state_file, backup_file)
    print(f"✅ Created backup: {backup_file}")
    
    # Load state
    data = json.loads(state_file.read_text(encoding="utf-8"))
    trades = data.get("trades", [])
    
    print(f"\nTotal trades before cleanup: {len(trades)}")
    
    # Find anomalous trades
    anomalous = []
    for t in trades:
        if t.get("status") == "closed":
            ret = t.get("return_pct", 0)
            if abs(ret) > 0.5:  # >50% return is unrealistic in paper trading
                anomalous.append(t)
    
    print(f"Anomalous trades (|return| > 50%): {len(anomalous)}")
    
    if not anomalous:
        print("No anomalous trades found. Exiting.")
        return 0
    
    # Show details
    print("\nAnomalous trades to be removed:")
    print("=" * 100)
    for t in sorted(anomalous, key=lambda x: abs(x.get("return_pct", 0)), reverse=True):
        symbol = t.get("symbol")
        entry_p = t.get("entry_price", 0)
        exit_p = t.get("exit_price", 0)
        ret = t.get("return_pct", 0)
        pnl = t.get("pnl", 0)
        qty = t.get("qty", 0)
        exit_time = t.get("exit_time", "")[:19]
        trade_id = t.get("trade_id", "")
        print(f"{symbol:6} {trade_id:20} {exit_time} entry=${entry_p:>7.2f} exit=${exit_p:>7.2f} return={ret:>+7.2%} pnl=${pnl:>12,.2f} qty={qty:>4}")
    
    total_anom_pnl = sum(t.get("pnl", 0) for t in anomalous)
    print(f"\nTotal P&L from anomalous trades: ${total_anom_pnl:,.2f}")
    
    # Confirm
    print("\n" + "="*100)
    response = input(f"Remove {len(anomalous)} anomalous trades? (yes/no): ")
    if response.lower() != "yes":
        print("Aborted.")
        return 0
    
    # Remove anomalous trades
    anomalous_ids = {t["trade_id"] for t in anomalous}
    cleaned_trades = [t for t in trades if t["trade_id"] not in anomalous_ids]
    
    data["trades"] = cleaned_trades
    
    # Save
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    print(f"\n✅ Removed {len(anomalous)} anomalous trades")
    print(f"✅ Remaining trades: {len(cleaned_trades)}")
    print(f"✅ Saved to: {state_file}")
    print(f"\n📝 Backup saved to: {backup_file}")
    
    # Recalculate summary
    closed_trades = [t for t in cleaned_trades if t.get("status") == "closed"]
    new_cumulative_pnl = sum(t.get("pnl", 0) for t in closed_trades if t.get("pnl") is not None)
    
    print(f"\n📊 New summary:")
    print(f"  Total trades: {len(cleaned_trades)}")
    print(f"  Closed trades: {len(closed_trades)}")
    print(f"  Cumulative P&L: ${new_cumulative_pnl:,.2f}")
    
    return 0

if __name__ == "__main__":
    exit(main())
