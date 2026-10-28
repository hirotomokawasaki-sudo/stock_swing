#!/usr/bin/env python3
"""Debug entry processing."""

from pathlib import Path
import sys
from datetime import datetime

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.backtest.trade_simulator import TradeSimulator

def main():
    print("=" * 70)
    print("🔍 Debug Entry Processing")
    print("=" * 70)
    
    # Test TradeSimulator directly
    simulator = TradeSimulator(start_equity=100000.0)
    
    params = {
        'max_position_pct': 0.08,
        'max_risk_per_trade': 0.005,
        'stop_loss_pct': 0.07,
        'take_profit_pct': 0.15,
        'max_hold_days': 5,
    }
    
    # Test with sample price
    test_symbol = "AAPL"
    test_price = 150.0
    test_date = datetime(2026, 4, 10)
    
    print(f"\nTest 1: Can enter position?")
    print(f"  Symbol: {test_symbol}")
    print(f"  Price: ${test_price}")
    print(f"  Equity: ${simulator.current_equity:,.2f}")
    
    can_enter, qty = simulator.can_enter_position(test_symbol, test_price, params)
    
    print(f"\nResult:")
    print(f"  Can enter: {can_enter}")
    print(f"  Quantity: {qty}")
    
    if can_enter and qty > 0:
        print(f"\nTest 2: Enter position")
        success = simulator.enter_position(
            test_symbol,
            test_date,
            test_price,
            qty,
            params
        )
        
        print(f"  Success: {success}")
        print(f"  Positions: {len(simulator.positions)}")
        print(f"  Current equity: ${simulator.current_equity:,.2f}")
        
        if test_symbol in simulator.positions:
            pos = simulator.positions[test_symbol]
            print(f"\n  Position details:")
            print(f"    Symbol: {pos.symbol}")
            print(f"    Qty: {pos.qty}")
            print(f"    Entry: ${pos.entry_price:.2f}")
            print(f"    Stop: ${pos.stop_loss_price:.2f}")
            print(f"    Target: ${pos.take_profit_price:.2f}")
            print(f"    Max exit: {pos.max_exit_date.date()}")
        
        # Test exit
        print(f"\nTest 3: Check exit (price goes up)")
        exit_date = datetime(2026, 4, 12)
        exit_price = test_price * 1.20  # +20%
        
        prices = {test_symbol: exit_price}
        closed = simulator.check_exits(exit_date, prices)
        
        print(f"  Exit price: ${exit_price:.2f}")
        print(f"  Closed trades: {len(closed)}")
        
        if closed:
            trade = closed[0]
            print(f"\n  Trade result:")
            print(f"    Symbol: {trade.symbol}")
            print(f"    P&L: ${trade.pnl:.2f}")
            print(f"    Return: {trade.return_pct:.1f}%")
            print(f"    Reason: {trade.exit_reason}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
