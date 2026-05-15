# Exit Strategy Investigation - 2026-05-15

## Problem Statement
User observed that positions were being closed at small negative P&L (before reaching -7% stop loss) within 1 day, despite max_hold_days=9 configuration.

## Investigation Timeline

### 1. Initial Findings
- All 67 closed trades exited within 1 day (average 0.32 days, median 0.04 days = ~1 hour)
- 31 trades closed at small losses (0% to -7%)
- Config specifies: stop_loss=-7%, max_hold_days=9, trailing_stop=3%
- None of the time-based (9 day) exits were ever triggered

### 2. Exit Reasoning Analysis
- Exit decisions had `reasoning=null` and `metadata=null` when queried directly
- Actual reasoning found in `evidence.notes` field:
  - Example: `"Stop loss triggered: -19.23% <= -7.00%"` for TTEQ
- SimpleExitV2Strategy **is generating reasoning correctly**

### 3. Price Data Investigation
**ROOT CAUSE IDENTIFIED:**

All ETF symbols (16/16) have **stale price data**:
```
TTEQ: last bar 2026-04-22 ($36.36) - broker stopped updating
SOXQ, SOXX, SMH, FTXL, PTF, SMHX, FRWD, GTOP, CHPX, CHPS, 
PSCT, QTEC, TDIV, SKYY, QTUM: all stopped 2026-04-22
```

### 4. Impact Analysis

**Example: TTEQ trade**
- Actual entry: $41.02 (2026-05-12)
- Stale price used in decision: $34.18 (from 2026-04 data)
- Calculated return: -16.4% → triggers stop loss
- Actual exit price: $41.16 (reconciler uses broker fill)
- Actual return: -0.79%

**Why final P&L is correct:**
- `reconcile_orders.py` uses broker's actual fill prices
- Tracker records the correct exit price
- But decisions are based on wrong prices

**Why all ETFs exited quickly:**
- paper_demo uses 3-week-old prices (~$35-40)
- Real positions entered at current prices (~$41-48)
- Every ETF position appears to be down -15% to -20%
- SimpleExitV2 immediately triggers stop loss
- All ETF positions get sold within hours

### 5. API Inconsistency
Broker (Alpaca) has conflicting APIs:
1. **fetch_positions()** → returns fresh `current_price` ($41.88 for TTEQ) ✓
2. **fetch_bars()** → returns stale bars (last: 2026-04-22) ✗

SimpleExitV2Strategy prioritizes price_map (from bars):
```python
current_price = price_map.get(symbol) or float(position_data.get("current_price", 0))
```

Since ETF symbols exist in price_map (with stale prices), the fallback to position current_price never happens.

## Root Causes

1. **Broker data feed issue**: ETF historical bars stopped updating after 2026-04-22
2. **No stale data detection**: System doesn't validate price data freshness
3. **Price fallback logic**: Stale bars take priority over fresh position prices
4. **No time-series consistency check**: Entry time vs price data time not validated

## Recommendations

### Immediate Fixes
1. **Add stale data detection** in PriceMomentumFeature:
   - Check if latest bar is within last 7 days
   - Exclude stale symbols from price_map
   - Log warnings for stale data

2. **Fix price fallback priority** in SimpleExitV2Strategy:
   - Use position current_price as primary source
   - Use price_map only if position price is missing
   - Add data age check

3. **Add position-price consistency validation**:
   - Verify entry_time is after latest bar time
   - Flag positions with price data older than entry

### Longer-term Solutions
1. **Review ETF symbol list**: Use symbols with reliable data feeds
2. **Add market data health checks**: Daily validation of data freshness
3. **Implement data source fallback**: Use alternative price sources when primary fails
4. **Add decision audit trail**: Log price sources and timestamps in decisions

## Next Steps
1. Implement stale data detection (priority: HIGH)
2. Fix SimpleExitV2Strategy price logic
3. Add tests for stale data scenarios
4. Review and update ETF symbol list
5. Document data freshness requirements

## Files Involved
- `src/stock_swing/feature_engine/price_momentum_feature.py`
- `src/stock_swing/strategy_engine/simple_exit_v2_strategy.py`
- `src/stock_swing/cli/paper_demo.py`
- `src/stock_swing/cli/reconcile_orders.py`

## Impact
- **Severity**: HIGH
- **Affected**: All ETF positions since 2026-04-22
- **User impact**: Unexpected early exits, confusion about exit logic
- **Data integrity**: Final P&L correct (due to reconciler), but decisions based on wrong data
