#!/usr/bin/env python3
"""Simplified backtest test to debug simulation loop."""

from pathlib import Path
import sys
from datetime import datetime, timedelta

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.backtest.engine_v2 import BacktestEngineV2

def main():
    print("=" * 70)
    print("🔍 Simplified Backtest Debug Test")
    print("=" * 70)
    print()
    
    engine = BacktestEngineV2(project_root, start_equity=100000.0)
    
    # Load all decisions
    all_decisions = engine.data_loader.load_decisions()
    print(f"Total decisions: {len(all_decisions)}")
    
    # Filter high confidence with prices
    valid_decisions = []
    for d in all_decisions:
        if d.get('confidence', 0) < 0.70:
            continue
        if d.get('action', '').lower() != 'buy':
            continue
            
        evidence = d.get('evidence') or {}
        sizing = (evidence.get('sizing') or d.get('sizing') or {})
        price = sizing.get('current_price') or evidence.get('latest_close')
        
        if price and price > 0:
            valid_decisions.append(d)
    
    print(f"Valid high-confidence BUY decisions with prices: {len(valid_decisions)}")
    
    # Show first 10
    print("\nFirst 10 valid decisions:")
    for i, d in enumerate(valid_decisions[:10]):
        ts_str = d.get('timestamp') or d.get('generated_at', '')
        evidence = d.get('evidence') or {}
        sizing = (evidence.get('sizing') or d.get('sizing') or {})
        price = sizing.get('current_price') or evidence.get('latest_close')
        
        print(f"{i+1}. {d.get('symbol')} @ ${price:.2f} - "
              f"confidence={d.get('confidence'):.2f}, time={ts_str[:19]}")
    
    # Test simulation with just first few decisions
    print("\n" + "=" * 70)
    print("Testing simulation with limited date range...")
    print("-" * 70)
    
    # Get date range from first 5 decisions
    dates = []
    for d in valid_decisions[:5]:
        ts_str = d.get('timestamp') or d.get('generated_at', '')
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                dates.append(ts)
            except:
                pass
    
    if dates:
        start = min(dates)
        end = max(dates) + timedelta(days=7)  # Add 7 days for exits
        
        print(f"Date range: {start.date()} to {end.date()}")
        
        params = {
            'confidence_threshold': 0.70,
            'stop_loss_pct': 0.07,
            'take_profit_pct': 0.15,
            'max_hold_days': 5,
            'max_position_pct': 0.08,
            'max_risk_per_trade': 0.005,
        }
        
        print("Running backtest...")
        result = engine.run_backtest_full(
            parameters=params,
            start_date=start,
            end_date=end,
            use_real_prices=False
        )
        
        print("\nResults:")
        print(f"  Trades: {result.total_trades}")
        print(f"  Equity curve length: {len(result.equity_curve)}")
        
        if result.trades:
            print(f"\n  Sample trades:")
            for t in result.trades[:5]:
                print(f"    {t.symbol}: ${t.pnl:.2f} ({t.return_pct:.1f}%) - {t.exit_reason}")
        else:
            print("  No trades executed - debugging needed")
            
            # Debug: Check what happened during simulation
            print("\n  Debug info:")
            print(f"    Simulator positions: {len(engine.simulator.positions)}")
            print(f"    Simulator trades: {len(engine.simulator.trades)}")
            print(f"    Simulator equity: ${engine.simulator.current_equity:,.2f}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
