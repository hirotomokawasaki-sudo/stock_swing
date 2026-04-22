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
    from datetime import datetime
    from collections import defaultdict
    
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
    
    # === NEW: Strategy breakdown ===
    strategy_stats = defaultdict(lambda: {"trades": [], "wins": 0, "losses": 0})
    for t in trades:
        strat = t.get("strategy_id", "unknown")
        strategy_stats[strat]["trades"].append(t)
        if t.get("pnl") is not None:
            if t["pnl"] > 0:
                strategy_stats[strat]["wins"] += 1
            elif t["pnl"] < 0:
                strategy_stats[strat]["losses"] += 1
    
    strategy_breakdown = {}
    for strat, stats in strategy_stats.items():
        strat_closed = [t for t in stats["trades"] if t.get("pnl") is not None]
        strat_pnls = [t["pnl"] for t in strat_closed]
        strategy_breakdown[strat] = {
            "total_trades": len(stats["trades"]),
            "closed_trades": len(strat_closed),
            "win_count": stats["wins"],
            "loss_count": stats["losses"],
            "win_rate": stats["wins"] / len(strat_closed) if strat_closed else 0,
            "avg_pnl": statistics.mean(strat_pnls) if strat_pnls else 0,
        }
    
    # === NEW: Trade duration analysis ===
    durations = []
    duration_buckets = {"0-2d": [], "2-5d": [], "5-10d": [], "10d+": []}
    
    for t in trades:
        if t.get("entry_time") and t.get("exit_time"):
            try:
                entry = datetime.fromisoformat(t["entry_time"].replace("Z", "+00:00"))
                exit = datetime.fromisoformat(t["exit_time"].replace("Z", "+00:00"))
                duration_days = (exit - entry).total_seconds() / 86400
                durations.append(duration_days)
                
                pnl_pct = t.get("pnl_pct", 0)
                if duration_days < 2:
                    duration_buckets["0-2d"].append(pnl_pct)
                elif duration_days < 5:
                    duration_buckets["2-5d"].append(pnl_pct)
                elif duration_days < 10:
                    duration_buckets["5-10d"].append(pnl_pct)
                else:
                    duration_buckets["10d+"].append(pnl_pct)
            except (ValueError, TypeError):
                pass
    
    duration_analysis = {
        "avg_hold_days": statistics.mean(durations) if durations else 0,
        "median_hold_days": statistics.median(durations) if durations else 0,
        "min_hold_days": min(durations) if durations else 0,
        "max_hold_days": max(durations) if durations else 0,
        "by_bucket": {
            k: {
                "count": len(v),
                "avg_return_pct": statistics.mean(v) * 100 if v else 0,
            }
            for k, v in duration_buckets.items()
        },
    }
    
    # === NEW: Symbol concentration ===
    symbol_counts = defaultdict(int)
    for t in trades:
        sym = t.get("symbol", "unknown")
        symbol_counts[sym] += 1
    
    total_trades_count = len(trades)
    top_symbols = sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # HHI (Herfindahl-Hirschman Index)
    hhi = sum((count / total_trades_count) ** 2 for count in symbol_counts.values())
    
    concentration_analysis = {
        "unique_symbols": len(symbol_counts),
        "top_5_symbols": [
            {"symbol": sym, "count": count, "pct": count / total_trades_count * 100}
            for sym, count in top_symbols
        ],
        "top_5_concentration_pct": sum(count for _, count in top_symbols) / total_trades_count * 100,
        "hhi_index": hhi,
    }
    
    # === NEW: Consecutive win/loss streaks ===
    sorted_trades = sorted(
        [t for t in trades if t.get("pnl") is not None],
        key=lambda x: x.get("entry_time", "")
    )
    
    max_win_streak = 0
    max_loss_streak = 0
    current_streak = 0
    current_type = None
    
    for t in sorted_trades:
        is_win = t["pnl"] > 0
        if current_type == is_win:
            current_streak += 1
        else:
            current_streak = 1
            current_type = is_win
        
        if is_win and current_streak > max_win_streak:
            max_win_streak = current_streak
        elif not is_win and current_streak > max_loss_streak:
            max_loss_streak = current_streak
    
    streak_analysis = {
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
    }
    
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
        "strategy_breakdown": strategy_breakdown,
        "duration_analysis": duration_analysis,
        "concentration_analysis": concentration_analysis,
        "streak_analysis": streak_analysis,
    }


def print_metrics(metrics: dict[str, Any]) -> None:
    """Print metrics in readable format."""
    print("=" * 70)
    print("BASELINE PERFORMANCE METRICS")
    print("=" * 70)
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
    print(f"  Initial Equity:        ${r['initial_equity']:>12,.2f}")
    print(f"  Final Equity:          ${r['final_equity']:>12,.2f}")
    print(f"  Total Return:           {r['total_return_pct']:>11.2f}%")
    print(f"  Daily Avg Return:       {r['daily_avg_return']*100:>11.4f}%")
    print(f"  Daily Std Return:       {r['daily_std_return']*100:>11.4f}%")
    print(f"  Sharpe Ratio:           {r['sharpe_ratio']:>11.2f}")
    print()
    
    # Risk
    risk = metrics["risk"]
    print("RISK:")
    print(f"  Max Drawdown:           {risk['max_drawdown_pct']:>11.2f}%")
    print(f"  Peak Equity:           ${risk['peak_equity']:>12,.2f}")
    print()
    
    # Trading
    t = metrics["trading"]
    print("TRADING ACTIVITY:")
    print(f"  Total Trades:          {t['total_trades']:>12}")
    print(f"  Closed Trades:         {t['closed_trades']:>12}")
    print(f"  Open Trades:           {t['open_trades']:>12}")
    print(f"  Winning Trades:        {t['winning_trades']:>12}")
    print(f"  Losing Trades:         {t['losing_trades']:>12}")
    print()
    
    print("TRADING PERFORMANCE:")
    win_rate_note = " *" if t['win_rate_pct'] >= 95 else ""
    print(f"  Win Rate:               {t['win_rate_pct']:>11.2f}%{win_rate_note}")
    if t['winning_trades'] > 0:
        print(f"  Avg Win:               ${t['avg_win']:>12,.2f}")
    if t['losing_trades'] > 0:
        print(f"  Avg Loss:              ${t['avg_loss']:>12,.2f}")
        print(f"  Win/Loss Ratio:         {t['avg_win_loss_ratio']:>11.2f}")
        print(f"  Profit Factor:          {t['profit_factor']:>11.2f}")
    else:
        print(f"  Avg Loss:               N/A (no losing trades)")
        print(f"  Win/Loss Ratio:         N/A")
        print(f"  Profit Factor:          N/A")
    print()
    
    # Signals
    s = metrics["signals"]
    print("SIGNAL EXECUTION:")
    print(f"  Total Signals:         {s['total_signals']:>12}")
    print(f"  Orders Submitted:      {s['total_orders']:>12}")
    print(f"  Execution Rate:         {s['execution_rate_pct']:>11.2f}%")
    print(f"  Avg Signals/Day:        {s['avg_signals_per_day']:>11.1f}")
    print()
    
    # Strategy Breakdown
    strat_breakdown = metrics.get("strategy_breakdown", {})
    if strat_breakdown:
        print("STRATEGY PERFORMANCE:")
        for strat_name, strat_metrics in sorted(strat_breakdown.items()):
            print(f"  {strat_name}:")
            print(f"    Total Trades:        {strat_metrics['total_trades']:>12}")
            print(f"    Closed Trades:       {strat_metrics['closed_trades']:>12}")
            if strat_metrics['closed_trades'] > 0:
                print(f"    Win Rate:             {strat_metrics['win_rate']*100:>11.1f}%")
                print(f"    Avg P&L:             ${strat_metrics['avg_pnl']:>12,.2f}")
        print()
    
    # Duration Analysis
    dur = metrics.get("duration_analysis", {})
    if dur.get("avg_hold_days", 0) > 0:
        print("TRADE DURATION:")
        print(f"  Avg Hold Time:          {dur['avg_hold_days']:>11.1f} days")
        print(f"  Median Hold Time:       {dur['median_hold_days']:>11.1f} days")
        print(f"  Range:                  {dur['min_hold_days']:>5.1f} - {dur['max_hold_days']:>5.1f} days")
        print()
        print("  Performance by Duration:")
        for bucket, stats in sorted(dur.get("by_bucket", {}).items()):
            if stats["count"] > 0:
                print(f"    {bucket:6}  {stats['count']:>3} trades  "
                      f"({stats['avg_return_pct']:>+6.2f}% avg)")
        print()
    
    # Concentration Analysis
    conc = metrics.get("concentration_analysis", {})
    if conc:
        print("SYMBOL CONCENTRATION:")
        print(f"  Unique Symbols:         {conc['unique_symbols']:>12}")
        print(f"  Top 5 Concentration:     {conc['top_5_concentration_pct']:>11.1f}%")
        print(f"  HHI Index:               {conc['hhi_index']:>11.3f}")
        print()
        print("  Top 5 Symbols:")
        for sym_data in conc.get("top_5_symbols", []):
            print(f"    {sym_data['symbol']:6}  {sym_data['count']:>3} trades "
                  f"({sym_data['pct']:>5.1f}%)")
        print()
    
    # Streak Analysis
    streak = metrics.get("streak_analysis", {})
    if streak:
        print("CONSECUTIVE STREAKS:")
        print(f"  Max Win Streak:         {streak['max_win_streak']:>12}")
        print(f"  Max Loss Streak:        {streak['max_loss_streak']:>12}")
        print()
    
    # Notes
    if t['win_rate_pct'] >= 95:
        print("NOTES:")
        print("  * Win rate may be unreliable - very few or no losing trades")
        print("    suggests incomplete exit tracking or insufficient sample")
        print()
    
    print("=" * 70)


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
