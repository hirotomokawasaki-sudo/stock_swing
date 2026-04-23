"""Add _enrich_broker_position method to dashboard_service.py"""

def _enrich_broker_position(self, broker_pos: dict) -> dict:
    """Enrich a broker position with calculated fields."""
    from datetime import datetime
    
    symbol = broker_pos.get('symbol', '')
    qty = int(float(broker_pos.get('qty', 0)))
    avg_entry = float(broker_pos.get('avg_entry_price', 0))
    current_price = float(broker_pos.get('current_price', 0))
    market_value = float(broker_pos.get('market_value', 0))
    unrealized_pl = float(broker_pos.get('unrealized_pl', 0))
    unrealized_plpc = float(broker_pos.get('unrealized_plpc', 0))
    
    # Calculate holding days (if created_at available)
    holding_days = None
    created_at = broker_pos.get('created_at')
    if created_at:
        try:
            from datetime import timezone
            created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            now_dt = datetime.now(timezone.utc)
            holding_days = (now_dt - created_dt).days
        except:
            pass
    
    return {
        'symbol': symbol,
        'qty': qty,
        'entry_price': avg_entry,
        'current_price': current_price,
        'market_value': market_value,
        'unrealized_pnl': unrealized_pl,
        'unrealized_pnl_pct': unrealized_plpc * 100,
        'holding_days': holding_days,
        'strategy_id': 'unknown',  # Not available from broker
        'source': 'broker',
    }

# Insert this method into DashboardService class around line 970
