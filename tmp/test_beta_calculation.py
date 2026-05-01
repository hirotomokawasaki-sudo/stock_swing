#!/usr/bin/env python3
"""Test beta calculation."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from console.services.benchmark_service import BenchmarkService
from console.services.dashboard_service import DashboardService

def test_beta():
    """Test beta calculation."""
    
    # Initialize services
    dashboard = DashboardService(PROJECT_ROOT)
    benchmark = BenchmarkService(PROJECT_ROOT)
    
    # Get trading data with snapshots
    trading = dashboard.get_trading()
    snapshots = trading.get('daily_snapshots', [])
    
    print(f"📊 Portfolio snapshots: {len(snapshots)}")
    if snapshots:
        print(f"   First: {snapshots[0].get('date')}")
        print(f"   Last: {snapshots[-1].get('date')}")
    
    # Load benchmark data
    spy_data = benchmark.load_benchmark_data("SPY")
    print(f"\n📈 SPY benchmark data: {len(spy_data)}")
    if spy_data:
        print(f"   First: {spy_data[0].get('date')}")
        print(f"   Last: {spy_data[-1].get('date')}")
    
    # Try beta calculation
    print("\n🔢 Calculating beta...")
    beta_result = benchmark.calculate_beta(snapshots, "SPY")
    
    print(f"\nResult: {beta_result}")
    
    if beta_result.get('available'):
        print(f"\n✅ Beta calculation successful:")
        print(f"   Beta: {beta_result.get('beta')}")
        print(f"   R²: {beta_result.get('r_squared')}")
        print(f"   Correlation: {beta_result.get('correlation')}")
    else:
        print(f"\n❌ Beta calculation failed:")
        print(f"   Error: {beta_result.get('error')}")
    
    # Check date overlap
    print("\n🔍 Date overlap analysis:")
    snapshot_dates = set(s.get('date') for s in snapshots if s.get('date'))
    benchmark_dates = set(b.get('date') for b in spy_data if b.get('date'))
    
    overlap = snapshot_dates & benchmark_dates
    print(f"   Snapshot dates: {len(snapshot_dates)}")
    print(f"   Benchmark dates: {len(benchmark_dates)}")
    print(f"   Overlapping dates: {len(overlap)}")
    
    if overlap:
        print(f"   First overlap: {min(overlap)}")
        print(f"   Last overlap: {max(overlap)}")

if __name__ == "__main__":
    test_beta()
