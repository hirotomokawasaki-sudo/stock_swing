"""Test SimpleExitStrategy to debug why it's not generating signals"""
import os
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.strategy_engine.simple_exit_strategy import SimpleExitStrategy

broker = BrokerClient(
    api_key=os.getenv("BROKER_API_KEY"),
    api_secret=os.getenv("BROKER_API_SECRET"),
    paper_mode=True,
)

print("🔍 SimpleExit Debug Test\n")
print("=" * 60)

# Get current positions
positions_env = broker.fetch_positions()
positions = positions_env.payload if hasattr(positions_env, 'payload') else positions_env

print(f"Fetched {len(positions)} positions from broker\n")

# Build current_positions_full dict
current_positions_full = {}
for pos in positions:
    sym = pos.get('symbol')
    qty = int(float(pos.get('qty', 0)))
    if sym and qty > 0:
        current_positions_full[sym] = pos

print(f"Filtered to {len(current_positions_full)} long positions\n")

# Show position details
print("POSITION DETAILS:")
print("-" * 60)
for sym, pos in current_positions_full.items():
    entry = float(pos.get('avg_entry_price', 0))
    current = float(pos.get('current_price', 0))
    qty = int(float(pos.get('qty', 0)))
    plpc = float(pos.get('unrealized_plpc', 0)) * 100
    
    return_pct = (current - entry) / entry if entry > 0 else 0
    
    print(f"{sym}:")
    print(f"  Qty: {qty}")
    print(f"  Entry: ${entry:.2f}")
    print(f"  Current: ${current:.2f}")
    print(f"  Return %: {return_pct*100:.2f}%")
    print(f"  Broker P&L %: {plpc:.2f}%")
    print(f"  created_at: {pos.get('created_at', 'N/A')}")
    print()

# Test SimpleExitStrategy
print("=" * 60)
print("TESTING SimpleExitStrategy\n")

exit_strat = SimpleExitStrategy(
    stop_loss_pct=-0.07,
    take_profit_pct=0.10,
    max_hold_days=5,
)

print(f"Parameters:")
print(f"  stop_loss_pct: {exit_strat.stop_loss_pct}")
print(f"  take_profit_pct: {exit_strat.take_profit_pct}")
print(f"  max_hold_days: {exit_strat.max_hold_days}\n")

# Call generate with empty features (we'll add price data manually)
from stock_swing.feature_engine.base_feature import FeatureResult

features = []
for sym, pos in current_positions_full.items():
    current_price = float(pos.get('current_price', 0))
    
    # Create a mock feature with latest_close
    feature = FeatureResult(
        feature_name="price_momentum",
        symbol=sym,
        values={
            "latest_close": current_price,
            "momentum": 0.0,
            "trend": "neutral",
        }
    )
    features.append(feature)

print(f"Created {len(features)} mock features\n")

# Generate signals
signals = exit_strat.generate(features, current_positions_full)

print(f"Generated {len(signals)} exit signals\n")

if signals:
    print("EXIT SIGNALS:")
    print("-" * 60)
    for sig in signals:
        print(f"{sig.symbol}: {sig.action.upper()}")
        print(f"  Reasoning: {sig.reasoning}")
        print(f"  Strength: {sig.signal_strength}")
        print(f"  Return %: {sig.metadata.get('return_pct', 0)*100:.2f}%")
        print()
else:
    print("❌ NO EXIT SIGNALS GENERATED!\n")
    print("Debugging why...")
    print()
    
    # Manual check
    for sym, pos in current_positions_full.items():
        entry = float(pos.get('avg_entry_price', 0))
        current = float(pos.get('current_price', 0))
        
        if entry <= 0 or current <= 0:
            print(f"⚠️  {sym}: Invalid prices (entry=${entry}, current=${current})")
            continue
        
        return_pct = (current - entry) / entry
        
        print(f"{sym}:")
        print(f"  Return: {return_pct*100:.2f}%")
        
        if return_pct <= exit_strat.stop_loss_pct:
            print(f"  ✅ SHOULD TRIGGER STOP LOSS ({return_pct:.2%} <= {exit_strat.stop_loss_pct:.2%})")
        elif return_pct >= exit_strat.take_profit_pct:
            print(f"  ✅ SHOULD TRIGGER TAKE PROFIT ({return_pct:.2%} >= {exit_strat.take_profit_pct:.2%})")
        else:
            print(f"  ⏸️  No exit criteria met")
        print()

print("=" * 60)
