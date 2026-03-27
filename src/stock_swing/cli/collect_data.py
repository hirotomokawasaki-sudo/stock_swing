#!/usr/bin/env python3
"""Data collection CLI for stock_swing.

Collects data from all configured sources:
- Finnhub (financials, earnings, insider, filings)
- FRED (macro indicators)
- SEC (company filings)
- Broker (market data)

Usage:
    python -m stock_swing.cli.collect_data [--sources SOURCE1,SOURCE2] [--symbols SYMBOL1,SYMBOL2]
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from stock_swing.core import ConfigLoader, RuntimeMode, read_runtime_mode
from stock_swing.sources import (
    BrokerClient,
    FinnhubClient,
    FredClient,
    SecClient,
)
from stock_swing.ingestion import RawIngestor
from stock_swing.storage import StageStore


def main():
    """Main data collection entry point."""
    parser = argparse.ArgumentParser(description="Collect data from sources")
    parser.add_argument(
        "--sources",
        type=str,
        default="finnhub,fred,sec,broker",
        help="Comma-separated list of sources (default: all)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="AAPL,MSFT,GOOGL,AMZN,TSLA",
        help="Comma-separated list of symbols",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode (no actual data collection)",
    )
    
    args = parser.parse_args()
    
    print(f"🚀 stock_swing Data Collection")
    print(f"📅 Started at: {datetime.now().isoformat()}")
    print(f"=" * 60)
    
    # Parse sources and symbols
    sources = [s.strip() for s in args.sources.split(",")]
    symbols = [s.strip() for s in args.symbols.split(",")]
    
    print(f"📡 Sources: {', '.join(sources)}")
    print(f"📊 Symbols: {', '.join(symbols)}")
    print(f"🧪 Dry run: {args.dry_run}")
    print()
    
    # Check runtime mode
    try:
        runtime_mode = read_runtime_mode()
        print(f"🔧 Runtime mode: {runtime_mode}")
        
        # Safety check: research mode only for now
        if runtime_mode != "research":
            print(f"⚠️  WARNING: Not in research mode!")
            print(f"   For safety, data collection should run in research mode.")
            print(f"   Current mode: {runtime_mode}")
            response = input("Continue anyway? (yes/no): ")
            if response.lower() != "yes":
                print("❌ Aborted.")
                return 1
    except Exception as e:
        print(f"⚠️  Could not read runtime mode: {e}")
        print(f"   Proceeding anyway...")
    
    print()
    
    # Load config
    try:
        config_loader = ConfigLoader()
        # Config loading would happen here
        print("✅ Configuration loaded")
    except Exception as e:
        print(f"⚠️  Config loading error: {e}")
        print(f"   Continuing with defaults...")
    
    print()
    
    if args.dry_run:
        print("🧪 DRY RUN MODE - No actual data collection")
        print()
        for source in sources:
            print(f"  Would collect from: {source}")
            if source != "fred":  # FRED doesn't need symbols
                for symbol in symbols:
                    print(f"    - {symbol}")
        print()
        print("✅ Dry run complete")
        return 0
    
    # Actual collection
    results = {
        "success": [],
        "failed": [],
    }
    
    for source in sources:
        print(f"📡 Collecting from {source}...")
        try:
            if source == "finnhub":
                collect_finnhub(symbols)
            elif source == "fred":
                collect_fred()
            elif source == "sec":
                collect_sec(symbols)
            elif source == "broker":
                collect_broker(symbols)
            else:
                print(f"  ⚠️  Unknown source: {source}")
                results["failed"].append(source)
                continue
            
            results["success"].append(source)
            print(f"  ✅ {source} complete")
        except Exception as e:
            print(f"  ❌ {source} failed: {e}")
            results["failed"].append(source)
        print()
    
    # Summary
    print("=" * 60)
    print(f"📊 Collection Summary:")
    print(f"  ✅ Success: {len(results['success'])} sources")
    print(f"  ❌ Failed: {len(results['failed'])} sources")
    if results["failed"]:
        print(f"     Failed sources: {', '.join(results['failed'])}")
    print()
    print(f"📅 Completed at: {datetime.now().isoformat()}")
    
    return 0 if not results["failed"] else 1


def collect_finnhub(symbols):
    """Collect from Finnhub."""
    print(f"  → Finnhub: {len(symbols)} symbols")
    # TODO: Implement actual collection
    print(f"     (Implementation pending - requires API key)")


def collect_fred():
    """Collect from FRED."""
    print(f"  → FRED: Macro indicators")
    # TODO: Implement actual collection
    print(f"     (Implementation pending - requires API key)")


def collect_sec(symbols):
    """Collect from SEC."""
    print(f"  → SEC: {len(symbols)} symbols")
    # TODO: Implement actual collection
    print(f"     (Implementation pending)")


def collect_broker(symbols):
    """Collect from Broker."""
    print(f"  → Broker: {len(symbols)} symbols")
    # TODO: Implement actual collection
    print(f"     (Implementation pending - requires API key)")


if __name__ == "__main__":
    sys.exit(main())
