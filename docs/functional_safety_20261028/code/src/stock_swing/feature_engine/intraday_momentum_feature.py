"""Intraday momentum feature for minute-level bar data.

This feature computes momentum indicators from minute/5-minute bar data,
utilizing additional fields like VWAP and transaction count from Massive API.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Dict, List

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import BaseFeature, FeatureResult


class IntradayMomentumFeature(BaseFeature):
    """Intraday momentum feature for minute-level bars.
    
    Computes momentum indicators optimized for minute/5-minute data:
    - Short-term momentum (last N bars)
    - VWAP deviation (price vs volume-weighted average)
    - Intraday volatility
    - Volume trend
    - Smoothed momentum (reduces noise from minute-level data)
    """
    
    def __init__(
        self,
        lookback_bars: int = 20,
        smoothing_window: int = 5,
        vwap_threshold: float = 0.005,
    ):
        """Initialize intraday momentum feature.
        
        Args:
            lookback_bars: Number of bars for momentum calculation (default 20 = 100min for 5min bars)
            smoothing_window: Window size for moving average smoothing (reduces noise)
            vwap_threshold: Threshold for VWAP deviation signal (default 0.5%)
        """
        self.lookback_bars = lookback_bars
        self.smoothing_window = smoothing_window
        self.vwap_threshold = vwap_threshold
    
    def compute(self, records: list[CanonicalRecord]) -> list[FeatureResult]:
        """Compute intraday momentum for symbols.
        
        Args:
            records: Canonical records (minute-level price bars).
            
        Returns:
            List of FeatureResult (one per symbol).
        """
        # Filter to price records
        price_records = [
            r for r in records 
            if r.source_type == "price" and "bar_" in r.event_type
        ]
        
        if not price_records:
            return []
        
        # Group by symbol
        symbols: Dict[str, List[CanonicalRecord]] = {}
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
            
            # Take only recent bars for intraday analysis
            recent_records = sorted_records[-self.lookback_bars:] if len(sorted_records) > self.lookback_bars else sorted_records
            
            if len(recent_records) < 2:
                # Insufficient data
                result = FeatureResult(
                    feature_name="intraday_momentum",
                    symbol=symbol,
                    computed_at=now,
                    values={
                        "momentum": 0.0,
                        "smoothed_momentum": 0.0,
                        "vwap_signal": "neutral",
                        "trend": "unknown",
                    },
                    metadata={},
                    quality_flags=["insufficient_bars"],
                )
                results.append(result)
                continue
            
            # Extract OHLCV data
            closes = []
            opens = []
            highs = []
            lows = []
            volumes = []
            vwaps = []
            
            for rec in recent_records:
                close = rec.payload.get("close")
                open_price = rec.payload.get("open")
                high = rec.payload.get("high")
                low = rec.payload.get("low")
                volume = rec.payload.get("volume")
                vwap = rec.payload.get("vw")  # VWAP from Massive
                
                if close is not None:
                    closes.append(close)
                if open_price is not None:
                    opens.append(open_price)
                if high is not None:
                    highs.append(high)
                if low is not None:
                    lows.append(low)
                if volume is not None:
                    volumes.append(volume)
                if vwap is not None:
                    vwaps.append(vwap)
            
            if not closes or len(closes) < 2:
                result = FeatureResult(
                    feature_name="intraday_momentum",
                    symbol=symbol,
                    computed_at=now,
                    values={
                        "momentum": 0.0,
                        "smoothed_momentum": 0.0,
                        "vwap_signal": "neutral",
                        "trend": "unknown",
                    },
                    metadata={},
                    quality_flags=["insufficient_price_data"],
                )
                results.append(result)
                continue
            
            # 1. Raw momentum: (latest_close - earliest_close) / earliest_close
            earliest_close = closes[0]
            latest_close = closes[-1]
            raw_momentum = (latest_close - earliest_close) / earliest_close if earliest_close > 0 else 0.0
            
            # 2. Smoothed momentum (moving average to reduce noise)
            if len(closes) >= self.smoothing_window:
                recent_closes = closes[-self.smoothing_window:]
                smoothed_close = sum(recent_closes) / len(recent_closes)
                baseline_closes = closes[:self.smoothing_window]
                baseline_close = sum(baseline_closes) / len(baseline_closes)
                smoothed_momentum = (smoothed_close - baseline_close) / baseline_close if baseline_close > 0 else 0.0
            else:
                smoothed_momentum = raw_momentum
            
            # 3. VWAP deviation signal
            vwap_signal = "neutral"
            vwap_deviation = None
            if vwaps and latest_close:
                latest_vwap = vwaps[-1]
                vwap_deviation = (latest_close - latest_vwap) / latest_vwap if latest_vwap > 0 else 0.0
                
                if vwap_deviation > self.vwap_threshold:
                    vwap_signal = "above_vwap"  # Price > VWAP = bullish
                elif vwap_deviation < -self.vwap_threshold:
                    vwap_signal = "below_vwap"  # Price < VWAP = bearish
            
            # 4. Trend classification
            if smoothed_momentum > 0.01:
                trend = "bullish"
            elif smoothed_momentum < -0.01:
                trend = "bearish"
            else:
                trend = "neutral"
            
            # 5. Intraday volatility (ATR for recent bars)
            true_ranges = []
            prev_close = None
            for i in range(len(recent_records)):
                high = highs[i] if i < len(highs) else None
                low = lows[i] if i < len(lows) else None
                close = closes[i] if i < len(closes) else None
                
                if high is None or low is None or close is None:
                    continue
                
                if prev_close is None:
                    tr = high - low
                else:
                    tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                true_ranges.append(tr)
                prev_close = close
            
            atr = sum(true_ranges) / len(true_ranges) if true_ranges else None
            intraday_volatility = (atr / latest_close) if (atr and latest_close > 0) else None
            
            # 6. Volume trend (recent avg vs baseline avg)
            volume_trend = None
            if len(volumes) >= self.smoothing_window * 2:
                recent_vol = sum(volumes[-self.smoothing_window:]) / self.smoothing_window
                baseline_vol = sum(volumes[:self.smoothing_window]) / self.smoothing_window
                volume_trend = (recent_vol - baseline_vol) / baseline_vol if baseline_vol > 0 else 0.0
            
            # 7. Risk metrics
            risk_per_share = atr * 2 if atr else None
            stop_price = latest_close - risk_per_share if risk_per_share else None
            
            result = FeatureResult(
                feature_name="intraday_momentum",
                symbol=symbol,
                computed_at=now,
                values={
                    "momentum": raw_momentum,
                    "smoothed_momentum": smoothed_momentum,
                    "vwap_signal": vwap_signal,
                    "vwap_deviation": vwap_deviation,
                    "trend": trend,
                    "bars_used": len(recent_records),
                    "intraday_volatility": intraday_volatility,
                    "atr": atr,
                    "volume_trend": volume_trend,
                    "risk_per_share": risk_per_share,
                    "stop_price": stop_price,
                    "latest_close": latest_close,
                    "latest_vwap": vwaps[-1] if vwaps else None,
                },
                metadata={
                    "earliest_time": recent_records[0].event_time.isoformat(),
                    "latest_time": recent_records[-1].event_time.isoformat(),
                    "lookback_bars": self.lookback_bars,
                    "smoothing_window": self.smoothing_window,
                    "has_vwap": len(vwaps) > 0,
                },
                quality_flags=[],
            )
            results.append(result)
        
        return results
