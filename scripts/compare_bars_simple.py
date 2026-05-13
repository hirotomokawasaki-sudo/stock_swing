#!/usr/bin/env python3
"""
Simple comparison between Alpaca and Massive bars.

Usage:
    python scripts/compare_bars_simple.py --symbol NVDA --days 5
"""

import argparse
from datetime import datetime, timedelta
import sys
import os
from pathlib import Path

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env file
env_path = Path.home() / "stock_swing" / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.strip() and not line.strip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

from src.stock_swing.sources.massive_client import MassiveClient
from src.stock_swing.sources.broker_client import BrokerClient


def compare_data_sources(symbol: str, days: int):
    """Compare Alpaca vs Massive data quality."""
    
    print("="*80)
    print(f"DATA QUALITY COMPARISON: {symbol}")
    print("="*80)
    
    # Date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    from_str = start_date.strftime("%Y-%m-%d")
    to_str = end_date.strftime("%Y-%m-%d")
    
    print(f"Period: {from_str} to {to_str} ({days} days)")
    print()
    
    # Fetch Alpaca daily bars
    print("⏳ Fetching Alpaca daily bars...")
    try:
        alpaca = BrokerClient(
            api_key=os.environ['BROKER_API_KEY'],
            api_secret=os.environ['BROKER_API_SECRET']
        )
        alpaca_envelope = alpaca.fetch_bars(
            symbol=symbol,
            timeframe="1Day",
            start=start_date.isoformat(),
            end=end_date.isoformat()
        )
        
        # RawEnvelope has .body which contains the actual data
        alpaca_data = alpaca_envelope.body
        
        # Count bars - body might be a list or dict with 'bars' key
        if isinstance(alpaca_data, list):
            alpaca_bars = alpaca_data
        elif isinstance(alpaca_data, dict) and 'bars' in alpaca_data:
            alpaca_bars = alpaca_data['bars']
        else:
            alpaca_bars = []
        
        alpaca_count = len(alpaca_bars)
        print(f"✅ Alpaca: {alpaca_count} daily bars")
    except Exception as e:
        print(f"❌ Alpaca failed: {e}")
        alpaca_count = 0
        alpaca_bars = []
    
    # Fetch Massive daily bars
    print("⏳ Fetching Massive daily bars...")
    try:
        massive = MassiveClient()
        massive_bars = massive.fetch_daily_bars(symbol, from_str, to_str)
        massive_count = len(massive_bars)
        print(f"✅ Massive: {massive_count} daily bars")
    except Exception as e:
        print(f"❌ Massive failed: {e}")
        massive_count = 0
        massive_bars = []
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Symbol:           {symbol}")
    print(f"Period:           {from_str} to {to_str}")
    print(f"Alpaca bars:      {alpaca_count:,}")
    print(f"Massive bars:     {massive_count:,}")
    
    if alpaca_count > 0 and massive_count > 0:
        diff = massive_count - alpaca_count
        diff_pct = (diff / alpaca_count * 100) if alpaca_count > 0 else 0
        print(f"Difference:       {diff:+,} ({diff_pct:+.1f}%)")
        
        if massive_count > alpaca_count:
            print()
            print(f"✅ Massive has {diff:,} MORE bars (+{diff_pct:.1f}%)")
            print("   → Better data coverage from Massive")
        elif alpaca_count > massive_count:
            print()
            print(f"⚠️  Alpaca has {abs(diff):,} MORE bars (+{abs(diff_pct):.1f}%)")
            print("   → Investigate why Massive has fewer bars")
        else:
            print()
            print("✅ Equal bar count - both sources have same coverage")
    
    # Show sample data
    if alpaca_bars and massive_bars:
        print()
        print("="*80)
        print("SAMPLE DATA (Latest 3 bars)")
        print("="*80)
        
        print("\nMassive:")
        for bar in massive_bars[-3:]:
            print(f"  {bar.timestamp.date()} | O:{bar.open:8.2f} H:{bar.high:8.2f} "
                  f"L:{bar.low:8.2f} C:{bar.close:8.2f} | Vol:{bar.volume:>12,.0f}")
        
        print("\nAlpaca:")
        for bar in alpaca_bars[-3:]:
            if hasattr(bar, 't'):  # BarSet format
                print(f"  {bar.t.date()} | O:{bar.o:8.2f} H:{bar.h:8.2f} "
                      f"L:{bar.l:8.2f} C:{bar.c:8.2f} | Vol:{bar.v:>12,.0f}")
            elif isinstance(bar, dict):  # Dict format
                ts = datetime.fromisoformat(bar['t'].replace('Z', '+00:00'))
                print(f"  {ts.date()} | O:{bar['o']:8.2f} H:{bar['h']:8.2f} "
                      f"L:{bar['l']:8.2f} C:{bar['c']:8.2f} | Vol:{bar['v']:>12,.0f}")
    
    print("="*80)


def main():
    parser = argparse.ArgumentParser(description="Compare Alpaca vs Massive data quality")
    parser.add_argument("--symbol", required=True, help="Stock symbol (e.g., NVDA)")
    parser.add_argument("--days", type=int, default=20, help="Number of days to compare (default: 20)")
    
    args = parser.parse_args()
    
    try:
        compare_data_sources(args.symbol, args.days)
        return 0
    except Exception as e:
        print(f"\n❌ Comparison failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
