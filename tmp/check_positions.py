#!/usr/bin/env python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# Load environment
import os

def _load_env(env_path):
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

project_root = Path(__file__).parent.parent
_load_env(project_root / '.env')

from stock_swing.sources.broker_client import BrokerClient
import os
from datetime import datetime

api_key = os.environ.get('BROKER_API_KEY')
api_secret = os.environ.get('BROKER_API_SECRET')

if not api_key:
    print('Error: No API key found')
    exit(1)

broker = BrokerClient(api_key=api_key, api_secret=api_secret)

# 現在のポジションを取得
print('📊 Alpaca Broker - 現在のポジション:\n')
positions_resp = broker.fetch_positions()
if isinstance(positions_resp.payload, list):
    positions = positions_resp.payload
else:
    positions = positions_resp.payload.get('positions', [])

print(f'合計ポジション数: {len(positions)}\n')
print(f'{"":3s} {"Symbol":6s} {"Qty":>6s} {"Entry":>9s} {"Current":>9s} {"P/L %":>8s} {"Days":>5s}')
print('=' * 65)

total_value = 0
for i, pos in enumerate(sorted(positions, key=lambda x: float(x.get('market_value', 0)), reverse=True), 1):
    symbol = pos.get('symbol')
    qty = pos.get('qty')
    avg_entry = float(pos.get('avg_entry_price', 0))
    current = float(pos.get('current_price', 0))
    unrealized_plpc = float(pos.get('unrealized_plpc', 0))
    market_value = float(pos.get('market_value', 0))
    total_value += market_value
    
    # 保有日数
    days = '?'
    
    pnl_emoji = '✅' if unrealized_plpc > 0 else '❌' if unrealized_plpc < 0 else '⚖️ '
    
    print(f'{pnl_emoji} {i:2d}. {symbol:6s} {qty:>6s} ${avg_entry:>8.2f} ${current:>8.2f} {unrealized_plpc*100:>7.2f}% {days:>5s}')

print('=' * 65)
print(f'合計価値: ${total_value:,.2f}\n')

# 最近の注文を取得
print('\n📋 最近の注文（最新10件）:\n')
try:
    import json
    import urllib.request
    
    url = 'https://paper-api.alpaca.markets/v2/orders?status=all&limit=10&direction=desc'
    req = urllib.request.Request(url)
    req.add_header('APCA-API-KEY-ID', api_key)
    req.add_header('APCA-API-SECRET-KEY', api_secret)
    
    with urllib.request.urlopen(req, timeout=10) as response:
        orders = json.loads(response.read())
    
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    for i, order in enumerate(orders, 1):
        symbol = order.get('symbol')
        side = order.get('side', '').upper()
        qty = order.get('qty')
        status = order.get('status')
        filled_qty = order.get('filled_qty', '0')
        created_at = order.get('created_at', '')[:19]
        order_date = created_at[:10]
        
        if status == 'filled':
            status_emoji = '✅'
        elif status in ['new', 'accepted', 'pending_new']:
            status_emoji = '⏳'
        else:
            status_emoji = '❌'
        
        date_marker = '📅' if order_date == today else '  '
        
        print(f'{i:2d}. {status_emoji} {date_marker} {created_at} | {side:4s} {qty:>4s} {symbol:6s} | {status:15s}')
        
        if status in ['rejected', 'canceled'] and order_date == today:
            if 'cancel_reason' in order:
                print(f'       ⚠️  {order["cancel_reason"]}')
            elif 'reason' in order:
                print(f'       ⚠️  {order["reason"]}')

except Exception as e:
    print(f'注文履歴取得エラー: {e}')

print('\n✅ = 利益/成功, ❌ = 損失/失敗, ⚖️  = ±0, ⏳ = 処理中')
