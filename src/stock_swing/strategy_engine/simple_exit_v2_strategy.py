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
    """Simple exit strategy V2 with trailing stop and breakeven protection.
    
    Exit rules (evaluated in priority order):
    1. Trailing stop  – once peak_return >= trailing_activation_pct,
       exit if price drops trailing_stop_pct from peak.
    2. Breakeven stop – once return_pct >= breakeven_activation_pct (but
       not yet in trailing mode), exit immediately if return falls to 0%.
    3. Initial stop loss – exit if return_pct <= stop_loss_pct.
    4. Time-based exit  – exit after max_hold_days.
    """
    
    strategy_id = "simple_exit_v2"
    
    # Signal-strength tiers for dynamic threshold adjustment
    # High conviction (strength >= HIGH_THRESHOLD): more room to breathe
    # Low conviction  (strength <  LOW_THRESHOLD):  tighter early exit
    HIGH_STRENGTH_THRESHOLD: float = 0.85
    LOW_STRENGTH_THRESHOLD:  float = 0.65

    def __init__(
        self,
        stop_loss_pct: float = -0.07,          # -7% hard stop (standard)
        breakeven_activation_pct: float = 0.03, # +3% → protect entry price
        trailing_activation_pct: float = 0.08,  # +8% → activate trailing
        trailing_stop_pct: float = 0.04,         # 4% pullback from peak
        max_hold_days: int = 20,
    ):
        """Initialize simple exit V2 strategy.

        Per-position exit thresholds are adjusted dynamically at runtime
        based on the position’s ``entry_signal_strength``:

        +-----------------+------------+-------------------+
        | Strength tier   | stop_loss  | trailing_activation|
        +-----------------+------------+-------------------+
        | High (>=0.85)   | -9%        | +6%               |
        | Standard        | -7%        | +8%               |
        | Low  (< 0.65)   | -5%        | +10%              |
        +-----------------+------------+-------------------+

        Args:
            stop_loss_pct: Baseline hard stop loss threshold (negative value).
            breakeven_activation_pct: Once peak return reaches this level, move
                effective floor to breakeven (0%). Must be < trailing_activation_pct.
            trailing_activation_pct: Baseline return level at which trailing activates.
            trailing_stop_pct: Pullback from peak price that triggers trailing exit.
            max_hold_days: Maximum holding period in calendar days.
        """
        self.stop_loss_pct = stop_loss_pct
        self.breakeven_activation_pct = breakeven_activation_pct
        self.trailing_activation_pct = trailing_activation_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.max_hold_days = max_hold_days

    def _resolve_thresholds(
        self, entry_signal_strength: float | None
    ) -> tuple[float, float]:
        """Return (stop_loss_pct, trailing_activation_pct) adjusted for signal strength.

        Missing or invalid strength is treated as LOW conviction (-5% stop, +10% trailing)
        because broker-reconstructed positions have no signal provenance.
        """
        if entry_signal_strength is None:
            # Unknown conviction: use conservative/low thresholds to protect capital
            return -0.05, 0.10
        try:
            s = float(entry_signal_strength)
        except (TypeError, ValueError):
            return -0.05, 0.10
        if s >= self.HIGH_STRENGTH_THRESHOLD:
            # High conviction: wider stop, earlier trailing activation
            return -0.09, 0.06
        if s < self.LOW_STRENGTH_THRESHOLD:
            # Low conviction: tighter stop, later trailing activation
            return -0.05, 0.10
        # Standard
        return self.stop_loss_pct, self.trailing_activation_pct
    
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
            created_at_str = position_data.get("created_at") or position_data.get("entry_time")
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    hold_duration = now - created_at
                    hold_days = hold_duration.days
                except (ValueError, AttributeError):
                    hold_days = None
            
            # Resolve dynamic thresholds from entry signal strength
            entry_signal_strength = position_data.get("entry_signal_strength")
            eff_stop_loss_pct, eff_trailing_activation_pct = self._resolve_thresholds(
                entry_signal_strength
            )

            logger.info(
                f"SimpleExitV2: {symbol} "
                f"entry_strength={entry_signal_strength} "
                f"eff_stop={eff_stop_loss_pct:.0%} "
                f"eff_trailing_act={eff_trailing_activation_pct:.0%}"
            )

            # Exit criteria (evaluated in priority order)
            exit_reason = None
            signal_strength = 0.0

            # 1. Trailing stop (highest priority once activated)
            if peak_return_pct >= eff_trailing_activation_pct:
                trailing_stop_price = peak_price * (1 - self.trailing_stop_pct)
                pullback_from_peak_pct = (peak_price - current_price) / peak_price
                if current_price <= trailing_stop_price:
                    exit_reason = (
                        f"Trailing stop triggered: price ${current_price:.2f} "
                        f"<= ${trailing_stop_price:.2f} "
                        f"(peak ${peak_price:.2f}, {pullback_from_peak_pct:.2%} pullback)"
                    )
                    signal_strength = 0.95

            # 2. Breakeven stop (protect profits once PEAK return >= breakeven_activation_pct)
            elif peak_return_pct >= self.breakeven_activation_pct:
                # Peak ever reached the activation threshold — never let it
                # turn into a loss.  Exit as soon as current return falls to or below 0%.
                if return_pct <= 0.0:
                    exit_reason = (
                        f"Breakeven stop triggered: return {return_pct:.2%} <= 0% "
                        f"(had reached breakeven_activation={self.breakeven_activation_pct:.0%})"
                    )
                    signal_strength = 0.95
                # else: still in profit but not yet at trailing level → hold

            # 3. Initial stop loss (position never reached breakeven zone)
            elif return_pct <= eff_stop_loss_pct:
                exit_reason = (
                    f"Stop loss triggered: {return_pct:.2%} <= {eff_stop_loss_pct:.2%}"
                    + (f" (strength-adjusted from {self.stop_loss_pct:.0%})"
                       if eff_stop_loss_pct != self.stop_loss_pct else "")
                )
                signal_strength = 1.0

            # 4. Time-based exit
            if exit_reason is None and hold_days is not None and hold_days >= self.max_hold_days:
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
                    confidence=0.90,
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
                        "trailing_active": peak_return_pct >= eff_trailing_activation_pct,
                        "breakeven_active": (
                            peak_return_pct >= self.breakeven_activation_pct
                            and peak_return_pct < eff_trailing_activation_pct
                        ),
                        "entry_signal_strength": entry_signal_strength,
                        "eff_stop_loss_pct": eff_stop_loss_pct,
                        "eff_trailing_activation_pct": eff_trailing_activation_pct,
                        "price_source": price_source,
                        "stale_data_skipped": symbol in stale_symbols,
                    },
                )
                signals.append(signal)
        
        return signals
