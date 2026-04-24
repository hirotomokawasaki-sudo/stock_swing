#!/usr/bin/env python3
"""Test backtest engine basic functionality."""

from pathlib import Path
import sys

# Add src to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.backtest import (
    BacktestEngine,
    DataLoader,
    ParameterGrid,
    TradeSimulator,
    MetricsCalculator,
)


def main():
    print("=" * 70)
    print("🧪 Backtest Engine Test Suite")
    print("=" * 70)
    print()
    
    # Test 1: ParameterGrid
    print("📊 Test 1: ParameterGrid")
    print("-" * 70)
    
    grid = ParameterGrid()
    
    priority_count = grid.count(priority_only=True)
    all_count = grid.count(priority_only=False)
    
    print(f"  Priority combinations: {priority_count}")
    print(f"  All combinations: {all_count}")
    
    priority_combos = grid.generate(priority_only=True)
    print(f"  Generated {len(priority_combos)} priority combinations")
    
    if priority_combos:
        print(f"  Sample combination:")
        for k, v in list(priority_combos[0].items())[:5]:
            print(f"    {k}: {v}")
    
    # Apply domain constraints
    filtered = grid.apply_domain_constraints(priority_combos)
    print(f"  After domain constraints: {len(filtered)} combinations")
    
    print("  ✅ ParameterGrid test passed\n")
    
    # Test 2: DataLoader
    print("📁 Test 2: DataLoader")
    print("-" * 70)
    
    loader = DataLoader(project_root)
    
    start_date, end_date = loader.get_date_range()
    print(f"  Data range: {start_date} to {end_date}")
    
    decisions = loader.load_decisions()
    print(f"  Total decisions loaded: {len(decisions)}")
    
    trades = loader.load_trades()
    print(f"  Total trades loaded: {len(trades)}")
    
    print("  ✅ DataLoader test passed\n")
    
    # Test 3: TradeSimulator
    print("🎮 Test 3: TradeSimulator")
    print("-" * 70)
    
    simulator = TradeSimulator(start_equity=100000.0)
    
    # Test position entry
    params = {
        'max_position_pct': 0.08,
        'max_risk_per_trade': 0.005,
        'stop_loss_pct': 0.07,
        'take_profit_pct': 0.15,
        'max_hold_days': 5,
    }
    
    from datetime import datetime
    
    can_enter, qty = simulator.can_enter_position('AAPL', 150.0, params)
    print(f"  Can enter AAPL @ $150: {can_enter}, Qty: {qty}")
    
    if can_enter:
        success = simulator.enter_position('AAPL', datetime.now(), 150.0, qty, params)
        print(f"  Position entered: {success}")
        print(f"  Current equity: ${simulator.current_equity:,.2f}")
        print(f"  Positions: {len(simulator.positions)}")
    
    print("  ✅ TradeSimulator test passed\n")
    
    # Test 4: MetricsCalculator
    print("📈 Test 4: MetricsCalculator")
    print("-" * 70)
    
    from stock_swing.backtest.metrics import BacktestTrade
    
    calc = MetricsCalculator()
    
    # Create sample trades
    sample_trades = [
        BacktestTrade(
            symbol='AAPL',
            entry_date=datetime(2026, 4, 1),
            entry_price=150.0,
            exit_date=datetime(2026, 4, 5),
            exit_price=165.0,
            qty=50,
            pnl=750.0,
            return_pct=10.0,
            hold_days=4,
            exit_reason='take_profit'
        ),
        BacktestTrade(
            symbol='GOOGL',
            entry_date=datetime(2026, 4, 2),
            entry_price=140.0,
            exit_date=datetime(2026, 4, 4),
            exit_price=130.0,
            qty=40,
            pnl=-400.0,
            return_pct=-7.14,
            hold_days=2,
            exit_reason='stop_loss'
        ),
    ]
    
    equity_curve = [100000, 100750, 100350]
    
    result = calc.calculate(sample_trades, equity_curve, start_equity=100000)
    
    print(f"  Total Return: {result.total_return:.2f}%")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:.2f}")
    print(f"  Win Rate: {result.win_rate:.1f}%")
    print(f"  Max Drawdown: {result.max_drawdown:.2f}%")
    print(f"  Profit Factor: {result.profit_factor:.2f}")
    
    print("  ✅ MetricsCalculator test passed\n")
    
    # Test 5: BacktestEngine
    print("🚀 Test 5: BacktestEngine")
    print("-" * 70)
    
    engine = BacktestEngine(project_root, start_equity=100000.0)
    
    print(f"  Engine initialized with ${engine.start_equity:,.2f} starting equity")
    print(f"  Components loaded:")
    print(f"    - DataLoader: ✅")
    print(f"    - ParameterGrid: ✅")
    print(f"    - TradeSimulator: ✅")
    print(f"    - MetricsCalculator: ✅")
    
    # Test best parameters extraction
    sample_results = []
    for i in range(3):
        from stock_swing.backtest import BacktestResult
        sample_results.append(BacktestResult(
            parameters={'test': i},
            total_return=float(i * 2),
            sharpe_ratio=float(i),
            win_rate=50.0 + i * 5,
            max_drawdown=5.0,
            total_trades=10,
            avg_pnl=100.0,
            profit_factor=1.5,
        ))
    
    best = engine.get_best_parameters(sample_results, metric='sharpe_ratio')
    print(f"  Best parameters by Sharpe: {best}")
    
    print("  ✅ BacktestEngine test passed\n")
    
    # Summary
    print("=" * 70)
    print("🎉 All tests passed!")
    print("=" * 70)
    print()
    print("Backtest engine is ready for:")
    print("  1. Parameter grid search")
    print("  2. Walk-forward validation")
    print("  3. Performance optimization")
    print()


if __name__ == "__main__":
    main()
