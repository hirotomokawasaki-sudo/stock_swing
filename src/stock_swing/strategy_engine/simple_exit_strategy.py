"""Simple exit strategy for emergency position management.

This is a basic exit strategy to prevent runaway losses while a more
sophisticated exit system is developed.

Exit triggers:
1. Stop loss: Position down >7% from entry
2. Take profit: Position up >10% from entry
3. Time-based: Holding period >5 days

This is a temporary bridge until full exit strategy is implemented.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.base_strategy import BaseStrategy, CandidateSignal


class SimpleExitStrategy(BaseStrategy):
    """Simple exit strategy for basic position management.
    
    Emergency implementation: simple_exit_v1
    """
    
    strategy_id = "simple_exit_v1"
    
    def __init__(
        self,
        stop_loss_pct: float = -0.07,  # -7% stop loss
        take_profit_pct: float = 0.10,  # +10% take profit
        max_hold_days: int = 5,  # 5 days max hold
    ):
        """Initialize simple exit strategy.
        
        Args:
            stop_loss_pct: Stop loss threshold (negative value).
            take_profit_pct: Take profit threshold (positive value).
            max_hold_days: Maximum holding period in days.
        """
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_hold_days = max_hold_days
    
    def generate(
        self,
        features: list[FeatureResult],
        current_positions: dict[str, dict] | None = None,
    ) -> list[CandidateSignal]:
        """Generate exit signals for open positions.
        
        Args:
            features: List of computed features (for current prices).
            current_positions: Current positions from broker.
                Format: {symbol: {qty, avg_entry_price, current_price, unrealized_pl, ...}}
            
        Returns:
            List of sell signals for positions that meet exit criteria.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not current_positions:
            logger.warning("SimpleExit: No current_positions provided")
            return []
        
        logger.info(f"SimpleExit: Checking {len(current_positions)} positions")
        
        signals = []
        now = datetime.now(timezone.utc)
        
        # Get current prices from features
        price_map = {}
        for feature in features:
            if feature.feature_name == "price_momentum" and feature.symbol:
                latest_close = feature.values.get("latest_close")
                if latest_close:
                    price_map[feature.symbol] = float(latest_close)
        
        logger.info(f"SimpleExit: price_map has {len(price_map)} symbols")
        
        # Check each position for exit criteria
        for symbol, position_data in current_positions.items():
            qty = float(position_data.get("qty", 0))
            if qty <= 0:
                continue  # Skip short positions or zero qty
            
            avg_entry_price = float(position_data.get("avg_entry_price", 0))
            current_price = price_map.get(symbol) or float(position_data.get("current_price", 0))
            
            if avg_entry_price <= 0 or current_price <= 0:
                continue  # Skip if missing price data
            
            # Calculate return
            return_pct = (current_price - avg_entry_price) / avg_entry_price
            
            logger.info(f"SimpleExit: {symbol} return={return_pct:.4f} ({return_pct*100:.2f}%), stop_loss={self.stop_loss_pct:.4f}, take_profit={self.take_profit_pct:.4f}")
            
            # Check holding period
            hold_days = None
            created_at_str = position_data.get("created_at")
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    hold_duration = now - created_at
                    hold_days = hold_duration.days
                except (ValueError, AttributeError):
                    hold_days = None
            
            # Exit criteria
            exit_reason = None
            signal_strength = 0.0
            
            # 1. Stop loss
            if return_pct <= self.stop_loss_pct:
                exit_reason = f"Stop loss triggered: {return_pct:.2%} <= {self.stop_loss_pct:.2%}"
                signal_strength = 1.0  # High urgency
            
            # 2. Take profit
            elif return_pct >= self.take_profit_pct:
                exit_reason = f"Take profit triggered: {return_pct:.2%} >= {self.take_profit_pct:.2%}"
                signal_strength = 0.9
            
            # 3. Time-based exit
            elif hold_days is not None and hold_days >= self.max_hold_days:
                exit_reason = f"Max hold period reached: {hold_days} days >= {self.max_hold_days} days"
                signal_strength = 0.7
            
            # Generate sell signal if any exit criteria met
            if exit_reason:
                signal = CandidateSignal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    action="sell",
                    signal_strength=signal_strength,
                    generated_at=now,
                    time_horizon="immediate",
                    confidence=0.85,  # High confidence in rule-based exits
                    reasoning=exit_reason,
                    feature_refs=["position_tracking"],
                    metadata={
                        "return_pct": return_pct,
                        "hold_days": hold_days,
                        "avg_entry_price": avg_entry_price,
                        "current_price": current_price,
                        "qty": qty,
                        "exit_trigger": exit_reason.split(":")[0],
                    },
                )
                signals.append(signal)
        
        return signals
