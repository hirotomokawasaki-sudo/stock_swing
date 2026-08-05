"""Simple Exit V2 strategy with trailing stop and dynamic thresholds.

Improvements over V1:
1. Trailing stop: Lock in profits while allowing upside
2. Volatility-aware thresholds: ATR-based stop/take (future)
3. Partial exits: Scale out positions (future)

Current implementation: simple_exit_v2
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.pricing import PriceResolver
from stock_swing.strategy_engine.base_strategy import BaseStrategy, CandidateSignal

logger = logging.getLogger(__name__)


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
        staged_trailing_enabled: bool = False,
        staged_trailing_levels: list[dict[str, float]] | None = None,
        # G9: min_hold guard — prevent stop_loss from firing on early noise
        min_hold_days: int = 1,
        min_hold_days_enabled: bool = True,
        emergency_stop_bypass_pct: float = -0.12,  # bypass min_hold if loss >= -12%
        # Plan A: Tiered min_hold (2026-07-27)
        # Post-exit drift analysis showed avg_ret=-2.9% recovers within 15d (noise),
        # avg_ret=-8.2% never recovers (true stop). Tiered approach reduces false stops.
        tiered_min_hold_enabled: bool = False,
        tiered_min_hold_levels: list[dict[str, float]] | None = None,
        # Broker-reconstructed threshold graduation (改善点1 2026-07-16)
        # After holding >= broker_recon_graduation_days, unknown-strength positions
        # graduate from conservative -5% stop to the standard stop_loss_pct (-7%).
        broker_recon_graduation_days: int | None = 5,
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
            staged_trailing_enabled: Enable R3-B staged trailing levels.
            staged_trailing_levels: Ordered list of activation/pullback thresholds.
        """
        self.stop_loss_pct = stop_loss_pct
        self.breakeven_activation_pct = breakeven_activation_pct
        self.trailing_activation_pct = trailing_activation_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.max_hold_days = max_hold_days
        self.staged_trailing_enabled = staged_trailing_enabled
        self.staged_trailing_levels = sorted(
            staged_trailing_levels or [],
            key=lambda row: float(row.get("activation_pct", 0.0)),
        )
        # G9: min_hold guard
        self.min_hold_days = min_hold_days
        self.min_hold_days_enabled = min_hold_days_enabled
        self.emergency_stop_bypass_pct = emergency_stop_bypass_pct
        # Plan A / v2 (2026-08-05 redesign): tiered min_hold
        # v1 (disabled by FIX-007, 2026-07-29) used *absolute* return_pct thresholds
        # (e.g. "return > -5%"). That is unreachable whenever the effective stop
        # threshold itself is already <= -5% (standard -7% / high-conviction -9%
        # tiers), because the stop_loss branch only evaluates once
        # return_pct <= eff_stop_loss_pct. Only the -5% low-conviction tier could
        # ever reach the -5% noise band, so the 7-day tier was dead code for the
        # vast majority of positions.
        #
        # v2 fix: tiers are now defined as an *offset in percentage points from the
        # effective stop threshold that just fired* (offset_pct), not an absolute
        # return level. This makes the tiering meaningful regardless of conviction:
        #   offset_pct = (return_pct - eff_stop_loss_pct) * 100
        #   e.g. eff_stop=-7%, return=-7.5% → offset=-0.5pp (barely breached → noise)
        #        eff_stop=-7%, return=-15%  → offset=-8.0pp (deeply breached → severe)
        self.tiered_min_hold_enabled = tiered_min_hold_enabled
        # Sort levels descending by offset so the first match wins
        # e.g. [(-2.0, 7), (-5.0, 3)] → offset=-1pp → 7d, offset=-3pp → 3d, offset=-8pp → base
        self.tiered_min_hold_levels: list[tuple[float, int]] = sorted(
            [
                (float(lv["offset_pct"]), int(lv["min_hold_days"]))
                for lv in (tiered_min_hold_levels or [])
            ],
            key=lambda x: x[0],
            reverse=True,  # least-negative (closest to threshold) first
        )
        # Run-level suppression tracking (reset each paper_demo run)
        # Key: tier label ("noise_7d" / "mid_3d" / "severe_1d" / "legacy")
        self._suppression_counts: dict[str, int] = {}
        # broker_recon threshold graduation
        self.broker_recon_graduation_days = broker_recon_graduation_days

    def _effective_min_hold_days(
        self, return_pct: float, eff_stop_loss_pct: float | None = None
    ) -> int:
        """Return the effective min_hold_days for the given current return.

        Plan A v2 (2026-08-05 redesign): tiers based on *offset from the
        effective stop threshold that fired*, not an absolute return level.

        Rationale: post-exit drift analysis (48 true stop_loss trades) found
        that losses just past the stop threshold recover far more often than
        losses deeply past it, regardless of the exact threshold value used
        (which itself varies -5%/-7%/-9% by conviction tier). Using an
        absolute return_pct cutoff (v1 / Plan A original) made the 7-day tier
        unreachable for standard/high-conviction positions, since their stop
        only fires once return_pct is already <= -7%/-9% (FIX-007, 2026-07-29).

        Args:
            return_pct: current position return (negative for a loss).
            eff_stop_loss_pct: the effective (conviction-adjusted) stop-loss
                threshold that triggered this check. Defaults to the base
                stop_loss_pct if not provided (e.g. legacy callers/tests).

        Tiers (when tiered_min_hold_enabled=True), offset_pct = how many
        percentage points past the threshold the position has fallen:
          offset_pct > -2pp  → 7 days  (barely breached → likely noise)
          offset_pct > -5pp  → 3 days  (moderately breached → give it a few days)
          offset_pct <= -5pp → base min_hold_days (default 1, exit quickly)

        The emergency_stop_bypass_pct (-12%) is checked upstream and always takes
        priority over any min_hold value returned here.

        When tiered_min_hold_enabled=False, returns base self.min_hold_days (legacy).
        """
        if not self.tiered_min_hold_enabled or not self.tiered_min_hold_levels:
            return self.min_hold_days
        threshold = (
            eff_stop_loss_pct if eff_stop_loss_pct is not None else self.stop_loss_pct
        )
        offset_pct = (return_pct - threshold) * 100.0
        for offset_threshold_pct, hold_days in self.tiered_min_hold_levels:
            if offset_pct > offset_threshold_pct:
                return hold_days
        # Deeply breached: fall back to base min_hold_days (typically 1)
        return self.min_hold_days

    def _tier_label(self, return_pct: float, eff_min_hold: int) -> str:
        """Return a human-readable label for the tier that suppressed this stop."""
        if not self.tiered_min_hold_enabled:
            return "legacy"
        if eff_min_hold >= 7:
            return "noise_7d"
        if eff_min_hold >= 3:
            return "mid_3d"
        return "severe_1d"

    def get_suppression_stats(self) -> dict[str, int]:
        """Return run-level stop_loss suppression counts by tier (for console reporting).

        Returns dict like:
          {"noise_7d": 2, "mid_3d": 1, "total": 3}
        Reset by calling reset_suppression_stats().
        """
        total = sum(self._suppression_counts.values())
        return {**self._suppression_counts, "total": total}

    def reset_suppression_stats(self) -> None:
        """Clear run-level suppression counters (call at start of each paper_demo run)."""
        self._suppression_counts.clear()

    def _resolve_thresholds(
        self,
        entry_signal_strength: float | None,
        hold_days: float | None = None,
    ) -> tuple[float, float]:
        """Return (stop_loss_pct, trailing_activation_pct) adjusted for signal strength.

        Missing or invalid strength is treated as LOW conviction (-5% stop, +10% trailing)
        because broker-reconstructed positions have no signal provenance.

        Graduation rule (2026-07-16): if entry_signal_strength is None (broker_reconstructed)
        but hold_days >= broker_recon_graduation_days, the position has demonstrated
        stability and graduates to standard thresholds (-7% stop, +8% trailing).
        """
        if entry_signal_strength is None:
            # Check graduation: long-held broker_reconstructed positions → standard thresholds
            if (
                self.broker_recon_graduation_days is not None
                and hold_days is not None
                and hold_days >= self.broker_recon_graduation_days
            ):
                logger.debug(
                    "broker_recon graduation: hold_days=%.1f >= %dd → standard thresholds",
                    hold_days,
                    self.broker_recon_graduation_days,
                )
                return self.stop_loss_pct, self.trailing_activation_pct
            # Unknown conviction within graduation window: conservative/low thresholds
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

    def _resolve_trailing_rule(
        self,
        peak_return_pct: float,
        eff_trailing_activation_pct: float,
    ) -> tuple[bool, float, float, dict[str, Any] | None]:
        """Return active status, activation pct, stop pct, and optional staged level."""
        if not self.staged_trailing_enabled or not self.staged_trailing_levels:
            return (
                peak_return_pct >= eff_trailing_activation_pct,
                eff_trailing_activation_pct,
                self.trailing_stop_pct,
                None,
            )

        active_level: dict[str, Any] | None = None
        for level in self.staged_trailing_levels:
            activation_pct = float(level.get("activation_pct", 0.0))
            if peak_return_pct >= activation_pct:
                active_level = level

        if active_level is None:
            first_activation = float(self.staged_trailing_levels[0].get("activation_pct", eff_trailing_activation_pct))
            return False, first_activation, self.trailing_stop_pct, None

        return (
            True,
            float(active_level.get("activation_pct", eff_trailing_activation_pct)),
            float(active_level.get("trailing_stop_pct", self.trailing_stop_pct)),
            active_level,
        )
    
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
        resolver = PriceResolver()
        
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
            
            position_current_price = float(position_data.get("current_price", 0))
            feature_price = price_map.get(symbol)
            exit_resolution = resolver.resolve_exit_price(
                symbol,
                position_current_price=position_current_price,
                feature_price=feature_price,
            )
            current_price = exit_resolution.price
            price_source = exit_resolution.source
            if exit_resolution.warnings:
                for w in exit_resolution.warnings:
                    logger.warning(f"SimpleExitV2: {symbol}: {w}")
            
            if avg_entry_price <= 0 or current_price <= 0:
                continue  # Skip if missing price data

            # --- Entry-price split guard --------------------------------
            # If avg_entry_price is more than 3x the current_price the entry
            # is almost certainly a PRE-SPLIT price that has not yet been
            # corrected by reconcile_split_adjusted_positions.
            # Acting on it would produce a massive negative return_pct and
            # fire the stop-loss immediately.
            # Suppress exit evaluation for this position and log a warning
            # so the operator knows to run a rebuild / reconcile.
            if avg_entry_price > current_price * 3.0:
                logger.warning(
                    f"SimpleExitV2: SKIPPING {symbol} — avg_entry_price "
                    f"${avg_entry_price:.2f} is {avg_entry_price / current_price:.1f}x "
                    f"current_price ${current_price:.2f}. "
                    f"Likely pre-split entry; reconcile will correct. "
                    f"No exit signal generated."
                )
                continue

            # Calculate current return
            return_pct = (current_price - avg_entry_price) / avg_entry_price

            # Get or estimate peak price
            peak_price = float(position_data.get("peak_price", current_price))

            # --- Anomaly guard for peak_price ---
            # If peak_price is >2.5x the entry price AND >2.5x the current price, it is almost
            # certainly a split-related feed glitch (e.g. Alpaca paper returning 10x prices).
            # Reset to max(entry, current) to prevent an immediate spurious trailing-stop exit.
            if avg_entry_price > 0 and peak_price > avg_entry_price * 2.5 and peak_price > current_price * 2.5:
                logger.warning(
                    f"SimpleExitV2: ANOMALOUS peak_price detected for {symbol}: "
                    f"${peak_price:.2f} vs entry=${avg_entry_price:.2f} current=${current_price:.2f} "
                    f"(ratio {peak_price / avg_entry_price:.1f}x entry) — "
                    f"resetting to max(entry, current) to suppress spurious trailing stop"
                )
                peak_price = max(avg_entry_price, current_price)

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
                entry_signal_strength, hold_days=hold_days
            )

            logger.debug(
                "exit_check symbol=%s return_pct=%s peak_return=%s hold_days=%s "
                "stop_threshold=%s breakeven_active=%s trail_active=%s",
                symbol,
                f"{return_pct:.4f}" if return_pct is not None else "None",
                f"{peak_return_pct:.4f}" if peak_return_pct is not None else "None",
                hold_days,
                eff_stop_loss_pct,
                return_pct is not None
                and peak_return_pct is not None
                and peak_return_pct >= self.breakeven_activation_pct,
                return_pct is not None
                and peak_return_pct is not None
                and self._resolve_trailing_rule(peak_return_pct, eff_trailing_activation_pct)[0],
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
            trailing_active, active_trailing_activation_pct, active_trailing_stop_pct, staged_level = (
                self._resolve_trailing_rule(peak_return_pct, eff_trailing_activation_pct)
            )

            # 1. Trailing stop (highest priority once activated)
            if trailing_active:
                trailing_stop_price = peak_price * (1 - active_trailing_stop_pct)
                pullback_from_peak_pct = (peak_price - current_price) / peak_price
                if current_price <= trailing_stop_price:
                    trigger_label = "Staged trailing stop" if staged_level is not None else "Trailing stop"
                    stage_text = (
                        f", stage activation={active_trailing_activation_pct:.0%}, "
                        f"stage stop={active_trailing_stop_pct:.1%}"
                        if staged_level is not None
                        else ""
                    )
                    exit_reason = (
                        f"{trigger_label} triggered: price ${current_price:.2f} "
                        f"<= ${trailing_stop_price:.2f} "
                        f"(peak ${peak_price:.2f}, {pullback_from_peak_pct:.2%} pullback"
                        f"{stage_text})"
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
                # G9 / Plan A: min_hold guard — suppress early noise cuts
                # Plan A uses tiered min_hold based on loss magnitude:
                #   return > -5% → 7d wait (noise zone)
                #   return > -8% → 3d wait (borderline zone)
                #   return <= -8% → base min_hold (1d, exit quickly)
                eff_min_hold = self._effective_min_hold_days(
                    return_pct, eff_stop_loss_pct=eff_stop_loss_pct
                )
                _suppress = False
                if (
                    self.min_hold_days_enabled
                    and hold_days is not None
                    and hold_days < eff_min_hold
                    and return_pct > self.emergency_stop_bypass_pct
                ):
                    # Within min-hold window AND not an emergency loss → suppress
                    logger.info(
                        "stop_loss suppressed by min_hold: %s return=%.2f%% hold=%.1fd "
                        "< min=%dd (tiered=%s emergency cap=%.0f%% not breached)",
                        symbol, return_pct * 100, hold_days,
                        eff_min_hold, self.tiered_min_hold_enabled,
                        self.emergency_stop_bypass_pct * 100,
                    )
                    # Track suppression by tier for console reporting
                    tier_key = self._tier_label(return_pct, eff_min_hold)
                    self._suppression_counts[tier_key] = (
                        self._suppression_counts.get(tier_key, 0) + 1
                    )
                    _suppress = True
                elif (
                    self.min_hold_days_enabled
                    and hold_days is not None
                    and hold_days < eff_min_hold
                    and return_pct <= self.emergency_stop_bypass_pct
                ):
                    # Emergency bypass: loss breaches hard cap → exit immediately
                    exit_reason = (
                        f"Emergency stop triggered (min_hold bypass): "
                        f"{return_pct:.2%} <= {self.emergency_stop_bypass_pct:.2%} "
                        f"(hold {hold_days:.1f}d < min {eff_min_hold}d)"
                    )
                    signal_strength = 1.0

                if not _suppress and exit_reason is None:
                    exit_reason = (
                        f"Stop loss triggered: {return_pct:.2%} <= {eff_stop_loss_pct:.2%}"
                        + (f" (strength-adjusted from {self.stop_loss_pct:.0%})"
                           if eff_stop_loss_pct != self.stop_loss_pct else "")
                        + (f" (hold {hold_days:.1f}d >= min {eff_min_hold}d"
                           + (" tiered" if self.tiered_min_hold_enabled else "")
                           + ")"
                           if self.min_hold_days_enabled and hold_days is not None else "")
                    )
                    signal_strength = 1.0

            # 4. Time-based exit
            if exit_reason is None and hold_days is not None and hold_days >= self.max_hold_days:
                exit_reason = f"Max hold period reached: {hold_days} days >= {self.max_hold_days} days"
                signal_strength = 0.7
            
            # Generate sell signal if any exit criteria met
            if exit_reason:
                import logging as _logging

                _logging.getLogger(__name__).info(
                    "exit_signal_fired symbol=%s exit_reason=%s return_pct=%.4f peak_return=%.4f "
                    "stop_loss_threshold=%.4f",
                    symbol,
                    exit_reason.split(":")[0].strip(),
                    return_pct if return_pct is not None else float("nan"),
                    peak_return_pct if peak_return_pct is not None else float("nan"),
                    eff_stop_loss_pct,
                )
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
                        "trailing_active": trailing_active,
                        "staged_trailing_enabled": self.staged_trailing_enabled,
                        "staged_trailing_level": staged_level,
                        "active_trailing_activation_pct": active_trailing_activation_pct,
                        "active_trailing_stop_pct": active_trailing_stop_pct,
                        "breakeven_active": (
                            peak_return_pct >= self.breakeven_activation_pct
                            and not trailing_active
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
