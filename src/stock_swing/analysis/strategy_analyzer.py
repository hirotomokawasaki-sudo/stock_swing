"""Strategy performance analyzer.

Analyzes trading performance by strategy, symbol, and time period.
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional
from collections import defaultdict
import numpy as np


@dataclass
class StrategyMetrics:
    """Performance metrics for a strategy."""
    
    strategy_id: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    flat_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    avg_pnl: float
    largest_win: float
    largest_loss: float
    profit_factor: float  # Total wins / Total losses
    sharpe_ratio: float
    max_drawdown: float
    avg_duration_days: float


class StrategyAnalyzer:
    """Analyzes trading performance by strategy."""
    
    def __init__(self):
        self.strategy_metrics: Dict[str, StrategyMetrics] = {}
    
    def analyze_by_strategy(self, trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Analyze performance grouped by strategy.
        
        Args:
            trades: List of trade dicts with strategy_id, pnl, return_pct, etc.
            
        Returns:
            Dict mapping strategy_id to metrics dict
        """
        # Group trades by strategy
        by_strategy = defaultdict(list)
        for trade in trades:
            if trade.get('status') == 'closed':
                strategy_id = trade.get('strategy_id', 'unknown')
                by_strategy[strategy_id].append(trade)
        
        # Calculate metrics for each strategy
        results = {}
        for strategy_id, strategy_trades in by_strategy.items():
            metrics = self._calculate_metrics(strategy_id, strategy_trades)
            self.strategy_metrics[strategy_id] = metrics
            results[strategy_id] = asdict(metrics)
        
        return results
    
    def _calculate_metrics(self, strategy_id: str, trades: List[Dict]) -> StrategyMetrics:
        """Calculate performance metrics for a strategy."""
        if not trades:
            return self._empty_metrics(strategy_id)
        
        # Separate wins/losses
        wins = [t for t in trades if t.get('pnl', 0) > 0]
        losses = [t for t in trades if t.get('pnl', 0) < 0]
        flats = [t for t in trades if t.get('pnl', 0) == 0]
        
        # Basic counts
        total_trades = len(trades)
        winning_trades = len(wins)
        losing_trades = len(losses)
        flat_trades = len(flats)
        
        # P&L metrics
        total_pnl = sum(t.get('pnl', 0) for t in trades)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0.0
        
        win_pnls = [t.get('pnl', 0) for t in wins]
        loss_pnls = [t.get('pnl', 0) for t in losses]
        
        avg_win = np.mean(win_pnls) if win_pnls else 0.0
        avg_loss = np.mean(loss_pnls) if loss_pnls else 0.0
        largest_win = max(win_pnls) if win_pnls else 0.0
        largest_loss = min(loss_pnls) if loss_pnls else 0.0
        
        # Win rate
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        # Profit factor
        total_wins = sum(win_pnls) if win_pnls else 0.0
        total_losses = abs(sum(loss_pnls)) if loss_pnls else 0.0
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
        
        # Sharpe ratio (simplified: returns / std dev)
        returns = [t.get('return_pct', 0) for t in trades if t.get('return_pct') is not None]
        if len(returns) > 1:
            mean_return = np.mean(returns)
            std_return = np.std(returns, ddof=1)
            sharpe_ratio = (mean_return / std_return) if std_return > 0 else 0.0
        else:
            sharpe_ratio = 0.0
        
        # Max drawdown (from cumulative P&L)
        cumulative_pnl = np.cumsum([t.get('pnl', 0) for t in trades])
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdowns = running_max - cumulative_pnl
        max_drawdown = np.max(drawdowns) if len(drawdowns) > 0 else 0.0
        
        # Average duration
        durations = []
        for t in trades:
            if t.get('entry_time') and t.get('exit_time'):
                try:
                    from datetime import datetime
                    entry = datetime.fromisoformat(t['entry_time'].replace('Z', '+00:00'))
                    exit = datetime.fromisoformat(t['exit_time'].replace('Z', '+00:00'))
                    duration_days = (exit - entry).total_seconds() / 86400
                    durations.append(duration_days)
                except:
                    pass
        avg_duration = np.mean(durations) if durations else 0.0
        
        return StrategyMetrics(
            strategy_id=strategy_id,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            flat_trades=flat_trades,
            win_rate=round(win_rate, 4),
            total_pnl=round(total_pnl, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            avg_pnl=round(avg_pnl, 2),
            largest_win=round(largest_win, 2),
            largest_loss=round(largest_loss, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != float('inf') else 999.99,
            sharpe_ratio=round(sharpe_ratio, 3),
            max_drawdown=round(max_drawdown, 2),
            avg_duration_days=round(avg_duration, 2),
        )
    
    def _empty_metrics(self, strategy_id: str) -> StrategyMetrics:
        """Return empty metrics for a strategy with no trades."""
        return StrategyMetrics(
            strategy_id=strategy_id,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            flat_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            avg_pnl=0.0,
            largest_win=0.0,
            largest_loss=0.0,
            profit_factor=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            avg_duration_days=0.0,
        )
    
    def get_top_performers(self, by: str = 'sharpe', n: int = 5) -> List[Dict[str, Any]]:
        """Get top N strategies by specified metric.
        
        Args:
            by: Metric to sort by ('sharpe', 'win_rate', 'total_pnl', 'profit_factor')
            n: Number of top strategies to return
            
        Returns:
            List of strategy metrics dicts, sorted by specified metric
        """
        if not self.strategy_metrics:
            return []
        
        # Sort strategies by metric
        sorted_strategies = sorted(
            self.strategy_metrics.values(),
            key=lambda m: getattr(m, by, 0),
            reverse=True
        )
        
        return [asdict(m) for m in sorted_strategies[:n]]
    
    def get_symbol_breakdown(self, strategy_id: str, trades: List[Dict]) -> Dict[str, Dict[str, Any]]:
        """Get per-symbol performance for a specific strategy.
        
        Args:
            strategy_id: Strategy to analyze
            trades: All trades
            
        Returns:
            Dict mapping symbol to performance metrics
        """
        # Filter trades for this strategy
        strategy_trades = [
            t for t in trades
            if t.get('strategy_id') == strategy_id and t.get('status') == 'closed'
        ]
        
        # Group by symbol
        by_symbol = defaultdict(list)
        for trade in strategy_trades:
            symbol = trade.get('symbol', 'unknown')
            by_symbol[symbol].append(trade)
        
        # Calculate metrics per symbol
        results = {}
        for symbol, symbol_trades in by_symbol.items():
            pnls = [t.get('pnl', 0) for t in symbol_trades]
            wins = sum(1 for p in pnls if p > 0)
            
            results[symbol] = {
                'trades': len(symbol_trades),
                'wins': wins,
                'losses': len(symbol_trades) - wins,
                'win_rate': wins / len(symbol_trades) if symbol_trades else 0.0,
                'total_pnl': sum(pnls),
                'avg_pnl': np.mean(pnls) if pnls else 0.0,
            }
        
        return results
    
    def get_comparison_data(self) -> Dict[str, List[Any]]:
        """Get data formatted for comparison charts.
        
        Returns:
            Dict with labels and datasets for horizontal bar chart
        """
        if not self.strategy_metrics:
            return {'labels': [], 'datasets': []}
        
        strategies = list(self.strategy_metrics.values())
        
        return {
            'labels': [s.strategy_id for s in strategies],
            'total_trades': [s.total_trades for s in strategies],
            'win_rates': [s.win_rate * 100 for s in strategies],
            'sharpe_ratios': [s.sharpe_ratio for s in strategies],
            'total_pnls': [s.total_pnl for s in strategies],
            'profit_factors': [s.profit_factor for s in strategies],
        }
