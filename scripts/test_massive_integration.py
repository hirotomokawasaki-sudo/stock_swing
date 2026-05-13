#!/usr/bin/env python3
"""
Quick validation test for Massive API integration.

Tests:
1. API connection
2. Ticker details
3. Daily bars fetch
4. Minute bars fetch
5. Technical indicators (SMA)
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
env_path = Path.home() / "stock_swing" / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.strip() and not line.strip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

from src.stock_swing.sources.massive_client import MassiveClient


def test_massive_integration():
    """Run integration tests for Massive API."""
    
    print("="*80)
    print("MASSIVE API INTEGRATION TEST")
    print("="*80)
    
    try:
        client = MassiveClient()
        print("✅ Client initialized\n")
    except Exception as e:
        print(f"❌ Client initialization failed: {e}")
        return False
    
    # Test 1: Ticker details
    print("TEST 1: Ticker Details")
    print("-"*80)
    try:
        for symbol in ["NVDA", "AMD", "AAPL"]:
            details = client.get_ticker_details(symbol)
            print(f"{symbol:6} {details['name']:30} {details['market']:10} {details['currency']}")
        print("✅ Ticker details working\n")
    except Exception as e:
        print(f"❌ Ticker details failed: {e}\n")
        return False
    
    # Test 2: Daily bars
    print("TEST 2: Daily Bars (last 5 days)")
    print("-"*80)
    try:
        end = datetime.now()
        start = end - timedelta(days=7)
        bars = client.fetch_daily_bars(
            "NVDA",
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d")
        )
        print(f"Fetched {len(bars)} bars")
        if bars:
            latest = bars[-1]
            print(f"Latest: {latest.timestamp.date()} | "
                  f"O:{latest.open:.2f} H:{latest.high:.2f} L:{latest.low:.2f} C:{latest.close:.2f} | "
                  f"Vol:{latest.volume:,.0f}")
        print("✅ Daily bars working\n")
    except Exception as e:
        print(f"❌ Daily bars failed: {e}\n")
        return False
    
    # Test 3: Minute bars (limited to avoid rate limit)
    print("TEST 3: Minute Bars (last 1 day, sample)")
    print("-"*80)
    try:
        end = datetime.now()
        start = end - timedelta(days=1)
        bars = client.fetch_minute_bars(
            "NVDA",
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            multiplier=5,  # 5-minute bars to reduce data volume
            limit=100
        )
        print(f"Fetched {len(bars)} 5-minute bars (limited to 100)")
        if bars:
            print(f"First: {bars[0].timestamp} | C:{bars[0].close:.2f}")
            print(f"Last:  {bars[-1].timestamp} | C:{bars[-1].close:.2f}")
        print("✅ Minute bars working\n")
    except Exception as e:
        print(f"❌ Minute bars failed: {e}\n")
        return False
    
    # Test 4: Technical indicators
    print("TEST 4: Technical Indicators (SMA)")
    print("-"*80)
    try:
        end = datetime.now()
        start = end - timedelta(days=30)
        sma = client.fetch_sma(
            "NVDA",
            window=20,
            from_date=start.strftime("%Y-%m-%d"),
            to_date=end.strftime("%Y-%m-%d")
        )
        print(f"Fetched {len(sma)} SMA(20) values")
        if sma:
            latest = sma[-1]
            print(f"Latest SMA(20): {latest['timestamp'].date()} = ${latest['value']:.2f}")
        print("✅ Technical indicators working\n")
    except Exception as e:
        print(f"❌ Technical indicators failed: {e}\n")
        return False
    
    print("="*80)
    print("ALL TESTS PASSED ✅")
    print("="*80)
    print("\nMassive API integration is working correctly.")
    print("\nNext steps:")
    print("1. Run data quality comparison: python scripts/compare_bars_quality.py --symbol NVDA --days 20")
    print("2. If Massive data is better, integrate into collect_data.py")
    print("3. Update feature_engine to use minute-level bars")
    
    return True


if __name__ == "__main__":
    success = test_massive_integration()
    sys.exit(0 if success else 1)
