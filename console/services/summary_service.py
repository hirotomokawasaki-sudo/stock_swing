"""Daily/Weekly summary generation service."""
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any
import json


class SummaryService:
    """Generate daily and weekly summaries."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
    
    def generate_daily_summary(self) -> Dict[str, Any]:
        """Generate daily summary."""
        today = datetime.now().date().isoformat()
        
        # PnL summary
        try:
            from stock_swing.tracking.pnl_tracker import PnLTracker
            tracker = PnLTracker(self.project_root)
            
            today_closed = [t for t in tracker.state.trades 
                           if t.get("status") == "closed" and 
                           (t.get("exit_time", "")[:10] == today)]
            
            today_pnl = sum(t.get("pnl", 0) for t in today_closed)
            
            pnl_summary = {
                "today_pnl": round(today_pnl, 2),
                "today_trades": len(today_closed),
                "cumulative_pnl": tracker.state.cumulative_realized_pnl,
                "total_trades": tracker.state.total_trades,
            }
            
            # Get open positions for alerts
            open_positions = tracker.get_open_positions()
        except:
            pnl_summary = {}
            open_positions = []
        
        # Top alerts
        alerts = self._generate_alerts(pnl_summary, open_positions)
        
        # Low conversion symbols
        low_conversion = self._analyze_low_conversion_symbols()
        
        return {
            "date": today,
            "alerts": alerts,
            "pnl_summary": pnl_summary,
            "low_conversion_symbols": low_conversion,
            "generated_at": datetime.now().isoformat(),
        }
    
    def _generate_alerts(self, pnl_summary: Dict[str, Any], open_positions: list) -> list:
        """Generate top alerts based on current state."""
        alerts = []
        
        # Alert: Large daily loss
        today_pnl = pnl_summary.get("today_pnl", 0)
        if today_pnl < -1000:
            alerts.append({
                "severity": "high",
                "title": f"Large daily loss: ${abs(today_pnl):,.2f}",
                "description": "Today's P&L is significantly negative",
                "action": "Review stop loss settings and position sizing"
            })
        
        # Alert: Too many open positions
        if len(open_positions) > 15:
            alerts.append({
                "severity": "medium",
                "title": f"High position count: {len(open_positions)}",
                "description": "Too many open positions may reduce focus",
                "action": "Consider closing underperforming positions"
            })
        
        # Alert: Unrealized loss threshold
        total_unrealized = sum(
            (p.get('current_price', 0) - p.get('entry_price', 0)) * p.get('qty', 0)
            for p in open_positions
        )
        if total_unrealized < -2000:
            alerts.append({
                "severity": "high",
                "title": f"Large unrealized loss: ${abs(total_unrealized):,.2f}",
                "description": "Unrealized losses are significant",
                "action": "Review individual positions for stop loss triggers"
            })
        
        return alerts
    
    def _analyze_low_conversion_symbols(self) -> list:
        """Analyze symbols with low conversion rates."""
        try:
            # Load decisions
            decisions_dir = self.project_root / "data" / "decisions"
            if not decisions_dir.exists():
                return []
            
            # Count decisions and submissions by symbol
            from collections import defaultdict
            symbol_stats = defaultdict(lambda: {"decisions": 0, "submissions": 0})
            
            # Recent decisions (last 100)
            decision_files = sorted(
                decisions_dir.glob("decision_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )[:100]
            
            for df in decision_files:
                try:
                    decision = json.loads(df.read_text())
                    symbol = decision.get('symbol')
                    action = decision.get('action', '').lower()
                    
                    if symbol and action in ['buy', 'sell']:
                        symbol_stats[symbol]["decisions"] += 1
                        
                        # Check if submitted (risk_state == pass)
                        if decision.get('risk_state') == 'pass':
                            symbol_stats[symbol]["submissions"] += 1
                except:
                    continue
            
            # Calculate conversion rates
            low_conversion = []
            for symbol, stats in symbol_stats.items():
                if stats["decisions"] >= 3:  # At least 3 decisions
                    conv_rate = (stats["submissions"] / stats["decisions"]) * 100 if stats["decisions"] > 0 else 0
                    if conv_rate < 20:  # Less than 20% conversion
                        low_conversion.append({
                            "symbol": symbol,
                            "decisions": stats["decisions"],
                            "submissions": stats["submissions"],
                            "conversion_rate": round(conv_rate, 1)
                        })
            
            # Sort by decision count (most active first)
            low_conversion.sort(key=lambda x: x["decisions"], reverse=True)
            
            return low_conversion[:10]  # Top 10
        except:
            return []
    
    def generate_weekly_summary(self, weeks: int = 1) -> Dict[str, Any]:
        """Generate weekly summary for the last N weeks."""
        from stock_swing.tracking.pnl_tracker import PnLTracker
        
        try:
            tracker = PnLTracker(self.project_root)
            
            # Get date range
            end_date = datetime.now()
            start_date = end_date - timedelta(weeks=weeks)
            
            # Filter trades in this period
            period_trades = [
                t for t in tracker.state.trades
                if t.get("status") == "closed" and
                t.get("exit_time") and
                self._parse_datetime(t.get("exit_time")) >= start_date
            ]
            
            # Calculate metrics
            total_pnl = sum(t.get("pnl", 0) for t in period_trades)
            winning_trades = [t for t in period_trades if t.get("pnl", 0) > 0]
            losing_trades = [t for t in period_trades if t.get("pnl", 0) < 0]
            
            win_rate = (len(winning_trades) / len(period_trades) * 100) if period_trades else 0
            
            avg_win = sum(t.get("pnl", 0) for t in winning_trades) / len(winning_trades) if winning_trades else 0
            avg_loss = sum(t.get("pnl", 0) for t in losing_trades) / len(losing_trades) if losing_trades else 0
            
            profit_factor = abs(sum(t.get("pnl", 0) for t in winning_trades) / sum(t.get("pnl", 0) for t in losing_trades)) if losing_trades and sum(t.get("pnl", 0) for t in losing_trades) != 0 else 0
            
            # Best and worst trades
            best_trade = max(period_trades, key=lambda t: t.get("pnl", 0)) if period_trades else None
            worst_trade = min(period_trades, key=lambda t: t.get("pnl", 0)) if period_trades else None
            
            # Strategy breakdown
            from collections import defaultdict
            strategy_stats = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0})
            
            for trade in period_trades:
                strategy = trade.get("strategy_id", "unknown")
                strategy_stats[strategy]["trades"] += 1
                strategy_stats[strategy]["pnl"] += trade.get("pnl", 0)
                if trade.get("pnl", 0) > 0:
                    strategy_stats[strategy]["wins"] += 1
            
            # Convert to list
            strategies = [
                {
                    "strategy_id": strategy,
                    "trades": stats["trades"],
                    "pnl": round(stats["pnl"], 2),
                    "win_rate": round((stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0, 1)
                }
                for strategy, stats in strategy_stats.items()
            ]
            strategies.sort(key=lambda s: s["pnl"], reverse=True)
            
            # Symbol breakdown
            symbol_stats = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0})
            
            for trade in period_trades:
                symbol = trade.get("symbol", "unknown")
                symbol_stats[symbol]["trades"] += 1
                symbol_stats[symbol]["pnl"] += trade.get("pnl", 0)
                if trade.get("pnl", 0) > 0:
                    symbol_stats[symbol]["wins"] += 1
            
            # Top performers
            top_symbols = sorted(
                [
                    {
                        "symbol": symbol,
                        "trades": stats["trades"],
                        "pnl": round(stats["pnl"], 2),
                        "win_rate": round((stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0, 1)
                    }
                    for symbol, stats in symbol_stats.items()
                ],
                key=lambda s: s["pnl"],
                reverse=True
            )[:10]
            
            # Weekly equity progression (from snapshots)
            daily_snapshots = list(tracker.state.daily_snapshots)
            weekly_snapshots = [
                snap for snap in daily_snapshots
                if self._parse_datetime(snap.get("date")) >= start_date
            ]
            
            return {
                "period": {
                    "start": start_date.date().isoformat(),
                    "end": end_date.date().isoformat(),
                    "weeks": weeks
                },
                "summary": {
                    "total_trades": len(period_trades),
                    "winning_trades": len(winning_trades),
                    "losing_trades": len(losing_trades),
                    "win_rate": round(win_rate, 1),
                    "total_pnl": round(total_pnl, 2),
                    "avg_win": round(avg_win, 2),
                    "avg_loss": round(avg_loss, 2),
                    "profit_factor": round(profit_factor, 2)
                },
                "best_trade": {
                    "symbol": best_trade.get("symbol") if best_trade else None,
                    "pnl": round(best_trade.get("pnl", 0), 2) if best_trade else 0,
                    "exit_time": best_trade.get("exit_time") if best_trade else None
                } if best_trade else None,
                "worst_trade": {
                    "symbol": worst_trade.get("symbol") if worst_trade else None,
                    "pnl": round(worst_trade.get("pnl", 0), 2) if worst_trade else 0,
                    "exit_time": worst_trade.get("exit_time") if worst_trade else None
                } if worst_trade else None,
                "by_strategy": strategies,
                "top_symbols": top_symbols,
                "equity_progression": [
                    {
                        "date": snap.get("date"),
                        "equity": snap.get("equity"),
                        "realized_pnl": snap.get("realized_pnl")
                    }
                    for snap in weekly_snapshots[-7:]  # Last 7 days
                ],
                "generated_at": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "error": str(e),
                "period": {
                    "start": (datetime.now() - timedelta(weeks=weeks)).date().isoformat(),
                    "end": datetime.now().date().isoformat(),
                    "weeks": weeks
                }
            }
    
    def _parse_datetime(self, dt_str: Any) -> datetime:
        """Parse datetime string."""
        if not dt_str:
            return datetime.min.replace(tzinfo=None)
        if isinstance(dt_str, datetime):
            # Make naive for comparison
            return dt_str.replace(tzinfo=None) if dt_str.tzinfo else dt_str
        try:
            # Try ISO format and make naive
            dt = datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except:
            return datetime.min.replace(tzinfo=None)
