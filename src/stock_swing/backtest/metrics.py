"""Backtest metrics and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List
import math


@dataclass
class BacktestTrade:
    """Record of a single backtested trade.
    
    Attributes:
        symbol: Stock symbol
        entry_date: Trade entry datetime
        entry_price: Entry price
        exit_date: Trade exit datetime
        exit_price: Exit price
        qty: Quantity (shares)
        pnl: Profit/Loss in USD
        return_pct: Return as percentage
        hold_days: Number of days held
        exit_reason: Reason for exit (stop_loss, take_profit, max_hold, manual)
    """
    symbol: str
    entry_date: datetime
    entry_price: float
    exit_date: datetime
    exit_price: float
    qty: int
    pnl: float
    return_pct: float
    hold_days: int
    exit_reason: str


@dataclass
class BacktestResult:
    """Result of a backtest run.
    
    Attributes:
        parameters: Parameter set used for this backtest
        total_return: Total return as percentage
        sharpe_ratio: Sharpe ratio (assuming 252 trading days)
        win_rate: Percentage of winning trades
        max_drawdown: Maximum drawdown as percentage
        total_trades: Number of trades executed
        avg_pnl: Average P&L per trade
        profit_factor: Ratio of gross profit to gross loss
        trades: List of individual trades
        equity_curve: Daily equity values
        final_equity: Final equity value
        start_equity: Starting equity value
    """
    parameters: dict
    total_return: float
    sharpe_ratio: float
    win_rate: float
    max_drawdown: float
    total_trades: int
    avg_pnl: float
    profit_factor: float
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    final_equity: float = 0.0
    start_equity: float = 100000.0


class MetricsCalculator:
    """Calculate backtest performance metrics."""
    
    def calculate(
        self, 
        trades: List[BacktestTrade],
        equity_curve: List[float],
        start_equity: float = 100000.0
    ) -> BacktestResult:
        """Calculate all metrics from trade history.
        
        Args:
            trades: List of executed trades
            equity_curve: Daily equity values
            start_equity: Starting equity (default 100,000)
            
        Returns:
            BacktestResult with all calculated metrics
        """
        if not trades:
            return BacktestResult(
                parameters={},
                total_return=0.0,
                sharpe_ratio=0.0,
                win_rate=0.0,
                max_drawdown=0.0,
                total_trades=0,
                avg_pnl=0.0,
                profit_factor=0.0,
                trades=[],
                equity_curve=equity_curve,
                final_equity=start_equity,
                start_equity=start_equity
            )
        
        # Basic stats
        total_trades = len(trades)
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]
        
        win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
        
        total_pnl = sum(t.pnl for t in trades)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0.0
        
        # Profit factor
        gross_profit = sum(t.pnl for t in wins) if wins else 0.0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
        
        # Return
        final_equity = equity_curve[-1] if equity_curve else start_equity
        total_return = ((final_equity - start_equity) / start_equity) * 100
        
        # Sharpe ratio
        sharpe_ratio = self._calculate_sharpe(equity_curve, start_equity)
        
        # Max drawdown
        max_drawdown = self._calculate_max_drawdown(equity_curve)
        
        return BacktestResult(
            parameters={},
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            win_rate=win_rate * 100,  # Convert to percentage
            max_drawdown=max_drawdown,
            total_trades=total_trades,
            avg_pnl=avg_pnl,
            profit_factor=profit_factor,
            trades=trades,
            equity_curve=equity_curve,
            final_equity=final_equity,
            start_equity=start_equity
        )
    
    def _calculate_sharpe(self, equity_curve: List[float], start_equity: float) -> float:
        """Calculate Sharpe ratio from equity curve.
        
        Assumes 252 trading days per year.
        """
        if len(equity_curve) < 2:
            return 0.0
        
        # Calculate daily returns
        returns = []
        for i in range(1, len(equity_curve)):
            daily_return = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
            returns.append(daily_return)
        
        if not returns:
            return 0.0
        
        # Calculate mean and std
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance)
        
        if std_return == 0:
            return 0.0
        
        # Annualize (252 trading days)
        sharpe = (mean_return / std_return) * math.sqrt(252)
        
        return sharpe
    
    def _calculate_max_drawdown(self, equity_curve: List[float]) -> float:
        """Calculate maximum drawdown as percentage."""
        if not equity_curve:
            return 0.0
        
        peak = equity_curve[0]
        max_dd = 0.0
        
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            
            drawdown = ((peak - equity) / peak) * 100
            if drawdown > max_dd:
                max_dd = drawdown
        
        return max_dd
