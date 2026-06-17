# stock_swing — System Analysis Export
**Generated:** 2026-05-28  
**Purpose:** External AI analysis reference  
**Status:** Paper trading, live on Alpaca Paper API

---

## 1. Mission & Design Philosophy

### Core Mission
Systematic trading infrastructure for U.S. stocks and ETFs using event-driven swing trading.

### Design Principles (from SYSTEM_OVERVIEW.md)
- LLMs assist interpretation and workflows — they are NOT the source of trading truth
- Market execution requires deterministic controls
- Source data must be separated from derived decisions
- Risk vetoes must be stronger than signal enthusiasm
- Runtime mode must constrain behavior at all times
- Safety model is DENY-FIRST: a strategy candidate must survive data completeness, freshness, risk, runtime mode, and execution policy checks

### Audit Model
For every meaningful decision, the system can reconstruct:
- Which raw data was used
- How it was normalized
- Which features were computed
- Which strategy produced the candidate
- Which risk checks passed or failed
- What order was submitted and what the broker returned

## 2. Architecture

### Data Flow
External Sources (Alpaca/Finnhub/FRED/SEC)
    ↓
Raw Ingestion (source-specific raw storage)
    ↓
Normalization (canonical schema)
    ↓
Feature Computation
    ↓
Strategy Signal Generation
    ↓
Risk Validation (deny-first)
    ↓
Decision Engine
    ↓
Execution / Reconciliation
    ↓
PnL Tracker / Audit Log
    ↓
Console (HTTP :3335 / WebSocket :3334) + Telegram

### Module Structure
```text
src/stock_swing/
├── feature_engine/         # Feature computation (momentum, macro regime, etc.)
├── strategy_engine/        # Entry & exit strategy logic
├── decision_engine/        # Risk validation + final decision generation
├── execution/              # Order submission, paper_executor, reconciler
├── tracking/               # PnL tracker (state persistence in JSON)
├── safety/                 # Audit logger, kill switch
├── reporting/              # Daily reports, snapshots
├── sources/                # Broker client (Alpaca), data fetchers
└── cli/                    # paper_demo (main orchestrator), reconcile_orders, etc.

console/
├── app.py                  # HTTP server (BaseHTTPRequestHandler, port 3335)
├── websocket_server.py     # WebSocket server (port 3334)
└── services/
    └── dashboard_service.py # All API handlers (~3400 lines)

scripts/
├── rebuild_pnl_state_from_broker.py  # Full state rebuild from broker fills
├── verify_rebuild_integrity.py       # Post-rebuild integrity checker (auto-fix)
├── audit_trades_with_market_data.py  # Weekly integrity audit
└── reconcile_orders.py               # Entry point for CLI reconciliation
```

### Cron Jobs (OpenClaw Gateway)
| Job | Schedule (JST) | Purpose |
|-----|---------------|---------|
| paper_demo_premarket | 23:00 weekdays | Pre-market decisions |
| paper_demo_market_open | 23:05 weekdays | Market open execution |
| paper_demo_midday | 02:00 Tue-Sat | Mid-session check |
| paper_demo_market_close | 05:55 Tue-Sat | Close decisions |
| stock_swing_order_reconciliation_market_hours | */30 20-23,0-6 | Fill detection |
| stock_swing_news_collection | */4h | Finnhub news collection |
| stock_swing_update_price_overrides | 22:00 daily | Fresh price override |
| stock_swing_weekly_full_audit | Mon 07:00 | Weekly integrity audit |
| daily_report_morning | 09:00 weekdays | Telegram daily report |

## 3. Entry Strategy

### 3.1 Entry: BreakoutMomentumStrategy (breakout_momentum_v1)

Key design choices:
- Signal: price momentum >= 5% over 5-day period with bullish trend
- Signal strength: linear scale (5%=0.5, 10%=1.0), adjusted by macro regime
- Minimum signal strength threshold: 0.65
- Macro regime modifiers: expansion ×1.1, high_volatility ×0.9, recession ×0.7

```python
"""Breakout/momentum strategy (breakout_momentum_v1).

This strategy generates buy signals when price momentum exceeds thresholds,
indicating potential breakout conditions.

Strategy logic:
1. Check price momentum
2. If momentum exceeds threshold and trend is bullish → buy signal
3. Signal strength based on momentum magnitude
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.base_strategy import BaseStrategy, CandidateSignal


class BreakoutMomentumStrategy(BaseStrategy):
    """Breakout/momentum trading strategy.
    
    Approved strategy: breakout_momentum_v1
    See STRATEGY_SCOPE.md for details.
    """
    
    strategy_id = "breakout_momentum_v1"
    
    def __init__(
        self,
        min_momentum: float = 0.05,  # 5% minimum momentum
        min_signal_strength: float = 0.65,
    ):
        """Initialize breakout momentum strategy.
        
        Args:
            min_momentum: Minimum momentum threshold for breakout.
            min_signal_strength: Minimum signal strength threshold.
        """
        self.min_momentum = min_momentum
        self.min_signal_strength = min_signal_strength
    
    def generate(
        self,
        features: list[FeatureResult],
    ) -> list[CandidateSignal]:
        """Generate candidate signals from features.
        
        Args:
            features: List of computed features.
            
        Returns:
            List of candidate signals (one per qualifying symbol).
        """
        # Filter to momentum features
        momentum_features = [
            f for f in features 
            if f.feature_name == "price_momentum" and f.symbol
        ]
        
        # Get macro regime if available
        macro_features = [
            f for f in features 
            if f.feature_name == "macro_regime"
        ]
        macro_regime = None
        if macro_features:
            macro_regime = macro_features[0].values.get("regime")
        
        # Generate signals
        signals = []
        now = datetime.now(timezone.utc)
        
        for momentum_feature in momentum_features:
            symbol = momentum_feature.symbol
            momentum = momentum_feature.values.get("momentum", 0.0)
            trend = momentum_feature.values.get("trend", "unknown")
            bars_used = momentum_feature.values.get("bars_used", 0)
            
            # Strategy logic: strong bullish momentum = breakout
            if momentum >= self.min_momentum and trend == "bullish":
                # Calculate signal strength
                signal_strength = self._calculate_signal_strength(
                    momentum=momentum,
                    macro_regime=macro_regime,
                )
                
                if signal_strength >= self.min_signal_strength:
                    # Generate candidate signal
                    signal = CandidateSignal(
                        strategy_id=self.strategy_id,
                        symbol=symbol,
                        action="buy",
                        signal_strength=signal_strength,
                        generated_at=now,
                        time_horizon="2d",
                        confidence=signal_strength * 0.85,  # Conservative
                        reasoning=f"Strong bullish momentum ({momentum:.2%}) indicates breakout",
                        feature_refs=[momentum_feature.feature_name],
                        metadata={
                            "momentum": momentum,
                            "trend": trend,
                            "bars_used": bars_used,
                            "macro_regime": macro_regime,
                            "risk_per_share": momentum_feature.values.get("risk_per_share"),
                            "stop_price": momentum_feature.values.get("stop_price"),
                            "latest_close": momentum_feature.values.get("latest_close"),
                            "atr": momentum_feature.values.get("atr"),
                        },
                    )
                    signals.append(signal)
        
        return signals
    
    def _calculate_signal_strength(
        self,
        momentum: float,
        macro_regime: str | None,
    ) -> float:
        """Calculate signal strength from inputs.
        
        Args:
            momentum: Price momentum value.
            macro_regime: Current macro regime.
            
        Returns:
            Signal strength [0.0, 1.0].
        """
        # Base strength from momentum magnitude
        # Linear scaling: 5% momentum = 0.5, 10% momentum = 1.0
        strength = min(momentum / 0.10, 1.0)
        
        # Adjust for macro regime
        if macro_regime == "expansion":
            strength *= 1.1
        elif macro_regime == "high_volatility":
            strength *= 0.9
        elif macro_regime == "recession":
            strength *= 0.7
        
        return min(strength, 1.0)
```

## 4. Exit Strategy

### 4.1 Exit: SimpleExitV2Strategy (simple_exit_v2)

Key design choices (implemented 2026-05-27):
- Priority order: trailing_stop > breakeven_stop > hard_stop_loss > time_based
- peak_price persisted across sessions (in pnl_state.json)
- Dynamic thresholds by entry signal strength:

| Strength tier    | stop_loss | trailing_activation |
|-----------------|-----------|---------------------|
| High (>=0.85)   | -9%       | +6%                 |
| Standard        | -7%       | +8%                 |
| Low (<0.65)     | -5%       | +10%                |

- exit_reason tracked in pending_exit_reasons.json for cross-session persistence

```python
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
        """Return (stop_loss_pct, trailing_activation_pct) adjusted for signal strength."""
        if entry_signal_strength is None:
            return self.stop_loss_pct, self.trailing_activation_pct
        s = float(entry_signal_strength)
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
```

## 5. Feature Engine

### 5.1 PriceMomentumFeature

Key design choices:
- 5-day lookback by default
- ATR computed from OHLC bars (true range average)
- Stale data detection: flags bars older than 7 days as "stale_data" quality flag
- Consumers must check quality_flags before using data

```python
"""Price momentum feature for measuring recent price strength.

This feature computes momentum indicators from price bar data.
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import BaseFeature, FeatureResult


class PriceMomentumFeature(BaseFeature):
    """Price momentum feature.
    
    Computes momentum indicators from price bars:
    - Simple returns over configurable periods
    - Trend direction
    """
    
    def __init__(self, period_days: int = 5):
        """Initialize price momentum feature.
        
        Args:
            period_days: Lookback period for momentum calculation.
        """
        self.period_days = period_days
    
    def compute(self, records: list[CanonicalRecord]) -> list[FeatureResult]:
        """Compute price momentum for symbols.
        
        Args:
            records: Canonical records (price bars).
            
        Returns:
            List of FeatureResult (one per symbol).
            
        Note:
            Stale data detection: Bars older than 7 days are flagged.
            Consumers should check quality_flags for "stale_data".
        """
        import logging
        from datetime import timedelta
        
        logger = logging.getLogger(__name__)
        
        # Filter to price records
        price_records = [
            r for r in records 
            if r.source_type == "price" and "bar_" in r.event_type
        ]
        
        if not price_records:
            return []
        
        # Group by symbol
        symbols = {}
        for record in price_records:
            if record.symbol:
                if record.symbol not in symbols:
                    symbols[record.symbol] = []
                symbols[record.symbol].append(record)
        
        # Compute momentum per symbol
        results = []
        now = datetime.now(timezone.utc)
        
        for symbol, symbol_records in symbols.items():
            # Sort by time
            sorted_records = sorted(symbol_records, key=lambda r: r.event_time)
            
            if len(sorted_records) < 2:
                # Insufficient data
                result = FeatureResult(
                    feature_name="price_momentum",
                    symbol=symbol,
                    computed_at=now,
                    values={
                        "momentum": 0.0,
                        "trend": "unknown",
                    },
                    metadata={},
                    quality_flags=["insufficient_bars"],
                )
                results.append(result)
                continue
            
            # Simple momentum: (latest_close - earliest_close) / earliest_close
            earliest_close = sorted_records[0].payload.get("close")
            latest_close = sorted_records[-1].payload.get("close")
            latest_bar_time = sorted_records[-1].event_time
            
            # Stale data detection: warn if latest bar is >7 days old
            data_age_days = (now - latest_bar_time).days
            is_stale = data_age_days > 7
            
            if is_stale:
                logger.warning(
                    f"STALE DATA: {symbol} latest bar is {data_age_days} days old "
                    f"(last: {latest_bar_time.date()})"
                )
            
            atr = None
            risk_per_share = None
            stop_price = None

            if earliest_close and latest_close and earliest_close > 0:
                momentum = (latest_close - earliest_close) / earliest_close

                # Classify trend
                if momentum > 0.02:
                    trend = "bullish"
                elif momentum < -0.02:
                    trend = "bearish"
                else:
                    trend = "neutral"

                # Simple ATR approximation from available OHLC bars
                true_ranges = []
                prev_close = None
                for rec in sorted_records:
                    high = rec.payload.get("high")
                    low = rec.payload.get("low")
                    close = rec.payload.get("close")
                    if high is None or low is None or close is None:
                        continue
                    if prev_close is None:
                        tr = high - low
                    else:
                        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                    true_ranges.append(tr)
                    prev_close = close
                if true_ranges:
                    atr = sum(true_ranges) / len(true_ranges)
                    risk_per_share = atr * 2
                    stop_price = latest_close - risk_per_share
            else:
                momentum = 0.0
                trend = "unknown"

            # Build quality flags
            quality_flags = []
            if is_stale:
                quality_flags.append("stale_data")
            
            result = FeatureResult(
                feature_name="price_momentum",
                symbol=symbol,
                computed_at=now,
                values={
                    "momentum": momentum,
                    "trend": trend,
                    "bars_used": len(sorted_records),
                    "atr": atr,
                    "risk_per_share": risk_per_share,
                    "stop_price": stop_price,
                    "latest_close": latest_close,
                    "data_age_days": data_age_days,
                },
                metadata={
                    "earliest_time": sorted_records[0].event_time.isoformat(),
                    "latest_time": sorted_records[-1].event_time.isoformat(),
                },
                quality_flags=quality_flags,
            )
            results.append(result)
        
        return results
```

### 5.2 MacroRegimeFeature

Key design choices:
- Global feature (not per-symbol)
- Uses FRED CPIAUCSL as primary indicator (simplified heuristic)
- Regime categories: expansion, high_volatility, recession, unknown
- TODO: Production would use multi-indicator regime detection

```python
"""Macro regime feature for classifying economic environment.

This feature uses FRED macro data to classify the current macro regime
(e.g., expansion, recession, high volatility).
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import BaseFeature, FeatureResult


class MacroRegimeFeature(BaseFeature):
    """Macro regime classification feature.
    
    Uses macro indicators (CPI, GDP, unemployment, etc.) to classify regime.
    
    Regime categories:
    - expansion: Growing economy, low volatility
    - recession: Contracting economy
    - high_volatility: Uncertain environment
    - unknown: Insufficient data
    """
    
    def compute(self, records: list[CanonicalRecord]) -> list[FeatureResult]:
        """Compute macro regime from macro data records.
        
        Args:
            records: Canonical records from FRED (macro data).
            
        Returns:
            List with one FeatureResult (macro regime is global).
            
        Note:
            This is a simplified implementation. Production would use
            more sophisticated regime detection algorithms.
        """
        # Filter to macro records
        macro_records = [r for r in records if r.source_type == "macro"]
        
        if not macro_records:
            # No macro data available
            return [self._unknown_regime()]
        
        # Simple heuristic: check if we have recent CPI data
        # Production would use multiple indicators
        cpi_records = [
            r for r in macro_records 
            if r.payload.get("series_id") == "CPIAUCSL"
        ]
        
        if cpi_records:
            latest_cpi = cpi_records[-1]  # Assume sorted by date
            cpi_value = latest_cpi.payload.get("value")
            
            # Simple regime classification (placeholder logic)
            if cpi_value and cpi_value < 320:
                regime = "expansion"
                confidence = 0.7
            else:
                regime = "high_volatility"
                confidence = 0.6
        else:
            regime = "unknown"
            confidence = 0.0
        
        result = FeatureResult(
            feature_name="macro_regime",
            symbol=None,  # Global feature
            computed_at=datetime.now(timezone.utc),
            values={
                "regime": regime,
                "confidence": confidence,
            },
            metadata={
                "input_records": len(macro_records),
                "indicators_used": ["CPIAUCSL"] if cpi_records else [],
            },
            quality_flags=[] if macro_records else ["insufficient_data"],
        )
        
        return [result]
    
    def _unknown_regime(self) -> FeatureResult:
        """Return unknown regime when no data available."""
        return FeatureResult(
            feature_name="macro_regime",
            symbol=None,
            computed_at=datetime.now(timezone.utc),
            values={
                "regime": "unknown",
                "confidence": 0.0,
            },
            metadata={},
            quality_flags=["no_macro_data"],
        )
```

## 6. Risk Validation

### 6.1 RiskValidator

Key design choices:
- Deny-first: any failed check → deny
- Checks: signal_strength, confidence, action validity, position size, symbol validity
- Position size check uses simple placeholder (10 shares) — actual sizing in paper_executor.py

```python
"""Risk validator for evaluating candidate signals.

This module implements risk checks that determine whether a candidate signal
can proceed to actionable decision or must be denied/reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from stock_swing.strategy_engine.base_strategy import CandidateSignal


class RiskState(Enum):
    """Risk validation state."""
    
    PASS = "pass"  # Risk checks passed
    DENY = "deny"  # Risk checks failed, must deny
    REVIEW = "review"  # Manual review required


@dataclass
class RiskValidationResult:
    """Result of risk validation.
    
    Attributes:
        risk_state: Overall risk state (pass/deny/review).
        deny_reasons: List of reasons if denied.
        review_notes: Notes for manual review.
        checks_performed: List of checks that were performed.
    """
    
    risk_state: RiskState
    deny_reasons: list[str] = field(default_factory=list)
    review_notes: list[str] = field(default_factory=list)
    checks_performed: list[str] = field(default_factory=list)


class RiskValidator:
    """Risk validator for candidate signals.
    
    Implements risk checks to determine if a candidate signal should:
    - Pass to actionable decision
    - Be denied
    - Require manual review
    """
    
    def __init__(
        self,
        min_signal_strength: float = 0.6,
        min_confidence: float = 0.5,
        max_position_size: int = 100,
    ):
        """Initialize risk validator.
        
        Args:
            min_signal_strength: Minimum signal strength to pass.
            min_confidence: Minimum confidence to pass.
            max_position_size: Maximum position size (shares).
        """
        self.min_signal_strength = min_signal_strength
        self.min_confidence = min_confidence
        self.max_position_size = max_position_size
    
    def validate(
        self,
        candidate: CandidateSignal,
        current_positions: dict[str, int] | None = None,
    ) -> RiskValidationResult:
        """Validate a candidate signal.
        
        Args:
            candidate: Candidate signal to validate.
            current_positions: Current positions (symbol → quantity).
            
        Returns:
            RiskValidationResult indicating pass/deny/review.
        """
        current_positions = current_positions or {}
        checks_performed = []
        deny_reasons = []
        review_notes = []
        
        # Check 1: Signal strength
        checks_performed.append("signal_strength")
        if candidate.signal_strength < self.min_signal_strength:
            deny_reasons.append(
                f"signal_strength {candidate.signal_strength:.2f} below minimum {self.min_signal_strength:.2f}"
            )
        
        # Check 2: Confidence
        checks_performed.append("confidence")
        if candidate.confidence < self.min_confidence:
            deny_reasons.append(
                f"confidence {candidate.confidence:.2f} below minimum {self.min_confidence:.2f}"
            )
        
        # Check 3: Action validity
        checks_performed.append("action_validity")
        if candidate.action not in {"buy", "sell", "hold"}:
            deny_reasons.append(f"invalid action: {candidate.action}")
        
        # Check 4: Position size (placeholder - would need proposed qty)
        # For now, assume 10 shares per signal (basic check)
        checks_performed.append("position_size")
        current_qty = current_positions.get(candidate.symbol, 0)
        proposed_qty = 10  # Placeholder - would come from position sizing logic
        
        if candidate.action == "buy":
            new_total = current_qty + proposed_qty
            if new_total > self.max_position_size:
                deny_reasons.append(
                    f"position_size would exceed limit: {new_total} > {self.max_position_size}"
                )
        
        # Check 5: Symbol validity (basic check)
        checks_performed.append("symbol_validity")
        if not candidate.symbol or len(candidate.symbol) < 1 or len(candidate.symbol) > 5:
            deny_reasons.append(f"invalid symbol: {candidate.symbol}")
        
        # Determine risk state
        if deny_reasons:
            risk_state = RiskState.DENY
        else:
            risk_state = RiskState.PASS
        
        return RiskValidationResult(
            risk_state=risk_state,
            deny_reasons=deny_reasons,
            review_notes=review_notes,
            checks_performed=checks_performed,
        )
```

## 7. Position Sizing (paper_executor.py)

### Allocation Policy
- ETF: max 45% of portfolio (hard block beyond threshold)
- Stock: max 55% of portfolio
- Per-symbol limit: 6% of portfolio notional
- Per-sector limit: 55% of portfolio

### Sizing Formula
Position size = min(
    available_buying_power × max_position_notional_pct,
    symbol_position_limit,
    sector_remaining_capacity
)

### Exposure Control by Regime
| Regime    | Max exposure |
|-----------|-------------|
| bullish   | 95%         |
| neutral   | 85%         |
| cautious  | 65%         |

### Key Safety Features
- Zero-sized buy preflight: orders with qty=0 are filtered before broker submission
- Stale order auto-cancel: previous day's unexecuted day orders are cancelled at market open

## 8. PnL Tracking (pnl_tracker.py)

### State Schema (pnl_state.json)
- trades: list of TradeEntry dicts (open + closed)
- daily_snapshots: daily equity curve data
- strategy_daily_snapshots: per-strategy daily breakdown
- cumulative_realized_pnl, winning_trades, losing_trades
- baseline_equity, broker_account_id, tracking_label

### TradeEntry Key Fields
- symbol, strategy_id, side, qty, entry_price, entry_time
- exit_price, exit_time, pnl, return_pct
- broker_order_id (for deduplication)
- peak_price (for trailing stop, persisted across sessions)
- entry_signal_strength (for dynamic exit thresholds)
- exit_reason: trailing_stop | breakeven_stop | stop_loss | time_based | broker_fill
- exit_strategy_id: simple_exit_v2:<trigger_name>

### record_exit() — FIFO lot matching
When a sell fill arrives, trades are closed in FIFO order until exit_qty is exhausted.
Partial fills create a new closed trade for the exited portion.

### Integrity Protection
- rebuild_pnl_state_from_broker.py: Full rebuild from Alpaca order history
- verify_rebuild_integrity.py: Post-rebuild checker (auto-restores daily_snapshots and peak_price from backup)
- audit_trades_with_market_data.py: Weekly audit comparing broker vs tracker

## 9. Console API (localhost:3335)

### Endpoints
| Endpoint | Purpose |
|----------|---------|
| GET /api/overview | Health score, equity, trade summary, account info |
| GET /api/positions | Open positions with unrealized PnL (broker-first, tracker fallback) |
| GET /api/trading | Closed trades, recent trades, daily snapshots |
| GET /api/live_metrics | Kelly criterion, drawdown, portfolio heat, risk score |
| GET /api/dashboard | Combined symbol + strategy overview |
| GET /api/cron_jobs | Cron job status |
| GET /api/logs | Paper demo audit logs |
| GET /api/exit_reasons | Exit reason breakdown |
| GET /api/decision_reasons | Entry decision reason breakdown |
| GET /api/symbol/<SYM> | Per-symbol drilldown |
| GET /api/summary/daily | Daily summary + alerts |
| GET /api/parameters | Strategy parameter view/edit |

### live_metrics Fields
- current_equity: From daily_snapshots equity curve (fallback $100K if empty — known bug now fixed)
- current_drawdown_pct, max_drawdown_pct
- kelly_suggested_size_pct: Kelly criterion (0 when negative = don't bet)
- portfolio_heat_pct: Sum of position weights × volatility proxy
- risk_score, risk_level (LOW/MODERATE/HIGH)
- open_positions_count: From broker positions API

## 10. Current Metrics (2026-05-28 09:30 JST)

### Account
- Baseline equity: $1,000,000 (paper, since 2026-05-12)
- Current equity: ~$1,030,370
- Unrealized PnL: +$54,575 (+5.5%)
- Cash: ~$2,234

### Trade Statistics (85 closed trades)
- Win rate: 47.1% (40 wins / 44 losses / 1 flat)
- Avg win PnL: +$614
- Avg loss PnL: -$1,110
- Profit Factor: 0.503 (CRITICAL — below 1.0 means negative expectancy)
- Cumulative realized PnL: -$24,268
- Trade Expectancy: -$285/trade

### Open Positions (53 trades / 38 symbols)
Symbols: AMAT, AMD, ANET, CHPS, CHPX, CRWD, CSCO, DDOG, DELL, FICO, FRWD, FTNT, FTXL,
         GOOGL, GTOP, HPE, INTC, LRCX, MU, NOW, NVDA, ORCL, PANW, PSCT, PTF, QCOM,
         QTEC, QTUM, RBRK, SKYY, SMCI, SMH, SMHX, SNOW, SOXQ, SOXX, TSLA, TTEQ

### Exit Reason Distribution (85 closed)
- broker_fill: 85/85 (100%) — exit strategy signals NEVER fired before 2026-05-27

### Known Issues / Root Causes
1. Profit Factor 0.503: Avg loss ($1,110) is 1.8× avg win ($614) — asymmetric risk/reward
2. Exit strategy was non-functional until 2026-05-27:
   - peak_price lost between sessions (not persisted) → trailing stop never triggered
   - exit_reason always recorded as broker_fill (manual paper_demo internal close)
3. Fixed 2026-05-27: peak_price now persisted, exit_reason tracked across sessions
4. First real exit strategy signals expected starting 2026-05-28 onwards

## 11. Improvement Roadmap

### Completed (T1–T22)
- T1-T4: Reconciliation, broker truth UI, test coverage, unrealized PnL (Week 1)
- T5-T8: Partial fill, mismatch structure, conversion analysis (Week 2)
- T9-T12: UI sort/filter, drilldown, daily summary, parameter tuning (Month 1)
- T13-T19: Operational stability, cron health, alert improvements (Phase 2)
- T21: Exit strategy — trailing stop, breakeven stop, entry-strength-linked thresholds, exit_reason persistence (2026-05-27)
- T22: Entry analysis — breakout_momentum_v2 improvement plan (2026-05-27)
- T23: Massive API integration for fresh prices (2026-05-15)

### In Progress
- T15: paper_demo cron 3-day consecutive completion (monitoring)
- T20: Sizing improvement live verification (monitoring)
- T21: Profit Factor re-measurement (target: after 2026-06-07)

### Next Actions
- 2026-06-07: Re-measure Profit Factor (has exit strategy improvement helped?)
- 2026-06-15: T25 Step 1 — run analyze_news_impact.py on 44 symbols, check if |r|>0.3 with n≥30
- If T25 Step 1 passes: T25 Step 2 (ETF sentiment mapping), T25 Step 3 (NewsFeature in paper_demo)
- T24: Massive WebSocket real-time prices (after REST stability confirmed)

### Key Open Questions for Analysis
1. Profit Factor 0.503 — primary driver: avg loss too large or win rate too low?
2. Exit strategy (trailing/breakeven stop) — will it improve profit factor from 2026-05-28 onwards?
3. breakout_momentum_v1 — "deny paradox": best signals have highest strength but get blocked by sector caps. How to fix allocation to let high-conviction signals through?
4. ETF vs Stock allocation: ETF was 83% before hard limit was added. With new 45% ETF hard cap, does return profile change?
5. News sentiment correlation: is Finnhub news sentiment predictive for these 44 symbols?

## 12. Recent Bug Fixes (2026-05-28)

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| live_metrics equity showed $100K | `get_live_metrics()` used `positions.get('current')` but `get_positions()` returns key `'positions'` | Changed to `positions.get('positions') or positions.get('current', [])` |
| recent_trades showed May 12-15 trades | `get_recent_trades()` returned last N by array index; broker_reconstructed trades happened to be at array tail | Added sort by exit_time before slice |
| reconcile sell mismatching | Matched by symbol only (most recent fill); could match old fills to new open positions | Added ±10min timestamp window matching; falls back to most-recent only if no time-proximate match |
| pending_exit_reasons never cleaned up | paper_demo records exits directly; reconcile_orders never sees them as "new" | Added cleanup of already-closed broker_order_ids on every reconcile run |
| rebuild wiped daily_snapshots and peak_price | Code was correct but data was lost (likely race condition with concurrent write) | Added verify_rebuild_integrity.py with auto-fix; integrated into rebuild script |
| reconcile cron silent failures | delivery.mode was "none" | Changed to announce → Telegram |

---

END OF DOCUMENT
