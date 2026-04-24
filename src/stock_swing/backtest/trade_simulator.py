"""Trade simulator for backtesting."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any
from dataclasses import dataclass

from .metrics import BacktestTrade


@dataclass
class Position:
    """Active position in simulation."""
    symbol: str
    entry_date: datetime
    entry_price: float
    qty: int
    stop_loss_price: float
    take_profit_price: float
    max_exit_date: datetime


class TradeSimulator:
    """Simulate trades based on parameters and historical data."""
    
    def __init__(self, start_equity: float = 100000.0):
        """Initialize trade simulator.
        
        Args:
            start_equity: Starting equity for simulation
        """
        self.start_equity = start_equity
        self.current_equity = start_equity
        self.positions: Dict[str, Position] = {}
        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[float] = [start_equity]
    
    def reset(self):
        """Reset simulator state."""
        self.current_equity = self.start_equity
        self.positions = {}
        self.trades = []
        self.equity_curve = [self.start_equity]
    
    def can_enter_position(
        self, 
        symbol: str,
        entry_price: float,
        parameters: Dict[str, Any]
    ) -> tuple[bool, int]:
        """Check if we can enter a position and calculate quantity.
        
        Args:
            symbol: Stock symbol
            entry_price: Entry price
            parameters: Backtest parameters
            
        Returns:
            Tuple of (can_enter, quantity)
        """
        # Check if already have position in this symbol
        if symbol in self.positions:
            return False, 0
        
        # Get parameters
        max_pos_pct = parameters.get('max_position_pct', 0.08)
        max_risk = parameters.get('max_risk_per_trade', 0.005)
        stop_loss_pct = parameters.get('stop_loss_pct', 0.07)
        
        # Calculate position size
        max_position_value = self.current_equity * max_pos_pct
        max_qty_by_notional = int(max_position_value / entry_price)
        
        # Calculate risk-based quantity
        risk_amount = self.current_equity * max_risk
        risk_per_share = entry_price * stop_loss_pct
        max_qty_by_risk = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
        
        # Take minimum
        qty = min(max_qty_by_notional, max_qty_by_risk)
        
        if qty < 1:
            return False, 0
        
        return True, qty
    
    def enter_position(
        self,
        symbol: str,
        entry_date: datetime,
        entry_price: float,
        qty: int,
        parameters: Dict[str, Any]
    ) -> bool:
        """Enter a new position.
        
        Args:
            symbol: Stock symbol
            entry_date: Entry datetime
            entry_price: Entry price
            qty: Quantity to buy
            parameters: Backtest parameters
            
        Returns:
            True if position entered successfully
        """
        if symbol in self.positions:
            return False
        
        # Calculate exit levels
        stop_loss_pct = parameters.get('stop_loss_pct', 0.07)
        take_profit_pct = parameters.get('take_profit_pct', 0.15)
        max_hold_days = parameters.get('max_hold_days', 5)
        
        stop_loss_price = entry_price * (1 - stop_loss_pct)
        take_profit_price = entry_price * (1 + take_profit_pct)
        max_exit_date = entry_date + timedelta(days=max_hold_days)
        
        # Create position
        position = Position(
            symbol=symbol,
            entry_date=entry_date,
            entry_price=entry_price,
            qty=qty,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            max_exit_date=max_exit_date
        )
        
        self.positions[symbol] = position
        
        # Update equity (subtract cost)
        cost = entry_price * qty
        self.current_equity -= cost
        
        return True
    
    def check_exits(
        self,
        current_date: datetime,
        prices: Dict[str, float]
    ) -> List[BacktestTrade]:
        """Check all positions for exit conditions.
        
        Args:
            current_date: Current simulation date
            prices: Current prices for all symbols
            
        Returns:
            List of closed trades
        """
        closed_trades = []
        symbols_to_remove = []
        
        for symbol, position in self.positions.items():
            current_price = prices.get(symbol)
            
            if current_price is None:
                continue
            
            exit_reason = None
            
            # Check stop loss
            if current_price <= position.stop_loss_price:
                exit_reason = "stop_loss"
            
            # Check take profit
            elif current_price >= position.take_profit_price:
                exit_reason = "take_profit"
            
            # Check max hold time
            elif current_date >= position.max_exit_date:
                exit_reason = "max_hold"
            
            # Exit if triggered
            if exit_reason:
                trade = self._close_position(symbol, position, current_date, current_price, exit_reason)
                closed_trades.append(trade)
                symbols_to_remove.append(symbol)
        
        # Remove closed positions
        for symbol in symbols_to_remove:
            del self.positions[symbol]
        
        return closed_trades
    
    def _close_position(
        self,
        symbol: str,
        position: Position,
        exit_date: datetime,
        exit_price: float,
        exit_reason: str
    ) -> BacktestTrade:
        """Close a position and create trade record.
        
        Args:
            symbol: Stock symbol
            position: Position to close
            exit_date: Exit datetime
            exit_price: Exit price
            exit_reason: Reason for exit
            
        Returns:
            BacktestTrade record
        """
        # Calculate P&L
        entry_value = position.entry_price * position.qty
        exit_value = exit_price * position.qty
        pnl = exit_value - entry_value
        return_pct = (pnl / entry_value) * 100
        
        # Calculate hold days
        hold_days = (exit_date - position.entry_date).days
        
        # Update equity
        self.current_equity += exit_value
        
        # Create trade record
        trade = BacktestTrade(
            symbol=symbol,
            entry_date=position.entry_date,
            entry_price=position.entry_price,
            exit_date=exit_date,
            exit_price=exit_price,
            qty=position.qty,
            pnl=pnl,
            return_pct=return_pct,
            hold_days=hold_days,
            exit_reason=exit_reason
        )
        
        self.trades.append(trade)
        
        return trade
    
    def close_all_positions(
        self,
        exit_date: datetime,
        prices: Dict[str, float]
    ):
        """Force close all open positions (end of backtest).
        
        Args:
            exit_date: Exit datetime
            prices: Final prices for all symbols
        """
        symbols = list(self.positions.keys())
        
        for symbol in symbols:
            position = self.positions[symbol]
            price = prices.get(symbol, position.entry_price)
            
            self._close_position(symbol, position, exit_date, price, "manual")
        
        self.positions = {}
    
    def update_equity_curve(self, current_prices: Dict[str, float]):
        """Update equity curve with current mark-to-market value.
        
        Args:
            current_prices: Current prices for all symbols
        """
        # Calculate position values
        position_value = 0.0
        for symbol, position in self.positions.items():
            current_price = current_prices.get(symbol, position.entry_price)
            position_value += current_price * position.qty
        
        # Total equity = cash + positions
        total_equity = self.current_equity + position_value
        
        self.equity_curve.append(total_equity)
