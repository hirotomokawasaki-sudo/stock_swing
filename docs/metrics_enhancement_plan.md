# Metrics Enhancement Plan

**Created:** 2026-04-22  
**Purpose:** Identify missing metrics for Week 3+ analysis and quality assurance  

---

## Current Baseline Metrics ✅

**What we have:**
- Total return, Sharpe ratio
- Max drawdown, peak equity
- Win rate, avg win/loss
- Signal execution rate
- Trade counts

**Limitations:**
- No exit reason tracking
- No strategy-level breakdown
- No time-based analysis
- Limited risk metrics
- No streak analysis

---

## Critical Missing Metrics (High Priority)

### 1. Exit Reason Breakdown ⭐⭐⭐⭐⭐

**Why critical:**
- Need to validate if stop loss/take profit are working
- Measure strategy effectiveness
- Identify improvement opportunities

**What to track:**
```
Exit Reasons:
  Stop Loss:        12 trades (26%)
  Take Profit:      8 trades (17%)
  Time Limit:       15 trades (33%)
  Strategy Exit:    10 trades (22%)
  Manual:           1 trade (2%)
```

**Implementation:**
- Add `exit_reason` field to PnL tracker
- Parse from decision logs
- Display in baseline metrics

**Effort:** Medium (2-3 hours)

---

### 2. Strategy-Level Performance ⭐⭐⭐⭐⭐

**Why critical:**
- Compare BreakoutMomentum vs SimpleExit effectiveness
- Identify which strategies need tuning
- Allocate optimization effort properly

**What to show:**
```
STRATEGY PERFORMANCE:
  BreakoutMomentumStrategy:
    Trades:         89 (80.9%)
    Win Rate:       52.3%
    Avg Return:     +2.1%
    Sharpe:         0.92
    
  SimpleExitStrategy:
    Trades:         21 (19.1%)
    Win Rate:       48.3%
    Avg Return:     -1.2%
    Sharpe:         0.65
```

**Implementation:**
- Group trades by strategy_id
- Calculate metrics per strategy
- Add comparison section

**Effort:** Low (1 hour)

---

### 3. Trade Duration Analysis ⭐⭐⭐⭐

**Why important:**
- Validate max_hold_days setting (currently 5)
- Understand optimal holding period
- Compare to strategy expectations

**What to show:**
```
TRADE DURATION:
  Avg Hold Time:    3.1 days
  Median:           2.5 days
  Min / Max:        0.0 / 13.7 days
  
  By Duration:
    0-2 days:       18 trades (39%)
    2-5 days:       20 trades (43%)
    5-10 days:      6 trades (13%)
    >10 days:       2 trades (5%)
    
  Performance by Duration:
    0-2 days:       +1.2% avg return
    2-5 days:       +3.1% avg return  ← Best
    5-10 days:      +0.5% avg return
    >10 days:       -2.1% avg return
```

**Implementation:**
- Calculate duration from entry_time/exit_time
- Bucket by duration
- Correlate with returns

**Effort:** Medium (1-2 hours)

---

### 4. Symbol Concentration Analysis ⭐⭐⭐⭐

**Why important:**
- Identify over-traded symbols
- Check if diversification is working
- Risk management validation

**What to show:**
```
SYMBOL CONCENTRATION:
  Total Unique Symbols:  25
  
  Top 5 Most Traded:
    MRVL:          23 trades (20.9%)  ← High concentration
    RBRK:          9 trades (8.2%)
    CIEN:          9 trades (8.2%)
    CRWD:          7 trades (6.4%)
    DELL:          7 trades (6.4%)
    
  Concentration Risk:
    Top 3 symbols:       37.3% of trades
    Top 5 symbols:       50.1% of trades
    HHI Index:           0.082 (moderate concentration)
```

**Implementation:**
- Count trades per symbol
- Calculate concentration metrics
- Add warning if too concentrated

**Effort:** Low (1 hour)

---

## Important Missing Metrics (Medium Priority)

### 5. Consecutive Win/Loss Streaks ⭐⭐⭐

**Why important:**
- Risk of ruin calculation
- Psychological impact assessment
- Drawdown prediction

**What to show:**
```
STREAK ANALYSIS:
  Max Consecutive Wins:     8
  Max Consecutive Losses:   3
  Current Streak:           2 wins
  
  Longest Winning Streak:   8 trades (+$12,450)
  Longest Losing Streak:    3 trades (-$2,100)
```

**Implementation:**
- Sort trades chronologically
- Track consecutive outcomes
- Identify longest streaks

**Effort:** Low (30 mins)

---

### 6. Drawdown Recovery Analysis ⭐⭐⭐

**Why important:**
- Understand recovery dynamics
- Set realistic expectations
- Risk management tuning

**What to show:**
```
DRAWDOWN ANALYSIS:
  Max Drawdown:           -4.34%
  Drawdown Events:        3
  
  Avg Recovery Time:      5.2 days
  Longest Recovery:       12 days
  Current Drawdown:       -0.8% (2 days old)
  
  Underwater Time:        18% of period
  Time to New High:       avg 7.1 days
```

**Implementation:**
- Track equity peaks
- Measure time to recovery
- Calculate underwater percentage

**Effort:** Medium (2 hours)

---

### 7. Time-Based Performance ⭐⭐⭐

**Why important:**
- Identify best/worst trading times
- Optimize execution schedule
- Avoid adverse periods

**What to show:**
```
PERFORMANCE BY DAY:
  Monday:     +0.8%  (avg return per trade)
  Tuesday:    +1.2%
  Wednesday:  +0.5%
  Thursday:   +2.1%  ← Best
  Friday:     -0.3%  ← Worst
  
PERFORMANCE BY WEEK:
  Week 1 (Apr 10-14):  -2.1%
  Week 2 (Apr 17-21):  +1.2%
  Week 3 (Apr 22-26):  TBD
```

**Implementation:**
- Parse dates from trades
- Group by day/week
- Calculate performance

**Effort:** Low (1 hour)

---

## Advanced Metrics (Low Priority - Week 4+)

### 8. Advanced Risk Metrics ⭐⭐

**Sortino Ratio:**
- Like Sharpe but only penalizes downside volatility
- Better for asymmetric strategies

**Calmar Ratio:**
- Return / Max Drawdown
- Measures risk-adjusted return differently

**MAR Ratio:**
- Return / Average Drawdown
- Smoother than Calmar

**Implementation:**
- Add to baseline_metrics.py
- Requires downside deviation calculation

**Effort:** Medium (2-3 hours)

---

### 9. Value at Risk (VaR) ⭐⭐

**What it shows:**
```
RISK METRICS:
  Daily VaR (95%):     -$850  (95% of days, loss < $850)
  Daily VaR (99%):     -$1,200
  Conditional VaR:     -$1,450  (avg loss beyond VaR)
```

**Why useful:**
- Risk budgeting
- Position sizing validation
- Regulatory/reporting

**Implementation:**
- Calculate from daily returns
- Percentile-based or parametric

**Effort:** Medium (2 hours)

---

### 10. Rolling Performance Windows ⭐⭐

**What it shows:**
```
ROLLING METRICS (7-day window):
  Current Sharpe:      1.2
  Peak Sharpe:         1.8
  Trough Sharpe:       0.3
  
  Rolling Win Rate:    55% (last 20 trades)
```

**Why useful:**
- Detect performance degradation
- Trigger re-optimization
- Adaptive parameter tuning

**Implementation:**
- Calculate metrics in sliding windows
- Track evolution over time

**Effort:** High (3-4 hours)

---

## Implementation Priority

### Phase 1 (This Week - For Week 3 Optimization) ⭐⭐⭐⭐⭐

**Must-have:**
1. Exit reason breakdown
2. Strategy-level performance
3. Trade duration analysis
4. Symbol concentration

**Output:** Enhanced baseline_metrics.py

**Effort:** 1 day (6-8 hours)

---

### Phase 2 (Week 4 - Risk Management) ⭐⭐⭐

**Should-have:**
5. Streak analysis
6. Drawdown recovery
7. Time-based performance

**Output:** risk_analysis.py module

**Effort:** 1 day (6-8 hours)

---

### Phase 3 (Month 2 - Advanced Analytics) ⭐⭐

**Nice-to-have:**
8. Advanced risk metrics
9. VaR analysis
10. Rolling windows

**Output:** advanced_analytics.py module

**Effort:** 2-3 days

---

## Recommended Next Steps

### Today (Apr 22) - If Time Permits

**Quick Wins (2-3 hours):**
1. ✅ Add strategy breakdown to baseline_metrics.py
2. ✅ Add symbol concentration analysis
3. ✅ Add trade duration stats

**Impact:**
- Better understanding of current system
- More informed Week 3 optimization
- Identify immediate issues (over-concentration, etc.)

---

### Tomorrow (Apr 23)

**Prepare for Week 3:**
4. ✅ Add exit reason tracking to PnL tracker
5. ✅ Parse exit reasons from decision logs
6. ✅ Update baseline metrics with new data

---

### Week 3 (Apr 24-28)

**During Optimization:**
- Use enhanced metrics to evaluate parameter changes
- Compare strategy performance before/after
- Validate improvements with multiple metrics

---

## Sample Enhanced Output

```
======================================================================
BASELINE PERFORMANCE METRICS (ENHANCED)
======================================================================

Period: 2026-04-03 to 2026-04-22
Trading Days: 86

RETURNS:
  Initial Equity:        $  100,000.00
  Final Equity:          $  102,982.49
  Total Return:                  2.98%
  Sharpe Ratio:                  0.85
  Sortino Ratio:                 1.12  ← NEW
  Calmar Ratio:                  0.69  ← NEW

RISK:
  Max Drawdown:                  4.34%
  Avg Drawdown:                  2.1%  ← NEW
  Drawdown Events:               3     ← NEW
  Avg Recovery Time:             5.2 days  ← NEW

TRADING ACTIVITY:
  Total Trades:                   110
  Closed Trades:                   46
  Open Trades:                     25
  Avg Hold Time:                   3.1 days  ← NEW
  
PERFORMANCE BY STRATEGY:                    ← NEW SECTION
  BreakoutMomentum (89 trades):
    Win Rate:                    52.3%
    Avg Return:                  +2.1%
    Sharpe:                      0.92
    
  SimpleExit (21 trades):
    Win Rate:                    48.3%
    Avg Return:                  -1.2%
    Sharpe:                      0.65

EXIT REASON BREAKDOWN:                      ← NEW SECTION
  Stop Loss:                12 (26%)
  Take Profit:              8 (17%)
  Time Limit:               15 (33%)
  Strategy Exit:            10 (22%)
  Manual:                   1 (2%)

SYMBOL CONCENTRATION:                       ← NEW SECTION
  Unique Symbols:           25
  Top Symbol (MRVL):        23 trades (20.9%)
  Top 5 Concentration:      50.1%
  HHI Index:                0.082 (moderate)

STREAK ANALYSIS:                            ← NEW SECTION
  Max Win Streak:           8 trades
  Max Loss Streak:          3 trades
  Current Streak:           2 wins

TIME-BASED PERFORMANCE:                     ← NEW SECTION
  Best Day:                 Thursday (+2.1% avg)
  Worst Day:                Friday (-0.3% avg)
  Best Week:                Week 2 (+1.2%)

======================================================================
```

---

## Questions for Master

1. **Priority confirmation:**
   - Implement Phase 1 (exit reasons, strategy breakdown, duration, concentration) this week?
   
2. **Depth preference:**
   - Full implementation or lightweight version first?
   
3. **Display format:**
   - Add to baseline_metrics.py or separate report?

---

**Recommendation:** Implement Phase 1 enhancements today/tomorrow (6-8 hours) to have better data for Week 3 optimization starting Apr 24.

---

End of Enhancement Plan
