#!/usr/bin/env python3
"""
Compare data quality between Alpaca and Massive bars.

Usage:
    python scripts/compare_bars_quality.py --symbol NVDA --days 20
"""

import argparse
from datetime import datetime, timedelta
from typing import List, Dict
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

from src.stock_swing.sources.massive_client import MassiveClient, MassiveBar
from src.stock_swing.sources.broker_client import BrokerClient
import logging

logger = logging.getLogger(__name__)


def compare_bars(
    symbol: str,
    days: int = 20,
    timeframe: str = "1Min"
) -> Dict:
    """
    Compare Alpaca vs Massive bars quality.
    
    Args:
        symbol: Stock ticker
        days: Number of days to compare
        timeframe: Alpaca timeframe (1Min, 5Min, 1Day)
    
    Returns:
        Comparison metrics dict
    """
    # Calculate date range
    from datetime import timezone
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    # Format for Alpaca API (ISO8601 with Z suffix)
    alpaca_start = start_date.isoformat().replace("+00:00", "Z")
    alpaca_end = end_date.isoformat().replace("+00:00", "Z")
    
    # Format for Massive API (date strings)
    from_str = start_date.strftime("%Y-%m-%d")
    to_str = end_date.strftime("%Y-%m-%d")
    
    logger.info(f"Comparing {symbol} bars from {from_str} to {to_str}")
    
    # Calculate limit based on timeframe and days
    # Approximation: market is open 6.5 hours/day = 390 minutes/day
    if timeframe == "1Day":
        estimated_limit = days
    elif "Min" in timeframe:
        minutes_per_bar = 1 if timeframe == "1Min" else int(timeframe.replace("Min", ""))
        bars_per_day = 390 // minutes_per_bar
        estimated_limit = bars_per_day * days
    else:
        estimated_limit = 1000  # Default fallback
    
    # Cap at Alpaca's maximum limit of 10,000
    limit = min(estimated_limit, 10000)
    
    # Fetch Alpaca bars using start/end + limit
    logger.info(f"Fetching Alpaca bars (start={alpaca_start}, end={alpaca_end}, limit={limit})...")
    alpaca = BrokerClient(
        api_key=os.environ.get('BROKER_API_KEY'),
        api_secret=os.environ.get('BROKER_API_SECRET')
    )
    alpaca_raw = alpaca.fetch_bars(
        symbol=symbol,
        timeframe=timeframe,
        start=alpaca_start,
        end=alpaca_end,
        limit=limit
    )
    alpaca_bars = alpaca_raw.payload.get("bars", [])
    alpaca_count = len(alpaca_bars)
    logger.info(f"Alpaca: {alpaca_count} bars")
    
    # Fetch Massive bars (use same date range)
    logger.info("Fetching Massive bars...")
    massive = MassiveClient()
    
    if timeframe == "1Day":
        massive_bars = massive.fetch_daily_bars(symbol, from_str, to_str)
    else:
        # Convert Alpaca timeframe to multiplier
        multiplier = 1 if timeframe == "1Min" else int(timeframe.replace("Min", ""))
        # Massive API uses date strings
        massive_bars = massive.fetch_minute_bars(
            symbol, from_str, to_str, multiplier=multiplier
        )
    
    massive_count = len(massive_bars)
    logger.info(f"Massive: {massive_count} bars")
    
    # Compare metrics
    metrics = {
        "symbol": symbol,
        "timeframe": timeframe,
        "period": f"{from_str} to {to_str}",
        "alpaca_count": alpaca_count,
        "massive_count": massive_count,
        "difference": massive_count - alpaca_count,
        "difference_pct": ((massive_count - alpaca_count) / alpaca_count * 100) if alpaca_count > 0 else 0
    }
    
    # Sample price comparison (first 10 bars if available)
    if alpaca_count > 0 and massive_count > 0:
        alpaca_sample = alpaca_bars[:10]
        massive_sample = massive_bars[:10]
        
        print("\n" + "="*80)
        print(f"SAMPLE COMPARISON - First 10 bars for {symbol}")
        print("="*80)
        print(f"{'Timestamp':<20} {'Source':<10} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10} {'Volume':<12}")
        print("-"*80)
        
        for i in range(min(10, len(alpaca_sample), len(massive_sample))):
            a_bar = alpaca_sample[i]
            m_bar = massive_sample[i]
            
            # Alpaca bar (dict format)
            a_time = a_bar.get("t", "")
            a_open = a_bar.get("o", 0)
            a_high = a_bar.get("h", 0)
            a_low = a_bar.get("l", 0)
            a_close = a_bar.get("c", 0)
            a_volume = a_bar.get("v", 0)
            print(f"{str(a_time):<20} {'Alpaca':<10} {a_open:<10.2f} {a_high:<10.2f} {a_low:<10.2f} {a_close:<10.2f} {a_volume:<12}")
            
            # Massive bar (object format)
            print(f"{str(m_bar.timestamp):<20} {'Massive':<10} {m_bar.open:<10.2f} {m_bar.high:<10.2f} {m_bar.low:<10.2f} {m_bar.close:<10.2f} {m_bar.volume:<12}")
            
            # Difference
            price_diff = abs(a_close - m_bar.close)
            vol_diff = abs(a_volume - m_bar.volume)
            print(f"{'Difference':<20} {'':<10} {'':<10} {'':<10} {'':<10} {price_diff:<10.4f} {vol_diff:<12}")
            print("-"*80)
    
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Compare Alpaca vs Massive bars quality")
    parser.add_argument("--symbol", required=True, help="Stock symbol (e.g., NVDA)")
    parser.add_argument("--days", type=int, default=20, help="Number of days to compare (default: 20)")
    parser.add_argument("--timeframe", default="1Min", help="Timeframe: 1Min, 5Min, 1Day (default: 1Min)")
    
    args = parser.parse_args()
    
    try:
        metrics = compare_bars(
            symbol=args.symbol,
            days=args.days,
            timeframe=args.timeframe
        )
        
        print("\n" + "="*80)
        print("COMPARISON SUMMARY")
        print("="*80)
        print(f"Symbol:           {metrics['symbol']}")
        print(f"Timeframe:        {metrics['timeframe']}")
        print(f"Period:           {metrics['period']}")
        print(f"Alpaca bars:      {metrics['alpaca_count']:,}")
        print(f"Massive bars:     {metrics['massive_count']:,}")
        print(f"Difference:       {metrics['difference']:+,} ({metrics['difference_pct']:+.1f}%)")
        print("="*80)
        
        if metrics['massive_count'] > metrics['alpaca_count']:
            print(f"\n✅ Massive has {metrics['difference']:,} MORE bars (+{metrics['difference_pct']:.1f}%)")
            print("   → Consider using Massive for better data coverage")
        elif metrics['alpaca_count'] > metrics['massive_count']:
            print(f"\n⚠️  Alpaca has {abs(metrics['difference']):,} MORE bars (+{abs(metrics['difference_pct']):.1f}%)")
            print("   → Investigate why Massive has fewer bars")
        else:
            print(f"\n✅ Both sources have the same number of bars")
            print("   → Check price accuracy in sample comparison above")
    
    except Exception as e:
        logger.error(f"Comparison failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
