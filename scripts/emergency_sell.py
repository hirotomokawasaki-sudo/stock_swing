"""Emergency manual sell for NOW and IBM"""
import os
from stock_swing.sources.broker_client import BrokerClient

broker = BrokerClient(
    api_key=os.getenv("BROKER_API_KEY"),
    api_secret=os.getenv("BROKER_API_SECRET"),
    paper_mode=True,
)

symbols_to_sell = ['NOW', 'IBM']

print("🚨 EMERGENCY SELL")
print("=" * 50)

# Get current positions
positions = broker.fetch_positions()
pos_data = positions.payload if hasattr(positions, 'payload') else positions

for sym in symbols_to_sell:
    # Find position
    position = None
    for p in pos_data:
        if p.get('symbol') == sym:
            position = p
            break
    
    if not position:
        print(f"❌ {sym}: No position found")
        continue
    
    qty = int(float(position.get('qty', 0)))
    if qty <= 0:
        print(f"❌ {sym}: Zero quantity")
        continue
    
    plpc = float(position.get('unrealized_plpc', 0)) * 100
    pl = float(position.get('unrealized_pl', 0))
    
    print(f"\n📉 {sym}:")
    print(f"   Qty: {qty}")
    print(f"   P&L: ${pl:,.2f} ({plpc:+.2f}%)")
    print(f"   Submitting SELL order...")
    
    try:
        order = broker.submit_order(
            symbol=sym,
            side='sell',
            order_type='market',
            qty=qty,
            time_in_force='day',
        )
        
        order_id = order.get('id')
        print(f"   ✅ Order submitted: {order_id}")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")

print("\n" + "=" * 50)
print("✅ Emergency sell complete")
