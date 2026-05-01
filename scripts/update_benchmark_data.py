#!/usr/bin/env python3
"""Update benchmark data (SPY, QQQ, etc.)."""

import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def update_spy_data():
    """Update SPY benchmark data using yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        print("❌ yfinance not installed. Install with: pip install yfinance")
        return False
    
    benchmark_dir = PROJECT_ROOT / "data" / "benchmarks"
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    
    spy_file = benchmark_dir / "SPY_daily.json"
    
    # Get last 60 days of data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=60)
    
    print(f"📥 Downloading SPY data from {start_date.date()} to {end_date.date()}...")
    
    spy = yf.Ticker("SPY")
    hist = spy.history(start=start_date, end=end_date)
    
    if hist.empty:
        print("❌ No data downloaded")
        return False
    
    # Convert to JSON format
    data = []
    for date, row in hist.iterrows():
        data.append({
            "date": date.strftime("%Y-%m-%d"),
            "close": round(float(row['Close']), 2),
            "open": round(float(row['Open']), 2),
            "high": round(float(row['High']), 2),
            "low": round(float(row['Low']), 2),
            "volume": int(row['Volume'])
        })
    
    # Sort by date
    data.sort(key=lambda x: x['date'])
    
    # Save to file
    spy_file.write_text(json.dumps(data, indent=2))
    
    print(f"✅ Downloaded {len(data)} days of SPY data")
    print(f"   First: {data[0]['date']}")
    print(f"   Last: {data[-1]['date']}")
    print(f"   Saved to: {spy_file}")
    
    return True

if __name__ == "__main__":
    success = update_spy_data()
    sys.exit(0 if success else 1)
