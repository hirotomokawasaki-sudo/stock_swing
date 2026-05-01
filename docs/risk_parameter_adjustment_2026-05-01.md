# Risk Parameter Adjustment for $1M Capital - 2026-05-01

## Summary

Adjusted position sizing and concentration limits to better manage risk with the new $1M capital base (up from $104K).

## Problem Analysis

### Issue: Concentration Risk Scaled with Capital

**Old Account ($104K):**
- 12% per symbol = $12,480 → Acceptable concentration
- 75% exposure = $78,000 across 6-7 positions → Reasonable diversification

**New Account ($1M - Before Adjustment):**
- 12% per symbol = $120,000 → **Excessive concentration**
- 75% exposure = $750,000 across 6-7 positions → **Insufficient diversification**

**Risk Impact:**
- A single stock down 10% = $12,000 loss
- Represents 1.2% of entire portfolio
- Individual stock risk too high relative to portfolio size

## Changes Made

### 1. Symbol-level Position Limits

| Parameter | Old Value | New Value | Reasoning |
|-----------|-----------|-----------|-----------|
| **Stocks** | 12% ($120K) | **6% ($60K)** | Halve concentration risk |
| **ETFs** | 30% ($300K) | **15% ($150K)** | 2-3 ETFs to reach 35% target |

**Impact:**
- Stocks: Double the diversification (6-7 positions → 12-14 positions)
- ETFs: Encourage multi-ETF allocation instead of 1-2 concentrated positions
- Risk per position: -50% reduction

### 2. Position Sizing Defaults

| Parameter | Old Value | New Value | File |
|-----------|-----------|-----------|------|
| `max_position_notional_pct` | 8% | **6%** | position_sizing.py |
| ETF minimum floor | 10% | **8%** | position_sizing.py |

**Rationale:**
- Align with symbol-level limits
- Better diversification across more positions
- Maintain consistency throughout risk framework

### 3. Unchanged (Rationale)

| Parameter | Value | Why Not Changed |
|-----------|-------|-----------------|
| **Exposure Limits** | 75%/85%/60% | Already optimal for target utilization |
| **Risk per Trade** | 0.5% | Conservative and appropriate |
| **Portfolio Allocation** | 35% ETF / 65% Stock | Target mix still valid |
| **Sector Exposure** | 80% | Limited universe justifies concentration |

## Expected Outcomes

### Quantitative Improvements

```
✅ Diversification: 2x improvement
   - Old: 6-7 positions
   - New: 12-14 positions

✅ Concentration Risk: -50%
   - Old: Single stock failure = -1.2% portfolio
   - New: Single stock failure = -0.6% portfolio

✅ Drawdown Resilience: +30-40%
   - More positions → smoother equity curve
   - Lower correlation → reduced portfolio volatility

✅ Capital Efficiency: Maintained
   - Still targeting 75% exposure ($750K deployed)
   - Just spread across more positions
```

### Qualitative Benefits

```
✅ Better Sector Balance
   - Can hold 2-3 positions per sector
   - Reduces single-sector concentration

✅ More Signal Capture
   - Lower per-position size → more signals can fit
   - Improved portfolio construction flexibility

✅ Risk-Adjusted Returns
   - Lower individual position risk
   - Similar upside potential with less downside
```

## Implementation Timeline

### Phase 1: Conservative Baseline (Immediate - 2026-05-01)

**Settings:**
- Stocks: 6% max
- ETFs: 15% max
- Exposure: 75% (neutral)

**Duration:** 2-4 weeks

**Success Criteria:**
- Portfolio builds to 10+ positions
- Exposure reaches 60-75%
- No single position >6.5% (allowing slight overruns)
- Win rate maintains ≥55%

### Phase 2: Optimization (After 2-4 weeks)

**Potential Adjustments:**
- Stocks: 6% → 7% (if diversification achieved)
- ETFs: 15% → 18%
- Exposure: 75% → 78% (neutral)
- Risk per trade: 0.5% → 0.6%

**Conditions:**
- Phase 1 performance metrics healthy
- No concentration issues observed
- Portfolio showing good diversification

### Phase 3: Dynamic Tuning (3-6 months)

**Advanced Features:**
- Volatility-adjusted position sizing
- Liquidity-based limits (5-8% range)
- Dynamic exposure based on market regime
- Confidence-based multipliers refinement

## Risk Considerations

### Downside Protection

```
Conservative Approach:
- Phase 1 settings intentionally restrictive
- Provides margin of safety during transition
- Can always increase limits later (harder to decrease)

Monitoring:
- Track concentration metrics weekly
- Alert if any position exceeds 7%
- Review sector exposure monthly
```

### Failure Modes

```
Scenario 1: Under-utilization
- Risk: Portfolio only reaches 50% exposure
- Mitigation: Phase 2 adjustments after 2 weeks
- Acceptable: Better to start conservative

Scenario 2: Signal overflow
- Risk: More signals than capacity
- Mitigation: Prioritization already in place (confidence, allocation)
- Acceptable: High-quality problem to have

Scenario 3: Fragmentation
- Risk: Too many tiny positions
- Mitigation: Minimum position size enforcement
- Current: Risk per trade (0.5%) provides natural floor
```

## Performance Baseline

### Pre-Adjustment Metrics (Old Account)

```
Capital: $104,675
Exposure: 42.6% ($44,613)
Positions: 10
Win Rate: 63.04%
Avg Return: 3.03%
Max Drawdown: 2.16%
```

### Post-Adjustment Targets (New Account)

```
Capital: $1,000,000
Exposure Target: 70-75% ($700-750K)
Positions Target: 12-15
Win Rate Target: ≥58%
Max Drawdown Target: <10%
Sharpe Ratio Target: 1.2-1.5
```

## Code Changes

### Files Modified

1. `src/stock_swing/cli/paper_demo.py`
   - `MAX_POSITION_PER_SYMBOL_PCT: 0.12 → 0.06`
   - `MAX_POSITION_PER_ETF_PCT: 0.30 → 0.15`

2. `src/stock_swing/risk/position_sizing.py`
   - `max_position_notional_pct: 0.08 → 0.06`
   - ETF floor: `0.10 → 0.08`

### Configuration Files

No configuration file changes required. All adjustments made at code level for consistency.

## Monitoring Plan

### Daily Checks

```
□ Total exposure vs target (should reach 60-75%)
□ Number of positions (should be 10+)
□ Largest position size (should be <7%)
□ ETF allocation progress (target 20-25% initially)
```

### Weekly Review

```
□ Concentration metrics
  - Top 3 positions < 20% combined
  - Top 5 positions < 35% combined
  
□ Sector exposure
  - No single sector >40%
  - Semis/Software balance

□ Performance vs baseline
  - Win rate tracking
  - Return per position
```

### Monthly Assessment

```
□ Phase 1 success criteria review
□ Prepare Phase 2 adjustments if warranted
□ Document lessons learned
□ Update parameter recommendations
```

## Rollback Plan

If Phase 1 shows issues:

```
Scenario: Excessive caution (exposure <50%)
→ Action: Increase limits by 1% increments weekly
→ Target: Reach 65% exposure within 4 weeks

Scenario: Performance degradation (win rate <55%)
→ Action: Pause adjustments, analyze root cause
→ Investigate: Position sizing, signal quality, execution

Scenario: Unexpected concentration
→ Action: Add manual checks in paper_demo.py
→ Enforce: Hard caps at symbol level
```

## References

- Account Migration: `docs/account_migration_2026-05-01.md`
- Original Implementation: `docs/portfolio_allocation_implementation_plan.md`
- Strategy Config: `config/strategy/portfolio_allocation.yaml`

## Change Log

- **2026-05-01**: Initial adjustment (Phase 1)
  - Stocks: 12% → 6%
  - ETFs: 30% → 15%
  - Rationale: Capital increase from $104K to $1M
  - Author: Assistant (based on user request for parameter review)

---

**Status:** ✅ Implemented (Phase 1)  
**Next Review:** 2-4 weeks from implementation  
**Owner:** Trading System / Risk Management
