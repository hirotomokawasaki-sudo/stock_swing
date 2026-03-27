#!/usr/bin/env python3
"""Data analysis CLI for stock_swing.

Analyzes collected data through the full pipeline:
1. Normalize raw data → canonical records
2. Extract features (MacroRegime, EarningsEvent, PriceMomentum)
3. Generate signals (EventSwing, BreakoutMomentum strategies)
4. Create decisions (DecisionEngine + RiskValidator)
5. Generate reports

Usage:
    python -m stock_swing.cli.analyze_data [--symbols SYMBOL1,SYMBOL2]
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from stock_swing.core import RuntimeMode, read_runtime_mode


def main():
    """Main analysis entry point."""
    parser = argparse.ArgumentParser(description="Analyze collected data")
    parser.add_argument(
        "--symbols",
        type=str,
        default="AAPL,MSFT,GOOGL,AMZN,TSLA",
        help="Comma-separated list of symbols",
    )
    parser.add_argument(
        "--skip-normalization",
        action="store_true",
        help="Skip normalization step",
    )
    parser.add_argument(
        "--skip-features",
        action="store_true",
        help="Skip feature extraction",
    )
    parser.add_argument(
        "--skip-signals",
        action="store_true",
        help="Skip signal generation",
    )
    parser.add_argument(
        "--skip-decisions",
        action="store_true",
        help="Skip decision making",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode (no actual analysis)",
    )
    
    args = parser.parse_args()
    
    print(f"📊 stock_swing Data Analysis")
    print(f"📅 Started at: {datetime.now().isoformat()}")
    print(f"=" * 60)
    
    # Parse symbols
    symbols = [s.strip() for s in args.symbols.split(",")]
    
    print(f"📈 Symbols: {', '.join(symbols)}")
    print(f"🧪 Dry run: {args.dry_run}")
    print()
    
    # Check runtime mode
    try:
        runtime_mode = read_runtime_mode()
        print(f"🔧 Runtime mode: {runtime_mode}")
        
        # Safety check
        if runtime_mode not in ["research", "paper"]:
            print(f"⚠️  WARNING: Not in research/paper mode!")
            print(f"   Analysis should run in research or paper mode.")
            print(f"   Current mode: {runtime_mode}")
            response = input("Continue anyway? (yes/no): ")
            if response.lower() != "yes":
                print("❌ Aborted.")
                return 1
    except Exception as e:
        print(f"⚠️  Could not read runtime mode: {e}")
        print(f"   Proceeding anyway...")
    
    print()
    
    if args.dry_run:
        print("🧪 DRY RUN MODE - No actual analysis")
        print()
        print("Analysis pipeline:")
        if not args.skip_normalization:
            print("  1. ✓ Normalize raw data → canonical records")
        if not args.skip_features:
            print("  2. ✓ Extract features (MacroRegime, EarningsEvent, PriceMomentum)")
        if not args.skip_signals:
            print("  3. ✓ Generate signals (EventSwing, BreakoutMomentum)")
        if not args.skip_decisions:
            print("  4. ✓ Create decisions (DecisionEngine + RiskValidator)")
        print("  5. ✓ Generate reports")
        print()
        print("✅ Dry run complete")
        return 0
    
    # Actual analysis
    results = {
        "success": [],
        "failed": [],
    }
    
    # Step 1: Normalization
    if not args.skip_normalization:
        print("📝 Step 1: Normalizing raw data...")
        try:
            normalize_data(symbols)
            results["success"].append("normalization")
            print("  ✅ Normalization complete")
        except Exception as e:
            print(f"  ❌ Normalization failed: {e}")
            results["failed"].append("normalization")
        print()
    
    # Step 2: Feature extraction
    if not args.skip_features:
        print("🔍 Step 2: Extracting features...")
        try:
            extract_features(symbols)
            results["success"].append("features")
            print("  ✅ Feature extraction complete")
        except Exception as e:
            print(f"  ❌ Feature extraction failed: {e}")
            results["failed"].append("features")
        print()
    
    # Step 3: Signal generation
    if not args.skip_signals:
        print("📡 Step 3: Generating signals...")
        try:
            generate_signals(symbols)
            results["success"].append("signals")
            print("  ✅ Signal generation complete")
        except Exception as e:
            print(f"  ❌ Signal generation failed: {e}")
            results["failed"].append("signals")
        print()
    
    # Step 4: Decision making
    if not args.skip_decisions:
        print("🎯 Step 4: Creating decisions...")
        try:
            create_decisions(symbols)
            results["success"].append("decisions")
            print("  ✅ Decision creation complete")
        except Exception as e:
            print(f"  ❌ Decision creation failed: {e}")
            results["failed"].append("decisions")
        print()
    
    # Step 5: Report generation
    print("📊 Step 5: Generating reports...")
    try:
        generate_reports(symbols)
        results["success"].append("reports")
        print("  ✅ Report generation complete")
    except Exception as e:
        print(f"  ❌ Report generation failed: {e}")
        results["failed"].append("reports")
    print()
    
    # Summary
    print("=" * 60)
    print(f"📊 Analysis Summary:")
    print(f"  ✅ Success: {len(results['success'])} steps")
    print(f"  ❌ Failed: {len(results['failed'])} steps")
    if results["failed"]:
        print(f"     Failed steps: {', '.join(results['failed'])}")
    print()
    print(f"📅 Completed at: {datetime.now().isoformat()}")
    
    return 0 if not results["failed"] else 1


def normalize_data(symbols):
    """Normalize raw data to canonical format."""
    print(f"  → Normalizing data for {len(symbols)} symbols")
    # TODO: Implement actual normalization
    print(f"     (Implementation pending)")


def extract_features(symbols):
    """Extract features from normalized data."""
    print(f"  → Extracting features for {len(symbols)} symbols")
    # TODO: Implement actual feature extraction
    print(f"     (Implementation pending)")


def generate_signals(symbols):
    """Generate trading signals from features."""
    print(f"  → Generating signals for {len(symbols)} symbols")
    # TODO: Implement actual signal generation
    print(f"     (Implementation pending)")


def create_decisions(symbols):
    """Create trading decisions from signals."""
    print(f"  → Creating decisions for {len(symbols)} symbols")
    # TODO: Implement actual decision creation
    print(f"     (Implementation pending)")


def generate_reports(symbols):
    """Generate analysis reports."""
    print(f"  → Generating reports for {len(symbols)} symbols")
    # TODO: Implement actual report generation
    print(f"     (Implementation pending)")


if __name__ == "__main__":
    sys.exit(main())
