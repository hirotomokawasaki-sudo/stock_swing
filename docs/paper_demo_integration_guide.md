# Paper Demo Integration Guide: Intraday Momentum + VWAP

## Overview

This guide describes how to integrate the optimized Intraday Momentum + VWAP feature into the paper_demo workflow.

## Optimal Parameters (Grid Search Results)

From grid search on 60 days of data (2026-05-12):

```yaml
lookback_bars: 25
smoothing_window: 5
vwap_threshold: 0.005  # 0.5%
momentum_threshold: 0.003  # 0.3%
```

**Performance:**
- Total Trades: 55
- Win Rate: **76.4%** (vs 69.2% baseline)
- Avg Return: 2.88% per trade
- Total Return: 158.5% over 60 days
- Sharpe Ratio: 0.43

## Integration Approach

### Option 1: Hybrid Strategy (Recommended)

Combine both Daily and Intraday momentum:

```python
# Compute both features
daily_momentum = PriceMomentumFeature(period_days=20).compute(daily_records)
intraday_momentum = IntradayMomentumFeature(
    lookback_bars=25,
    smoothing_window=5,
    vwap_threshold=0.005
).compute(intraday_records)

# Signal logic:
# - Use daily momentum for trend identification
# - Use intraday momentum for entry timing
# - Require both to align for high-confidence signal

for daily_result in daily_momentum:
    symbol = daily_result.symbol
    intraday_result = find_intraday_result(symbol, intraday_momentum)
    
    daily_mom = daily_result.values['momentum']
    intraday_mom = intraday_result.values['smoothed_momentum']
    vwap_signal = intraday_result.values['vwap_signal']
    
    # High confidence: both bullish
    if daily_mom > 0.02 and intraday_mom > 0.003 and vwap_signal != 'below_vwap':
        confidence = 0.80  # High
        generate_signal(symbol, 'buy', confidence)
    
    # Medium confidence: daily bullish, intraday neutral
    elif daily_mom > 0.02 and intraday_mom > 0.001:
        confidence = 0.60  # Medium
        generate_signal(symbol, 'buy', confidence)
```

### Option 2: Intraday-Only Strategy

Use only intraday momentum:

```python
intraday_momentum = IntradayMomentumFeature(
    lookback_bars=25,
    smoothing_window=5,
    vwap_threshold=0.005
).compute(intraday_records)

for result in intraday_momentum:
    smoothed_mom = result.values['smoothed_momentum']
    vwap_signal = result.values['vwap_signal']
    
    if smoothed_mom > 0.003 and vwap_signal != 'below_vwap':
        confidence = min(smoothed_mom * 10, 1.0)
        generate_signal(result.symbol, 'buy', confidence)
```

## Implementation Steps

### Step 1: Add 5-Minute Data Collection

**Modify:** `src/stock_swing/cli/paper_demo.py`

```python
# After daily bars collection (around line 250)

# Add 5-minute bars collection
_section("5b. Data Collection (5-Minute Bars)")
intraday_records: list[CanonicalRecord] = []

def fetch_intraday_bars(symbol: str) -> tuple[str, list[CanonicalRecord], int, str | None]:
    """Fetch 5-minute bars for intraday analysis."""
    try:
        raw = broker.fetch_bars(symbol, timeframe="5Min", limit=100)  # ~8 hours
        records = normalizer.normalize_broker_bars(raw, symbol)
        return symbol, records, len(records), None
    except Exception as exc:
        return symbol, [], 0, str(exc)

with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(fetch_intraday_bars, sym): sym for sym in symbols}
    for future in as_completed(futures):
        symbol, records, bar_count, error = future.result()
        if error:
            print(f"  WARN: {symbol:<6} intraday fetch failed: {error}")
        else:
            intraday_records.extend(records)
            print(f"  OK: {symbol:<6} {bar_count:3d} 5-min bars")

print(f"\n  Total intraday records: {len(intraday_records)}")
```

### Step 2: Compute Intraday Momentum

```python
# After PriceMomentumFeature computation (around line 274)

from stock_swing.feature_engine.intraday_momentum_feature import IntradayMomentumFeature

intraday_feat = IntradayMomentumFeature(
    lookback_bars=25,
    smoothing_window=5,
    vwap_threshold=0.005
)
intraday_results = intraday_feat.compute(intraday_records)

# Display intraday momentum
print(f"\n  {'Symbol':<6}  {'Smoothed Mom':>12}  {'VWAP Signal':<12}  {'Intraday Vol':>12}")
print(f"  {'------':<6}  {'------------':>12}  {'------------':<12}  {'------------':>12}")
for f in sorted(intraday_results, key=lambda x: x.values.get("smoothed_momentum", 0), reverse=True):
    smoothed_mom = f.values.get("smoothed_momentum", 0)
    vwap_signal = f.values.get("vwap_signal", "unknown")
    intraday_vol = f.values.get("intraday_volatility", 0)
    print(f"  {f.symbol:<6}  {smoothed_mom:>+12.2%}  {vwap_signal:<12}  {intraday_vol:>12.2%}")

# Combine with all features
all_features = momentum_results + intraday_results + macro_results
```

### Step 3: Update Strategy Signal Logic

**Option A: Modify BreakoutMomentumStrategy**

```python
# In src/stock_swing/strategy_engine/breakout_momentum_strategy.py

def generate(self, features: list[FeatureResult]) -> list[SignalRecord]:
    # Separate daily and intraday features
    daily_features = [f for f in features if f.feature_name == "price_momentum"]
    intraday_features = [f for f in features if f.feature_name == "intraday_momentum"]
    
    # Create lookup
    intraday_by_symbol = {f.symbol: f for f in intraday_features}
    
    signals = []
    for daily_feat in daily_features:
        symbol = daily_feat.symbol
        daily_mom = daily_feat.values.get("momentum", 0)
        
        # Get intraday feature
        intraday_feat = intraday_by_symbol.get(symbol)
        
        # Base signal from daily momentum
        if daily_mom > self.min_momentum:
            base_strength = daily_mom * 10
            
            # Enhance with intraday if available
            if intraday_feat:
                smoothed_mom = intraday_feat.values.get("smoothed_momentum", 0)
                vwap_signal = intraday_feat.values.get("vwap_signal", "neutral")
                
                # Boost confidence if intraday confirms
                if smoothed_mom > 0.003 and vwap_signal != 'below_vwap':
                    signal_strength = min(base_strength * 1.2, 1.0)  # +20% boost
                    reasoning = f"Daily momentum {daily_mom:.2%}, Intraday confirmed (VWAP: {vwap_signal})"
                else:
                    signal_strength = base_strength
                    reasoning = f"Daily momentum {daily_mom:.2%}, Intraday weak"
            else:
                signal_strength = base_strength
                reasoning = f"Daily momentum {daily_mom:.2%} (no intraday data)"
            
            if signal_strength >= self.min_signal_strength:
                signals.append(SignalRecord(
                    symbol=symbol,
                    action="buy",
                    signal_strength=signal_strength,
                    strategy_id="breakout_momentum_v2",
                    reasoning=reasoning,
                    generated_at=datetime.now(timezone.utc)
                ))
    
    return signals
```

**Option B: Create New Strategy**

```python
# src/stock_swing/strategy_engine/intraday_vwap_strategy.py

class IntradayVWAPStrategy:
    """Intraday momentum + VWAP strategy.
    
    Uses optimized parameters from grid search:
    - Smoothed momentum > 0.3%
    - VWAP signal != below_vwap
    - Win rate: 76.4%
    """
    
    def __init__(
        self,
        min_smoothed_momentum: float = 0.003,
        min_signal_strength: float = 0.52,
    ):
        self.min_smoothed_momentum = min_smoothed_momentum
        self.min_signal_strength = min_signal_strength
    
    def generate(self, features: list[FeatureResult]) -> list[SignalRecord]:
        intraday_features = [f for f in features if f.feature_name == "intraday_momentum"]
        
        signals = []
        for feat in intraday_features:
            smoothed_mom = feat.values.get("smoothed_momentum", 0)
            vwap_signal = feat.values.get("vwap_signal", "neutral")
            
            if smoothed_mom > self.min_smoothed_momentum and vwap_signal != 'below_vwap':
                # Scale confidence based on momentum strength
                signal_strength = min(smoothed_mom * 10, 1.0)
                
                if signal_strength >= self.min_signal_strength:
                    reasoning = (
                        f"Intraday momentum {smoothed_mom:.2%} "
                        f"(VWAP: {vwap_signal})"
                    )
                    
                    signals.append(SignalRecord(
                        symbol=feat.symbol,
                        action="buy",
                        signal_strength=signal_strength,
                        strategy_id="intraday_vwap",
                        reasoning=reasoning,
                        generated_at=datetime.now(timezone.utc)
                    ))
        
        return signals
```

### Step 4: Test Integration

```bash
# Dry run test
python -m stock_swing.cli.paper_demo --dry-run --allow-outside-hours

# Check for:
# - 5-minute bars collection success
# - Intraday momentum computation
# - Signal generation with VWAP filter
# - Confidence scores
```

## Configuration File

Created: `config/features/intraday_momentum.yaml`

```yaml
lookback_bars: 25
smoothing_window: 5
vwap_threshold: 0.005
signal_criteria:
  momentum_threshold: 0.003
  vwap_filter: true
  min_confidence: 0.50
```

## Monitoring & Validation

### Daily Checks

1. **Signal Quality:**
   - Win rate should be 75%+ (vs 69% baseline)
   - Avg return per trade should be 2.5%+

2. **VWAP Filter Effectiveness:**
   - Count signals where VWAP filter prevented entry
   - Validate that filtered-out signals would have been losses

3. **Data Quality:**
   - Verify 5-minute bars are available for all symbols
   - Check for gaps or missing data

### Weekly Review

- Compare actual win rate vs backtested (76.4%)
- Measure false positive rate
- Adjust thresholds if needed

## Rollback Plan

If performance degrades:

1. **Quick fix:** Increase momentum_threshold from 0.003 to 0.005
2. **Full rollback:** Remove intraday feature, revert to daily-only

## Next Steps

1. ✅ Create configuration file
2. ⬜ Implement 5-minute data collection in paper_demo.py
3. ⬜ Add IntradayMomentumFeature computation
4. ⬜ Update signal generation logic
5. ⬜ Test with --dry-run
6. ⬜ Deploy to production cron
7. ⬜ Monitor for 1 week
8. ⬜ Validate win rate improvement

## References

- Grid search results: `scripts/backtest_grid_search.py`
- Feature implementation: `src/stock_swing/feature_engine/intraday_momentum_feature.py`
- Configuration: `config/features/intraday_momentum.yaml`
- Backtest script: `scripts/backtest_momentum_comparison.py`
