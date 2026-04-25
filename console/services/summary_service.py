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
        
        # Top alerts (simplified)
        alerts = []
        
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
        except:
            pnl_summary = {}
        
        # Low conversion symbols
        low_conversion = []
        
        return {
            "date": today,
            "alerts": alerts,
            "pnl_summary": pnl_summary,
            "low_conversion_symbols": low_conversion,
            "generated_at": datetime.now().isoformat(),
        }
