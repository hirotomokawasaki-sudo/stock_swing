#!/usr/bin/env python3
"""Run first backtest with sample parameters."""

from pathlib import Path
import sys
from datetime import datetime

# Add src to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.backtest.engine_v2 import BacktestEngineV2
from stock_swing.backtest import ParameterGrid


def main():
    print("=" * 70)
    print("🚀 First Backtest Run - Week 3 Day 1")
    print("=" * 70)
    print()
    
    # Initialize engine
    print("Initializing backtest engine...")
    engine = BacktestEngineV2(project_root, start_equity=100000.0)
    
    # Get date range
    start_date, end_date = engine.data_loader.get_date_range()
    print(f"Data range: {start_date} to {end_date}")
    print()
    
    # Load decisions count
    decisions = engine.data_loader.load_decisions()
    trades = engine.data_loader.load_trades()
    print(f"Available data:")
    print(f"  Decisions: {len(decisions)}")
    print(f"  Trades: {len(trades)}")
    print()
    
    # Test with baseline parameters
    print("Running baseline backtest...")
    print("-" * 70)
    
    baseline_params = {
        'confidence_threshold': 0.70,
        'min_momentum': 0.03,
        'stop_loss_pct': 0.07,
        'take_profit_pct': 0.15,
        'max_hold_days': 5,
        'max_position_pct': 0.08,
        'max_risk_per_trade': 0.005,
    }
    
    print("Parameters:")
    for k, v in baseline_params.items():
        print(f"  {k}: {v}")
    print()
    
    # Run backtest (without real prices for now)
    result = engine.run_backtest_full(
        parameters=baseline_params,
        use_real_prices=False
    )
    
    print("Results:")
    print("-" * 70)
    print(f"Total Trades:    {result.total_trades}")
    print(f"Total Return:    {result.total_return:.2f}%")
    print(f"Sharpe Ratio:    {result.sharpe_ratio:.2f}")
    print(f"Win Rate:        {result.win_rate:.1f}%")
    print(f"Max Drawdown:    {result.max_drawdown:.2f}%")
    print(f"Profit Factor:   {result.profit_factor:.2f}")
    print(f"Avg P&L:         ${result.avg_pnl:.2f}")
    print(f"Final Equity:    ${result.final_equity:,.2f}")
    print()
    
    # Show trade samples
    if result.trades:
        print(f"Sample trades (first 5):")
        print("-" * 70)
        for i, trade in enumerate(result.trades[:5]):
            print(f"{i+1}. {trade.symbol}: ${trade.pnl:.2f} ({trade.return_pct:.2f}%) - {trade.exit_reason}")
        print()
    
    # Test priority parameter grid
    print("Testing priority parameter grid...")
    print("-" * 70)
    
    grid = ParameterGrid()
    priority_combos = grid.generate(priority_only=True)
    filtered = grid.apply_domain_constraints(priority_combos)
    
    print(f"Priority combinations: {len(priority_combos)}")
    print(f"After constraints: {len(filtered)}")
    print()
    
    if len(filtered) > 0:
        print("Running first 3 parameter combinations...")
        
        for i, params in enumerate(filtered[:3]):
            print(f"\nCombo {i+1}:")
            result = engine.run_backtest_full(params, use_real_prices=False)
            print(f"  Trades: {result.total_trades}, Return: {result.total_return:.2f}%, Sharpe: {result.sharpe_ratio:.2f}")
    
    print()
    print("=" * 70)
    print("✅ First backtest complete!")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Integrate real price data")
    print("  2. Run full grid search (32 combinations)")
    print("  3. Analyze best parameters")
    print()


if __name__ == "__main__":
    main()
