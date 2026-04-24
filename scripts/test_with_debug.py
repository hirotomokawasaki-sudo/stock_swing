#!/usr/bin/env python3
"""Test with debug output."""

from pathlib import Path
import sys
from datetime import datetime, timedelta

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.backtest.engine_v2 import BacktestEngineV2

engine = BacktestEngineV2(project_root)

# Get a single day with decisions
all_decisions = engine.data_loader.load_decisions()
grouped = engine._group_decisions_by_date(all_decisions)

# Find first date with decisions
dates_with_data = sorted([d for d in grouped.keys() if grouped[d]])
if dates_with_data:
    test_date = dates_with_data[0]
    print(f"Testing date: {test_date.date()}")
    print(f"Decisions on this date: {len(grouped[test_date])}")
    print()
    
    params = {
        'confidence_threshold': 0.70,
        'stop_loss_pct': 0.07,
        'take_profit_pct': 0.15,
        'max_hold_days': 5,
        'max_position_pct': 0.08,
        'max_risk_per_trade': 0.005,
    }
    
    # Process with debug
    for i, decision in enumerate(grouped[test_date][:5]):  # First 5
        print(f"Decision {i+1}:")
        engine._process_entry(decision, test_date, params, False, debug=True)
        print()
    
    print(f"Total positions entered: {len(engine.simulator.positions)}")
    print(f"Current equity: ${engine.simulator.current_equity:,.2f}")

