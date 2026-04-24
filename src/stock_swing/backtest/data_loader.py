"""Data loader for backtest engine."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any


class DataLoader:
    """Load historical trading data for backtesting."""
    
    def __init__(self, project_root: Path):
        """Initialize data loader.
        
        Args:
            project_root: Path to project root directory
        """
        self.project_root = Path(project_root)
        self.decisions_dir = self.project_root / "data" / "decisions"
        self.tracking_file = self.project_root / "data" / "tracking" / "pnl_state.json"
    
    def load_decisions(self, start_date: datetime | None = None, end_date: datetime | None = None) -> List[Dict[str, Any]]:
        """Load decision logs within date range.
        
        Args:
            start_date: Start date (inclusive), None for all
            end_date: End date (inclusive), None for all
            
        Returns:
            List of decision records
        """
        if not self.decisions_dir.exists():
            return []
        
        decisions = []
        
        for file_path in sorted(self.decisions_dir.glob("decision_*.json")):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                # Parse timestamp
                ts_str = data.get('timestamp', '')
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    
                    # Filter by date range
                    if start_date and ts < start_date:
                        continue
                    if end_date and ts > end_date:
                        continue
                
                decisions.append(data)
            
            except Exception:
                continue
        
        return decisions
    
    def load_trades(self) -> List[Dict[str, Any]]:
        """Load trade history from PnL tracker.
        
        Returns:
            List of trade records
        """
        if not self.tracking_file.exists():
            return []
        
        try:
            with open(self.tracking_file, 'r') as f:
                data = json.load(f)
            
            return data.get('trades', [])
        
        except Exception:
            return []
    
    def load_price_data(self, symbol: str, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Load historical price data for a symbol.
        
        Note: For now, this is a placeholder. In production, would fetch from
        broker API or cache.
        
        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            
        Returns:
            List of price bars (OHLCV data)
        """
        # TODO: Implement actual price data loading
        # For now, return empty list
        # In production, would:
        # 1. Check local cache
        # 2. Fetch from broker API if needed
        # 3. Store in cache for future use
        return []
    
    def get_date_range(self) -> tuple[datetime | None, datetime | None]:
        """Get the date range of available decision data.
        
        Returns:
            Tuple of (earliest_date, latest_date) or (None, None) if no data
        """
        decisions = self.load_decisions()
        
        if not decisions:
            return None, None
        
        dates = []
        for d in decisions:
            ts_str = d.get('timestamp', '')
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    dates.append(ts)
                except Exception:
                    continue
        
        if not dates:
            return None, None
        
        return min(dates), max(dates)
