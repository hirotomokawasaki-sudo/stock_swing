#!/usr/bin/env python3
"""Fetch benchmark (SPY) data for performance comparison."""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import json

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load .env
env_file = PROJECT_ROOT / '.env'
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ[key] = value

from stock_swing.sources.broker_client import BrokerClient

def fetch_spy_bars(days=30):
    """Fetch SPY (S&P500 ETF) daily bars."""
    broker = BrokerClient(
        api_key=os.environ['BROKER_API_KEY'],
        api_secret=os.environ['BROKER_API_SECRET'],
        paper_mode=True
    )
    
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # Fetch bars
    print(f"Fetching SPY bars from {start_date.date()} to {end_date.date()}...")
    bars = broker.fetch_bars(
        symbol='SPY',
        timeframe='1Day',
        start=start_date.strftime('%Y-%m-%d'),
        end=end_date.strftime('%Y-%m-%d')
    )
    
    if not bars or not hasattr(bars, 'payload') or not bars.payload:
        print("Error: No data returned")
        return []
    
    # Extract bars from payload
    bar_list = bars.payload.get('bars', [])
    if not bar_list:
        print("Error: No bars in payload")
        return []
    
    # Convert to simple format
    data = []
    for bar in bar_list:
        data.append({
            'date': bar['t'][:10],  # ISO date
            'close': float(bar['c']),
            'open': float(bar['o']),
            'high': float(bar['h']),
            'low': float(bar['l']),
            'volume': int(bar['v']),
        })
    
    return data

def save_benchmark_data(data):
    """Save benchmark data to file."""
    output_dir = PROJECT_ROOT / "data" / "benchmarks"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / "SPY_daily.json"
    output_file.write_text(json.dumps(data, indent=2))
    
    print(f"Saved {len(data)} bars to {output_file}")
    
    # Also save summary
    if data:
        first_close = data[0]['close']
        last_close = data[-1]['close']
        return_pct = ((last_close - first_close) / first_close) * 100
        
        summary = {
            'symbol': 'SPY',
            'period': f"{data[0]['date']} to {data[-1]['date']}",
            'days': len(data),
            'first_close': first_close,
            'last_close': last_close,
            'return_pct': return_pct,
        }
        
        summary_file = output_dir / "SPY_summary.json"
        summary_file.write_text(json.dumps(summary, indent=2))
        
        print(f"\nSummary:")
        print(f"  Period: {summary['period']}")
        print(f"  Return: {return_pct:+.2f}%")

def main():
    data = fetch_spy_bars(days=60)  # Fetch 60 days to ensure 30+ trading days
    if data:
        save_benchmark_data(data)
        print("\nDone!")
    else:
        print("Failed to fetch data")

if __name__ == '__main__':
    main()
