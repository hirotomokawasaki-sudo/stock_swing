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
