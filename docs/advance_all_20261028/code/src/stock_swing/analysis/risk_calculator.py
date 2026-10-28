"""Risk metrics calculator.

Calculates portfolio risk metrics including Kelly Criterion, drawdown,
portfolio heat, VaR, and overall risk score.
"""

from typing import List, Dict, Any, Optional
import numpy as np
from datetime import datetime, timezone


class RiskCalculator:
    """Calculate risk and portfolio health metrics."""
    
    def calculate_current_drawdown(
        self,
        equity_curve: List[float],
        percentage: bool = True
    ) -> float:
        """Calculate current drawdown from peak.
        
        Args:
            equity_curve: List of equity values over time
            percentage: If True, return as percentage; else dollar amount
            
        Returns:
            Current drawdown (positive number)
        """
        if not equity_curve or len(equity_curve) < 2:
            return 0.0
        
        current_equity = equity_curve[-1]
        peak_equity = max(equity_curve)
        
        if peak_equity == 0:
            return 0.0
        
        drawdown_dollars = peak_equity - current_equity
        
        if percentage:
            return round((drawdown_dollars / peak_equity) * 100, 2)
        else:
            return round(drawdown_dollars, 2)
    
    def calculate_max_drawdown(
        self,
        equity_curve: List[float],
        percentage: bool = True
    ) -> float:
        """Calculate maximum drawdown experienced.
        
        Args:
            equity_curve: List of equity values over time
            percentage: If True, return as percentage
            
        Returns:
            Maximum drawdown (positive number)
        """
        if not equity_curve or len(equity_curve) < 2:
            return 0.0
        
        equity_array = np.array(equity_curve)
        running_max = np.maximum.accumulate(equity_array)
        drawdowns = running_max - equity_array
        
        if percentage:
            # Avoid division by zero
            with np.errstate(divide='ignore', invalid='ignore'):
                dd_pct = np.where(running_max > 0, (drawdowns / running_max) * 100, 0)
            max_dd = np.max(dd_pct)
        else:
            max_dd = np.max(drawdowns)
        
        return round(max_dd, 2)
    
    def calculate_kelly_criterion(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float
    ) -> float:
        """Calculate Kelly Criterion optimal position size.
        
        Formula: f* = (p*b - q) / b
        where:
          p = win probability
          q = loss probability (1-p)
          b = win/loss ratio
        
        Args:
            win_rate: Win probability (0-1)
            avg_win: Average winning trade P&L
            avg_loss: Average losing trade P&L (absolute value)
            
        Returns:
            Optimal position size as fraction (0-1)
        """
        if win_rate <= 0 or win_rate >= 1:
            return 0.0
        
        if avg_win <= 0 or avg_loss <= 0:
            return 0.0
        
        p = win_rate
        q = 1 - p
        b = avg_win / abs(avg_loss)  # Win/loss ratio
        
        kelly_pct = (p * b - q) / b
        
        # Kelly can be negative (system has negative edge)
        # Cap at reasonable max (50% for safety)
        kelly_pct = max(0.0, min(kelly_pct, 0.5))
        
        return round(kelly_pct, 4)
    
    def calculate_portfolio_heat(
        self,
        positions: List[Dict[str, Any]],
        total_equity: float
    ) -> float:
        """Calculate portfolio heat (% of capital at risk).
        
        Estimates total capital currently at risk across all positions.
        
        Args:
            positions: List of open positions
            total_equity: Total account equity
            
        Returns:
            Portfolio heat as percentage (0-100)
        """
        if not positions or total_equity <= 0:
            return 0.0
        
        total_exposure = sum(abs(p.get('market_value', 0)) for p in positions)
        
        heat_pct = (total_exposure / total_equity) * 100
        
        return round(heat_pct, 2)
    
    def calculate_risk_score(
        self,
        positions: List[Dict],
        total_equity: float,
        current_drawdown_pct: float,
        portfolio_heat: float,
        open_pnl: float
    ) -> float:
        """Calculate overall risk score (0-10).
        
        Combines multiple risk factors into single score:
        - Portfolio concentration
        - Current drawdown
        - Open P&L
        - Number of positions
        
        Score interpretation:
          0-3: Low risk (green)
          4-6: Moderate risk (yellow)
          7-10: High risk (red)
        
        Args:
            positions: Open positions
            total_equity: Total equity
            current_drawdown_pct: Current DD %
            portfolio_heat: Portfolio heat %
            open_pnl: Unrealized P&L
            
        Returns:
            Risk score (0-10)
        """
        score = 0.0
        
        # Factor 1: Portfolio heat (0-3 points)
        # >80% = 3, 60-80% = 2, 40-60% = 1, <40% = 0
        if portfolio_heat > 80:
            score += 3
        elif portfolio_heat > 60:
            score += 2
        elif portfolio_heat > 40:
            score += 1
        
        # Factor 2: Current drawdown (0-3 points)
        # >10% = 3, 5-10% = 2, 2-5% = 1, <2% = 0
        if current_drawdown_pct > 10:
            score += 3
        elif current_drawdown_pct > 5:
            score += 2
        elif current_drawdown_pct > 2:
            score += 1
        
        # Factor 3: Open P&L relative to equity (0-2 points)
        # < -5% = 2, -2% to -5% = 1, > -2% = 0
        if total_equity > 0:
            open_pnl_pct = (open_pnl / total_equity) * 100
            if open_pnl_pct < -5:
                score += 2
            elif open_pnl_pct < -2:
                score += 1
        
        # Factor 4: Concentration (0-2 points)
        # Check if any single position > 30% of equity
        if positions and total_equity > 0:
            max_position_pct = max(
                abs(p.get('market_value', 0)) / total_equity * 100
                for p in positions
            )
            if max_position_pct > 30:
                score += 2
            elif max_position_pct > 20:
                score += 1
        
        return round(min(score, 10.0), 1)
    
    def calculate_var(
        self,
        returns: List[float],
        confidence: float = 0.95,
        time_horizon_days: int = 1
    ) -> float:
        """Calculate Value at Risk (VaR).
        
        Args:
            returns: Historical returns (as fractions, not %)
            confidence: Confidence level (0.95 = 95%)
            time_horizon_days: Time horizon in days
            
        Returns:
            VaR as percentage (positive number represents potential loss)
        """
        if not returns or len(returns) < 10:
            return 0.0
        
        returns_array = np.array(returns)
        
        # Historical VaR (percentile method)
        var_percentile = (1 - confidence) * 100
        var_value = np.percentile(returns_array, var_percentile)
        
        # Scale by time horizon (sqrt of time)
        var_scaled = var_value * np.sqrt(time_horizon_days)
        
        # Return as positive percentage
        return round(abs(var_scaled) * 100, 2)
    
    def get_risk_level(self, risk_score: float) -> str:
        """Convert risk score to risk level label.
        
        Args:
            risk_score: Risk score (0-10)
            
        Returns:
            Risk level: 'LOW', 'MODERATE', or 'HIGH'
        """
        if risk_score < 4:
            return 'LOW'
        elif risk_score < 7:
            return 'MODERATE'
        else:
            return 'HIGH'
    
    def get_risk_emoji(self, risk_score: float) -> str:
        """Get emoji for risk level.
        
        Args:
            risk_score: Risk score (0-10)
            
        Returns:
            Emoji: 🟢 (low), 🟡 (moderate), or 🔴 (high)
        """
        if risk_score < 4:
            return '🟢'
        elif risk_score < 7:
            return '🟡'
        else:
            return '🔴'
    
    def days_since_last_trade(self, trades: List[Dict]) -> float:
        """Calculate days since last closed trade.
        
        Args:
            trades: List of trades with exit_time
            
        Returns:
            Days since last trade (float)
        """
        if not trades:
            return 0.0
        
        # Filter closed trades with exit_time
        closed_trades = [
            t for t in trades
            if t.get('status') == 'closed' and t.get('exit_time')
        ]
        
        if not closed_trades:
            return 0.0
        
        try:
            # Find most recent exit
            latest_exit = max(
                datetime.fromisoformat(t['exit_time'].replace('Z', '+00:00'))
                for t in closed_trades
            )
            
            now = datetime.now(timezone.utc)
            days = (now - latest_exit).total_seconds() / 86400
            
            return round(days, 2)
        except:
            return 0.0
