# Console Output Review Report

**Date:** 2026-04-22 11:33 JST  
**Purpose:** Comprehensive review for strategy confirmation, quality assurance, and improvement planning  

---

## Executive Summary

**Overall Assessment:** 🟡 Good but needs enhancements (7/10)

**Current Strengths:**
- Clear section structure
- Critical information present
- Good error handling
- Position details now comprehensive

**Critical Gaps:**
- Missing exit signal details
- No risk utilization metrics
- Limited strategy effectiveness indicators
- No performance context

---

## Section-by-Section Analysis

### ✅ Section 1: Runtime Mode

```
-- 1. Runtime Mode ----------------------------------------
  OK: runtime_mode=paper
```

**Status:** ✅ Complete  
**Information provided:**
- Current mode (paper/live)

**Missing:**
- None

**Quality:** Excellent

---

### ✅ Section 2: Kill Switch

```
-- 2. Kill Switch -----------------------------------------
  OK: Kill switch ACTIVE (execution allowed)
```

**Status:** ✅ Complete  
**Information provided:**
- Kill switch status

**Missing:**
- None (simple boolean status is sufficient)

**Quality:** Excellent

---

### ⚠️ Section 3: Market Hours

```
-- 3. Market Hours ----------------------------------------
  WARN: Market closed: Outside trading hours
```

**Status:** ⚠️ Adequate but could be better  
**Information provided:**
- Market open/closed status
- Basic reason

**Missing (would be helpful):**
- Next market open time
- Current time in market timezone
- Time until next open

**Improvement suggestion:**
```
-- 3. Market Hours ----------------------------------------
  WARN: Market closed (Outside trading hours)
  Current time:     02:33 UTC (11:33 JST)
  Market timezone:  US/Eastern (ET)
  Next open:        Today 13:30 UTC (22:30 JST)
  Time until open:  10h 57m
```

**Priority:** Low (nice to have)

---

### ✅ Section 4: Broker

```
-- 4. Broker ----------------------------------------------
  URL: https://paper-api.alpaca.markets/v2
  OK: status=ACTIVE equity=$103,737.12 bp=$44,755.98
```

**Status:** ✅ Complete  
**Information provided:**
- Broker URL
- Account status
- Equity (total assets)
- Buying power

**Missing (would enhance):**
- Portfolio margin usage
- Day trade count (if applicable)
- Account restrictions/warnings

**Improvement suggestion:**
```
-- 4. Broker Account --------------------------------------
  URL: https://paper-api.alpaca.markets/v2
  Status:           ACTIVE
  Equity:           $103,737.12
  Cash:             $44,755.98
  Buying Power:     $44,755.98
  Portfolio Value:  $58,981.14 (56.8% of equity)
  Margin Used:      $0.00 (0%)
```

**Priority:** Medium

---

### ✅ Section 5: Data Collection

```
-- 5. Data Collection (Broker Bars) -----------------------
  OK: AAPL    20 bars ->  20 records
  OK: MSFT    20 bars ->  20 records
  ...
  Total records: 200
```

**Status:** ✅ Complete  
**Information provided:**
- Data fetch status per symbol
- Bar count and record count

**Missing:**
- None (data quality is sufficient)

**Quality:** Excellent

---

### ⚠️ Section 6: Feature Computation

```
-- 6. Feature Computation ---------------------------------
  Macro regime: unknown
  Price regime: cautious
  Sizing regime: cautious

  Symbol    Momentum  Trend        Bars
  ------    --------        ----   ----
  CRM         +9.64%  bullish        20
  AMD         +2.41%  bullish        20
  ...
```

**Status:** ⚠️ Good but missing context  
**Information provided:**
- Macro regime (from FRED data)
- Price regime (from momentum breadth)
- Sizing regime (used for position sizing)
- Momentum per symbol
- Trend classification

**Missing (critical for strategy):**
- **ATR (volatility) per symbol**
- **Volume indicators**
- **Sector classification per symbol**
- **Signal strength breakdown**

**Improvement suggestion:**
```
-- 6. Feature Computation ---------------------------------
  Market Regime:
    Macro:              unknown (FRED data unavailable)
    Price:              cautious (40% bearish breadth)
    Sizing regime:      cautious (50% max exposure)
    
  Symbol Analysis:
    Symbol    Momentum   Trend      ATR    Sector
    ------    --------   -----    -----    ------
    CRM         +9.64%   bullish   3.2%    Software
    AMD         +2.41%   bullish   4.1%    Semiconductor
    AMZN        +0.00%   neutral   2.8%    Consumer
    ...
    
  Breadth Summary:
    Bullish:    2 symbols (20%)
    Neutral:    2 symbols (20%)
    Bearish:    6 symbols (60%)
```

**Priority:** High (needed for Week 3 analysis)

---

### 🔴 Section 7: Strategy Signals

```
-- 7. Strategy Signals ------------------------------------
  BreakoutMomentum: 1 signal(s)
  EventSwing:       0 signal(s)
  SimpleExit:       0 signal(s)
  (Buy signals prioritized for sector diversification)
  -> [breakout_momentum_v1] CRM: BUY strength=0.96
     Strong bullish momentum (9.64%) indicates breakout
```

**Status:** 🔴 Critical information missing  
**Information provided:**
- Signal count per strategy
- Individual signals with reasoning

**Missing (CRITICAL):**
- **Exit signals detail** - WHY are there 0 exit signals?
- **Current positions needing exit** - which positions meet exit criteria?
- **Risk/reward per signal**
- **Expected position size**
- **Sector per signal**
- **Confidence breakdown**

**This is the MOST IMPORTANT section and needs major enhancement!**

**Improvement suggestion:**
```
-- 7. Strategy Signals ------------------------------------
  Entry Signals:
    BreakoutMomentum:     1 signal(s)
    EventSwing:           0 signal(s)
    
  Exit Signals:
    SimpleExit:           0 signal(s)
    (12 positions checked, 0 meet exit criteria)
    Closest to stop loss:  DDOG (-1.68%, need -7.00%)
    Closest to take profit: ADBE (+2.68%, need +10.00%)
    Longest hold:          MRVL (8 days, max 5 days) ⚠️
    
  Signal Details:
    [BUY] CRM (Software sector)
      Strategy:         breakout_momentum_v1
      Signal Strength:  0.96 (strong)
      Confidence:       0.82
      Momentum:         +9.64%
      Trend:            bullish
      Expected Size:    10 shares (~$1,894)
      Risk/Reward:      1:3 (7% risk, 21% potential)
      Reasoning:        Strong bullish momentum (9.64%) indicates breakout
```

**Priority:** 🔴 CRITICAL

---

### ⚠️ Section 8: Decision Engine

```
-- 8. Decision Engine -------------------------------------
  Current Positions:
    Symbol    Qty  Avg Entry    Current      P&L $    P&L %
    ------ ------ ---------- ---------- ---------- --------
    ADBE       19 $   246.47 $   253.07 $   125.42    2.68%
    ...
    
  [PASS] CRM: action=buy risk=pass conf=0.82
```

**Status:** ⚠️ Good but missing risk context  
**Information provided:**
- ✅ Position details (recently added)
- Decision outcome (PASS/SKIP)

**Missing:**
- **Total position value**
- **Sector breakdown**
- **Exposure utilization**
- **Risk metrics**
- **Denial reasons** (for SKIP decisions)

**Improvement suggestion:**
```
-- 8. Decision Engine -------------------------------------
  Portfolio Summary:
    Total Positions:      12
    Total Value:          $58,981.14
    Total P&L:            +$261.28 (+0.44%)
    Exposure:             56.8% of equity (max: 65% in cautious)
    Available Capacity:   $8,500 (8.2%)
    
  Sector Allocation:
    Software:             $25,420 (24.5%)  ← at limit
    Semiconductor:        $18,500 (17.8%)
    Other:                $15,061 (14.5%)
    
  Current Positions:
    Symbol    Qty  Avg Entry    Current      P&L $    P&L %   Hold   Sector
    ------ ------ ---------- ---------- ---------- -------- ------ --------
    ADBE       19 $   246.47 $   253.07 $   125.42    2.68%   8d    Software
    MU         41 $   446.29 $   453.70 $   303.93    1.66%   3d    Semicon
    ...
    
  Position Risk:
    Closest to stop loss:    DDOG (-1.68%, buffer: 5.32%)
    Closest to take profit:  ADBE (+2.68%, need: +7.32%)
    Over hold limit:         0 positions
    
  Decision Analysis:
    [PASS] CRM: action=buy risk=pass conf=0.82
      Risk checks:         ✓ signal strength (0.96 > 0.55)
                          ✓ confidence (0.82 > 0.40)
                          ✓ position size (<50 shares)
                          ⚠ sector near limit (Software 24.5%/50%)
```

**Priority:** High

---

### ⚠️ Section 9: Paper Order Submission

```
-- 9. Paper Order Submission ------------------------------
  Actionable: 1  Denied/held: 0

  DRY RUN - would submit:
    BUY 10 CRM type=market tif=day
```

**Status:** ⚠️ Basic but functional  
**Information provided:**
- Actionable count
- Denied count
- Order details

**Missing:**
- **Expected fill price**
- **Order value**
- **Impact on exposure**
- **Risk amount**
- **Denial reasons** (when denied > 0)

**Improvement suggestion:**
```
-- 9. Paper Order Submission ------------------------------
  Orders:               1 actionable, 0 denied
  
  DRY RUN - Orders to submit:
    [1] BUY 10 CRM @ market
        Type:             market, TIF: day
        Est. fill:        ~$189.40
        Est. value:       ~$1,894
        Risk:             $132.58 (7% of $1,894)
        Portfolio impact: +1.8% exposure (56.8% → 58.6%)
        Sector impact:    Software (24.5% → 26.3%)
        
  Denied Orders: (none)
```

**Priority:** Medium

---

### ⚠️ Section 10: Summary

```
============================================================
  SUMMARY [DRY RUN]
  2026-04-22 02:34:00 UTC
============================================================
  Decisions : 1  Actionable: 1  Denied: 0  Held: 0
  Equity    : $103,737.12
  Decisions saved to data/decisions/
============================================================
```

**Status:** ⚠️ Too minimal  
**Information provided:**
- Decision counts
- Current equity

**Missing (CRITICAL):**
- **Daily P&L change**
- **Performance since start**
- **Win rate**
- **Recent trend**
- **Key metrics**

**Improvement suggestion:**
```
============================================================
  SUMMARY [DRY RUN]
  2026-04-22 02:34:00 UTC (11:34 JST)
============================================================
  SESSION:
    Decisions:          1 (1 actionable, 0 denied, 0 held)
    Orders:             1 to submit
    Execution Rate:     100% (1/1 signals)
    
  ACCOUNT:
    Current Equity:     $103,737.12
    Daily Change:       +$6.80 (+0.01%)
    Since Start:        +$3,737.12 (+3.74%)
    
  PORTFOLIO:
    Open Positions:     12
    Total P&L:          +$261.28 (+0.44%)
    Winners/Losers:     7 / 5
    Exposure:           56.8% (max: 65%)
    
  PERFORMANCE (Last 7 days):
    Trades:             23
    Win Rate:           60.9%
    Avg Win:            +$125
    Avg Loss:           -$63
    Sharpe:             0.92
    
  FILES:
    Decisions:          data/decisions/
    Log:                logs/paper_demo_20260422_113354.log
============================================================
```

**Priority:** High

---

## Missing Sections (Should Add)

### 🔴 CRITICAL: Section 10 - Reconciliation (missing)

**Purpose:** Verify orders were submitted correctly

**Should show:**
```
-- 10. Reconciliation ------------------------------------
  Orders submitted:     1
  Orders confirmed:     1 (100%)
  
  [CRM] BUY 10 @ market
    Submitted:          02:34:00
    Broker ID:          abc123-def456
    Status:             submitted → pending_new
    Confirmation:       OK
```

**Priority:** 🔴 Critical (this section exists but not shown in dry-run)

---

### ⚠️ Section 11 - Performance Context (missing)

**Purpose:** Show recent performance trends

**Should show:**
```
-- 11. Performance Context -------------------------------
  Last 7 Days:
    Equity:             $100,000 → $103,737 (+3.74%)
    Best Day:           +$1,320 (Apr 20)
    Worst Day:          -$1,539 (Apr 21)
    Win Rate:           60.9% (14W / 9L)
    
  Current Week (Apr 21-27):
    Equity:             +$516 (+0.50%)
    Trades:             5 (3W / 2L)
    Avg Hold:           2.3 days
```

**Priority:** Medium

---

## Information Quality Assessment

### ✅ Complete & Accurate

1. Runtime mode
2. Kill switch status
3. Data collection
4. Position details (newly added)

### ⚠️ Present but Incomplete

1. Market hours (missing time context)
2. Broker info (missing margin/usage)
3. Feature computation (missing ATR, sector)
4. Decision engine (missing risk metrics)
5. Summary (too minimal)

### 🔴 Critical Gaps

1. **Exit signal analysis** - Why 0 exits? Which positions close to exit?
2. **Risk utilization** - How much exposure capacity left?
3. **Performance trends** - Daily/weekly context
4. **Sector analysis** - Concentration, limits
5. **Denial reasons** - Why were signals rejected?

---

## Visibility Issues (見切れ)

### Currently NO truncation issues ✅

All fields display correctly with current data:
- Symbol names: 6 chars (adequate)
- Prices: up to $999.99 (adequate)
- P&L: up to $999.99 (adequate)
- Percentages: up to 99.99% (adequate)

### Potential future issues:

1. **If stock price > $1000:**
   - Current: `$   246.47`
   - With $1200: `$  1200.00` (ok)
   - With $12000: `$ 12000.00` (might overflow)
   
   **Fix:** Use dynamic width or abbreviations ($12.0k)

2. **If position > 999 shares:**
   - Current: `   55`
   - With 1250: ` 1250` (might overflow)
   
   **Fix:** Use wider column or abbreviations (1.25k)

3. **If P&L > $9,999:**
   - Current: `$   125.42`
   - With $12,500: `$ 12500.00` (will overflow)
   
   **Fix:** Use abbreviations ($12.5k)

**Priority:** Low (unlikely scenarios, but good to address proactively)

---

## Improvement Priorities

### 🔴 CRITICAL (Week 3 Must-Have)

1. **Exit Signal Details**
   - Show WHY no exits
   - Show positions close to exit criteria
   - Show risk/reward per position

2. **Risk Metrics**
   - Exposure utilization
   - Sector concentration
   - Available capacity

3. **Strategy Effectiveness**
   - Entry signal quality indicators
   - Expected vs actual outcomes
   - Confidence validation

### ⚠️ HIGH (Week 3 Should-Have)

4. **Performance Context**
   - Daily change
   - Weekly trend
   - Key metrics (win rate, Sharpe)

5. **Enhanced Summary**
   - Recent performance
   - Portfolio state
   - Execution statistics

### 🟡 MEDIUM (Week 4+)

6. **Market Hours Enhancement**
   - Time until open
   - Next market schedule

7. **Broker Account Details**
   - Margin usage
   - Day trade count

8. **Feature Computation Enhancement**
   - ATR per symbol
   - Sector labeling

---

## Recommended Implementation

### Phase 1 (This Week - for Week 3 optimization)

**Priority: Exit signal analysis + Risk metrics**

```python
# Add to Section 7
def _print_exit_analysis(current_positions, features):
    print("  Exit Signal Analysis:")
    
    positions_checked = len(current_positions)
    
    # Find closest to exit criteria
    closest_stop = min(..., key=lambda x: x['distance_to_stop'])
    closest_profit = min(..., key=lambda x: x['distance_to_profit'])
    over_hold = [p for p in positions if p['hold_days'] > MAX_HOLD]
    
    print(f"    Positions checked:       {positions_checked}")
    print(f"    Closest to stop loss:    {closest_stop['symbol']} "
          f"({closest_stop['pnl_pct']:.2f}%, need {STOP_LOSS_PCT:.2f}%)")
    print(f"    Closest to take profit:  {closest_profit['symbol']} "
          f"({closest_profit['pnl_pct']:.2f}%, need {TAKE_PROFIT_PCT:.2f}%)")
    if over_hold:
        print(f"    Over hold limit:         {len(over_hold)} positions")
    print()

# Add to Section 8  
def _print_risk_metrics(equity, current_positions, regime):
    total_value = sum(p['market_value'] for p in current_positions.values())
    exposure_pct = total_value / equity * 100
    max_exposure = REGIME_LIMITS[regime] * 100
    
    print("  Risk Metrics:")
    print(f"    Total Exposure:          ${total_value:,.2f} ({exposure_pct:.1f}%)")
    print(f"    Max Allowed:             ${equity * REGIME_LIMITS[regime]:,.2f} ({max_exposure:.0f}%)")
    print(f"    Available Capacity:      ${equity * REGIME_LIMITS[regime] - total_value:,.2f}")
    print()
```

**Effort:** 2-3 hours  
**Impact:** High (critical for optimization decisions)

---

### Phase 2 (Week 4)

**Priority: Enhanced summary + Performance context**

```python
def _print_enhanced_summary(decisions, equity, daily_change, metrics):
    print("  ACCOUNT:")
    print(f"    Current Equity:     ${equity:,.2f}")
    print(f"    Daily Change:       ${daily_change:+,.2f} ({daily_change/equity*100:+.2f}%)")
    print(f"    Since Start:        ${equity - 100000:+,.2f} ({(equity/100000-1)*100:+.2f}%)")
    print()
    print("  PORTFOLIO:")
    print(f"    Open Positions:     {metrics['open_positions']}")
    print(f"    Total P&L:          ${metrics['total_pnl']:+,.2f}")
    print(f"    Winners/Losers:     {metrics['winners']} / {metrics['losers']}")
    print(f"    Exposure:           {metrics['exposure_pct']:.1f}% (max: {metrics['max_pct']:.0f}%)")
    print()
    print("  RECENT PERFORMANCE (7 days):")
    print(f"    Win Rate:           {metrics['win_rate_7d']:.1f}%")
    print(f"    Avg Win:            ${metrics['avg_win_7d']:,.2f}")
    print(f"    Sharpe:             {metrics['sharpe_7d']:.2f}")
```

**Effort:** 3-4 hours  
**Impact:** Medium (better visibility, not critical for optimization)

---

## Conclusion

**Overall Rating:** 7/10 (Good foundation, needs strategic enhancements)

**Critical for Week 3:**
1. Exit signal analysis
2. Risk metrics
3. Strategy effectiveness indicators

**Current Strengths:**
- Position details now excellent
- Clear structure
- Good error handling

**Must Fix:**
- Exit signal visibility
- Risk utilization metrics
- Performance context

---

**Recommendation:** Implement Phase 1 (exit analysis + risk metrics) before Week 3 optimization starts on Apr 24.

---

End of Review Report
