#!/usr/bin/env python3
"""Calculate baseline performance metrics for parameter optimization.

This script analyzes the current system performance using collected data
to establish a baseline for comparison during parameter optimization.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any


def load_pnl_data(project_root: Path) -> dict[str, Any]:
    """Load P&L tracking data."""
    pnl_file = project_root / "data" / "tracking" / "pnl_state.json"
    if not pnl_file.exists():
        raise FileNotFoundError(f"PnL file not found: {pnl_file}")
    return json.loads(pnl_file.read_text())


def calculate_baseline_metrics(pnl_data: dict[str, Any]) -> dict[str, Any]:
    """Calculate baseline performance metrics."""
    snapshots = pnl_data.get("daily_snapshots", [])
    trades = pnl_data.get("trades", [])
    
    if not snapshots:
        return {"error": "No snapshots found"}
    
    # Extract equity curve
    equity_values = [s["equity"] for s in snapshots]
    dates = [s["date"] for s in snapshots]
    
    # Overall performance
    initial_equity = equity_values[0]
    final_equity = equity_values[-1]
    total_return = (final_equity - initial_equity) / initial_equity
    
    # Calculate returns
    daily_returns = []
    for i in range(1, len(equity_values)):
        daily_return = (equity_values[i] - equity_values[i-1]) / equity_values[i-1]
        daily_returns.append(daily_return)
    
    # Max drawdown
    peak = equity_values[0]
    max_dd = 0
    for equity in equity_values:
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd
    
    # Sharpe ratio (assuming risk-free rate = 0 for simplicity)
    if daily_returns:
        avg_return = statistics.mean(daily_returns)
        std_return = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0
        sharpe = (avg_return / std_return * (252 ** 0.5)) if std_return > 0 else 0
    else:
        avg_return = 0
        std_return = 0
        sharpe = 0
    
    # Trade analysis
    closed_trades = [t for t in trades if t.get("status") == "closed" or t.get("pnl") is not None]
    open_trades = [t for t in trades if t.get("status") == "open"]
    
    winning_trades = [t for t in closed_trades if t.get("pnl", 0) > 0]
    losing_trades = [t for t in closed_trades if t.get("pnl", 0) < 0]
    
    win_rate = len(winning_trades) / len(closed_trades) if closed_trades else 0
    
    avg_win = statistics.mean([t["pnl"] for t in winning_trades]) if winning_trades else 0
    avg_loss = statistics.mean([t["pnl"] for t in losing_trades]) if losing_trades else 0
    
    profit_factor = (
        sum([t["pnl"] for t in winning_trades]) / abs(sum([t["pnl"] for t in losing_trades]))
        if losing_trades and winning_trades
        else 0
    )
    
    # Signal analysis from snapshots
    total_signals = sum(s.get("signals_generated", 0) for s in snapshots)
    total_orders = sum(s.get("orders_submitted", 0) for s in snapshots)
    execution_rate = total_orders / total_signals if total_signals > 0 else 0
    
    return {
        "period": {
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "trading_days": len(snapshots),
        },
        "returns": {
            "initial_equity": initial_equity,
            "final_equity": final_equity,
            "total_return": total_return,
            "total_return_pct": total_return * 100,
            "daily_avg_return": avg_return,
            "daily_std_return": std_return,
            "sharpe_ratio": sharpe,
        },
        "risk": {
            "max_drawdown": max_dd,
            "max_drawdown_pct": max_dd * 100,
            "peak_equity": max(equity_values),
        },
        "trading": {
            "total_trades": len(trades),
            "closed_trades": len(closed_trades),
            "open_trades": len(open_trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": win_rate,
            "win_rate_pct": win_rate * 100,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_win_loss_ratio": avg_win / abs(avg_loss) if avg_loss != 0 else 0,
            "profit_factor": profit_factor,
        },
        "signals": {
            "total_signals": total_signals,
            "total_orders": total_orders,
            "execution_rate": execution_rate,
            "execution_rate_pct": execution_rate * 100,
            "avg_signals_per_day": total_signals / len(snapshots) if snapshots else 0,
        },
    }


def print_metrics(metrics: dict[str, Any]) -> None:
    """Print metrics in readable format."""
    print("=" * 60)
    print("BASELINE PERFORMANCE METRICS")
    print("=" * 60)
    print()
    
    if "error" in metrics:
        print(f"ERROR: {metrics['error']}")
        return
    
    # Period
    p = metrics["period"]
    print(f"Period: {p['start_date']} to {p['end_date']}")
    print(f"Trading Days: {p['trading_days']}")
    print()
    
    # Returns
    r = metrics["returns"]
    print("RETURNS:")
    print(f"  Initial Equity:    ${r['initial_equity']:>12,.2f}")
    print(f"  Final Equity:      ${r['final_equity']:>12,.2f}")
    print(f"  Total Return:      {r['total_return_pct']:>12.2f}%")
    print(f"  Sharpe Ratio:      {r['sharpe_ratio']:>12.2f}")
    print()
    
    # Risk
    risk = metrics["risk"]
    print("RISK:")
    print(f"  Max Drawdown:      {risk['max_drawdown_pct']:>12.2f}%")
    print(f"  Peak Equity:       ${risk['peak_equity']:>12,.2f}")
    print()
    
    # Trading
    t = metrics["trading"]
    print("TRADING:")
    print(f"  Total Trades:      {t['total_trades']:>12}")
    print(f"  Closed Trades:     {t['closed_trades']:>12}")
    print(f"  Open Trades:       {t['open_trades']:>12}")
    print(f"  Winning Trades:    {t['winning_trades']:>12}")
    print(f"  Losing Trades:     {t['losing_trades']:>12}")
    print(f"  Win Rate:          {t['win_rate_pct']:>12.2f}%")
    print(f"  Avg Win:           ${t['avg_win']:>12,.2f}")
    print(f"  Avg Loss:          ${t['avg_loss']:>12,.2f}")
    print(f"  Win/Loss Ratio:    {t['avg_win_loss_ratio']:>12.2f}")
    print(f"  Profit Factor:     {t['profit_factor']:>12.2f}")
    print()
    
    # Signals
    s = metrics["signals"]
    print("SIGNALS:")
    print(f"  Total Signals:     {s['total_signals']:>12}")
    print(f"  Orders Submitted:  {s['total_orders']:>12}")
    print(f"  Execution Rate:    {s['execution_rate_pct']:>12.2f}%")
    print(f"  Avg Signals/Day:   {s['avg_signals_per_day']:>12.1f}")
    print()
    print("=" * 60)


def main() -> int:
    """Main entry point."""
    import sys
    from pathlib import Path
    
    # Find project root
    project_root = Path(__file__).resolve().parents[3]
    
    try:
        # Load data
        print("Loading P&L data...")
        pnl_data = load_pnl_data(project_root)
        
        # Calculate metrics
        print("Calculating baseline metrics...\n")
        metrics = calculate_baseline_metrics(pnl_data)
        
        # Print results
        print_metrics(metrics)
        
        # Save to file
        output_file = project_root / "docs" / "reports" / "baseline_metrics.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(metrics, indent=2))
        print(f"\nMetrics saved to: {output_file}")
        
        return 0
        
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
