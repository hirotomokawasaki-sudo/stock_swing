"""Simple Exit V2 strategy with trailing stop and dynamic thresholds.

Improvements over V1:
1. Trailing stop: Lock in profits while allowing upside
2. Volatility-aware thresholds: ATR-based stop/take (future)
3. Partial exits: Scale out positions (future)

Current implementation: simple_exit_v2
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.base_strategy import BaseStrategy, CandidateSignal


class SimpleExitV2Strategy(BaseStrategy):
    """Simple exit strategy V2 with trailing stop.
    
    New features:
    - Trailing stop after profit threshold
    - Dynamic exit based on price movement
    """
    
    strategy_id = "simple_exit_v2"
    
    def __init__(
        self,
        stop_loss_pct: float = -0.07,  # -7% initial stop loss
        trailing_activation_pct: float = 0.05,  # 5% profit to activate trailing
        trailing_stop_pct: float = 0.03,  # 3% pullback from peak to exit
        max_hold_days: int = 20,  # 20 days to allow strong momentum trades to develop
    ):
        """Initialize simple exit V2 strategy.
        
        Args:
            stop_loss_pct: Initial stop loss threshold (negative value).
            trailing_activation_pct: Profit threshold to activate trailing stop.
            trailing_stop_pct: Pullback percentage from peak to trigger exit.
            max_hold_days: Maximum holding period in days.
        """
        self.stop_loss_pct = stop_loss_pct
        self.trailing_activation_pct = trailing_activation_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.max_hold_days = max_hold_days
    
    def generate(
        self,
        features: list[FeatureResult],
        current_positions: dict[str, dict] | None = None,
    ) -> list[CandidateSignal]:
        """Generate exit signals for open positions with trailing stop logic.
        
        Args:
            features: List of computed features (for current prices).
            current_positions: Current positions from broker.
                Format: {symbol: {qty, avg_entry_price, current_price, unrealized_pl, 
                                  peak_price (optional), ...}}
            
        Returns:
            List of sell signals for positions that meet exit criteria.
        """
        import logging
        import json
        from pathlib import Path
        logger = logging.getLogger(__name__)
        
        if not current_positions:
            logger.warning("SimpleExitV2: No current_positions provided")
            return []
        
        # Load price overrides to fix stale broker prices
        price_overrides = {}
        try:
            override_path = Path(__file__).parent.parent.parent.parent / "data" / "price_overrides.json"
            if override_path.exists():
                override_data = json.loads(override_path.read_text())
                price_overrides = override_data.get("overrides", {})
                if price_overrides:
                    logger.info(f"SimpleExitV2: Loaded {len(price_overrides)} price overrides")
        except Exception as e:
            logger.warning(f"SimpleExitV2: Failed to load price overrides: {e}")
        
        # Apply price overrides to current_positions
        overrides_applied = 0
        for symbol in current_positions:
            if symbol in price_overrides:
                fresh_price = float(price_overrides[symbol]["fresh_price"])
                old_price = float(current_positions[symbol].get("current_price") or 0)
                current_positions[symbol]["current_price"] = fresh_price
                overrides_applied += 1
                logger.info(
                    f"SimpleExitV2: Applied price override for {symbol}: "
                    f"${old_price:.2f} → ${fresh_price:.2f}"
                )
        
        if overrides_applied > 0:
            logger.info(f"SimpleExitV2: Applied {overrides_applied} price overrides")
        
        logger.info(f"SimpleExitV2: Checking {len(current_positions)} positions")
        
        signals = []
        now = datetime.now(timezone.utc)
        
        # Get current prices from features (excluding stale data)
        price_map = {}
        stale_symbols = set()
        for feature in features:
            if feature.feature_name == "price_momentum" and feature.symbol:
                # Skip stale data (>7 days old)
                if "stale_data" in feature.quality_flags:
                    stale_symbols.add(feature.symbol)
                    data_age = feature.values.get("data_age_days", "unknown")
                    logger.warning(
                        f"Skipping stale price data for {feature.symbol} "
                        f"(age: {data_age} days)"
                    )
                    continue
                
                latest_close = feature.values.get("latest_close")
                if latest_close:
                    price_map[feature.symbol] = float(latest_close)
        
        logger.info(f"SimpleExitV2: price_map has {len(price_map)} symbols")
        
        # Check each position for exit criteria
        for symbol, position_data in current_positions.items():
            qty = float(position_data.get("qty", 0))
            if qty <= 0:
                continue  # Skip short positions or zero qty
            
            avg_entry_price = float(position_data.get("avg_entry_price", 0))
            
            # Price fallback priority:
            # 1. Position current_price (fresh from broker)
            # 2. Feature price_map (only if not stale)
            # This prevents using stale historical bars when fresh position data exists.
            position_current_price = float(position_data.get("current_price", 0))
            feature_price = price_map.get(symbol)
            
            if position_current_price > 0:
                current_price = position_current_price
                price_source = "position"
            elif feature_price:
                current_price = feature_price
                price_source = "feature"
            else:
                current_price = 0
                price_source = "none"
            
            if avg_entry_price <= 0 or current_price <= 0:
                continue  # Skip if missing price data
            
            # Calculate current return
            return_pct = (current_price - avg_entry_price) / avg_entry_price
            
            # Get or estimate peak price
            peak_price = float(position_data.get("peak_price", current_price))
            peak_return_pct = (peak_price - avg_entry_price) / avg_entry_price
            
            # Update peak if current price is higher
            if current_price > peak_price:
                peak_price = current_price
                peak_return_pct = return_pct
            
            logger.info(
                f"SimpleExitV2: {symbol} return={return_pct:.4f} ({return_pct*100:.2f}%), "
                f"peak_return={peak_return_pct:.4f}, "
                f"trailing_active={peak_return_pct >= self.trailing_activation_pct}, "
                f"price_source={price_source}, "
                f"current=${current_price:.2f}, entry=${avg_entry_price:.2f}"
            )
            
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
            
            # 1. Trailing stop (if activated)
            if peak_return_pct >= self.trailing_activation_pct:
                # Trailing stop is active
                trailing_stop_price = peak_price * (1 - self.trailing_stop_pct)
                pullback_from_peak_pct = (peak_price - current_price) / peak_price
                
                if current_price <= trailing_stop_price:
                    exit_reason = (
                        f"Trailing stop triggered: price ${current_price:.2f} "
                        f"<= ${trailing_stop_price:.2f} "
                        f"(peak ${peak_price:.2f}, {pullback_from_peak_pct:.2%} pullback)"
                    )
                    signal_strength = 0.95  # High priority
            
            # 2. Initial stop loss (if not in trailing mode)
            elif return_pct <= self.stop_loss_pct:
                exit_reason = f"Stop loss triggered: {return_pct:.2%} <= {self.stop_loss_pct:.2%}"
                signal_strength = 1.0  # Highest urgency
            
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
                    confidence=0.90,  # High confidence in rule-based exits with trailing
                    reasoning=exit_reason,
                    feature_refs=["position_tracking"],
                    metadata={
                        "return_pct": return_pct,
                        "peak_return_pct": peak_return_pct,
                        "hold_days": hold_days,
                        "avg_entry_price": avg_entry_price,
                        "current_price": current_price,
                        "peak_price": peak_price,
                        "qty": qty,
                        "exit_trigger": exit_reason.split(":")[0].strip(),
                        "trailing_active": peak_return_pct >= self.trailing_activation_pct,
                        "price_source": price_source,
                        "stale_data_skipped": symbol in stale_symbols,
                    },
                )
                signals.append(signal)
        
        return signals
