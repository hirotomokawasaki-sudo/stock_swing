#!/usr/bin/env python3
"""
Fix stale broker prices with fresh Massive API data.

Problem: Alpaca positions API returns stale prices for some symbols (CHPX, QTEC).
Solution: Fetch fresh prices from Massive API and create a price override map.

This script generates a JSON file that can be used by SimpleExitV2Strategy
to override stale broker prices.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from stock_swing.sources.hybrid_data_fetcher import HybridDataFetcher
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.cli.paper_demo import ETF_SYMBOLS


def load_env():
    """Load environment variables from .env file."""
    env_path = Path(__file__).parent.parent / ".env"
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


def main():
    load_env()
    
    broker = BrokerClient(
        api_key=os.environ["BROKER_API_KEY"],
        api_secret=os.environ["BROKER_API_SECRET"],
        paper_mode=True
    )
    
    fetcher = HybridDataFetcher(
        broker_client=broker,
        etf_symbols=ETF_SYMBOLS,
        massive_api_key=os.environ.get("MASSIVE_API_KEY")
    )
    
    # Get all positions
    positions_env = broker.fetch_positions()
    positions = positions_env.payload if hasattr(positions_env, "payload") else positions_env
    
    symbols = [pos.get("symbol") for pos in positions]
    
    print(f"Fetching fresh prices for {len(symbols)} symbols from Massive API...")
    
    fresh_prices = {}
    stale_count = 0
    
    for symbol in symbols:
        try:
            records, source = fetcher.fetch_bars(symbol=symbol, timeframe="1Day", limit=3)
            
            if records and len(records) > 0:
                latest = records[-1]
                latest_close = latest.payload.get("close")
                latest_date = str(latest.event_time)[:10]
                
                if latest_close:
                    broker_pos = next((p for p in positions if p.get("symbol") == symbol), None)
                    broker_price = float(broker_pos.get("current_price", 0)) if broker_pos else 0
                    
                    # Check for >5% deviation
                    if broker_price > 0:
                        deviation = abs((latest_close - broker_price) / broker_price) * 100
                        if deviation > 5.0:
                            fresh_prices[symbol] = {
                                "fresh_price": float(latest_close),
                                "broker_price": broker_price,
                                "deviation_pct": deviation,
                                "date": latest_date,
                                "source": source,
                                "updated_at": datetime.now().isoformat()
                            }
                            stale_count += 1
                            print(f"  ⚠️  {symbol}: Broker ${broker_price:.2f} → Fresh ${latest_close:.2f} ({deviation:+.2f}%)")
        except Exception as e:
            print(f"  ✗ {symbol}: {e}")
    
    # Save to JSON
    output_path = Path(__file__).parent.parent / "data" / "price_overrides.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    output = {
        "schema_version": "v1",
        "generated_at": datetime.now().isoformat(),
        "note": "Fresh prices from Massive API to override stale Alpaca positions API prices",
        "overrides": fresh_prices
    }
    
    output_path.write_text(json.dumps(output, indent=2))
    
    print(f"\n✓ Generated price overrides for {stale_count} symbols")
    print(f"  Saved to: {output_path}")
    
    if stale_count > 0:
        print(f"\n⚠️  Recommendation:")
        print(f"  - Update SimpleExitV2Strategy to load price_overrides.json")
        print(f"  - Apply fresh prices before calculating exit signals")
    else:
        print(f"\n✓ All broker prices are fresh (no overrides needed)")


if __name__ == "__main__":
    main()
