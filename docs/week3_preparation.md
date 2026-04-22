# Week 3 Preparation: Parameter Optimization

**Preparation Date:** 2026-04-22  
**Implementation Start:** 2026-04-24 (Thursday)  
**Objective:** Optimize trading parameters using collected data  

---

## Overview

Week 3 focuses on **parameter optimization** using the 12 days of trading data collected during Weeks 1-2. We will systematically test different parameter combinations to identify optimal settings for improved performance.

---

## Current System Parameters

### Entry Strategy (BreakoutMomentumStrategy)

```python
min_momentum: 0.03  # 3% minimum momentum for signal
min_signal_strength: 0.55  # Minimum signal strength threshold
```

### Exit Strategy (SimpleExitStrategy)

```python
stop_loss_pct: -0.07  # -7% stop loss
take_profit_pct: 0.10  # +10% take profit
max_hold_days: 5  # Maximum holding period
```

### Risk Management

```python
# Position sizing
max_risk_per_trade_pct: 0.005  # 0.5% risk per trade
max_position_notional_pct: 0.08  # 8% max position size
default_stop_pct: 0.05  # 5% default stop

# Exposure limits
REGIME_LIMITS = {
    "bullish": 0.95,
    "neutral": 0.85,
    "cautious": 0.65,
    "unknown": 0.85,
}

# Sector limits
max_sector_exposure_pct: 0.50  # 50% max per sector
```

---

## Data Available for Analysis

### Dataset Summary

**Period:** April 10-22, 2026 (12 trading days)  
**Total Trades:** 110  
**Total Decisions:** 200+  
**Market Conditions:** Neutral to Bullish  

**Data Files:**
- Decision logs: `data/decisions/decision_*.json`
- PnL tracking: `data/tracking/pnl_state.json`
- Daily logs: `logs/paper_demo_cron_*.log`

### Performance Baseline

**Overall Performance:**
- Total Return: +2.98% ($100k → $102,982)
- Max Drawdown: -4.34%
- Win Rate: TBD (need to calculate)
- Average Hold Time: ~3-5 days

**By Strategy:**
- BreakoutMomentum: 90%+ of signals
- SimpleExit: Functioning (stop loss & take profit)
- EventSwing: <5% of signals (inactive)

---

## Optimization Targets

### 1. Entry Parameters

**min_momentum (Current: 3%)**

Test range: [0.02, 0.03, 0.04, 0.05, 0.07]

**Hypothesis:**
- Lower (2%): More signals, but lower quality
- Higher (5-7%): Fewer signals, but higher quality
- Current (3%): Balanced approach

**Metrics to evaluate:**
- Signal count per day
- Win rate by threshold
- Average return per signal
- False positive rate

---

**min_signal_strength (Current: 0.55)**

Test range: [0.50, 0.55, 0.60, 0.65, 0.70]

**Hypothesis:**
- Lower (0.50): More trades, potentially more noise
- Higher (0.70): Fewer trades, higher confidence
- Current (0.55): Moderate filtering

**Metrics to evaluate:**
- Signal quality vs quantity
- Win rate by strength threshold
- Average return by strength bucket

---

### 2. Exit Parameters

**stop_loss_pct (Current: -7%)**

Test range: [-0.05, -0.07, -0.10, -0.12]

**Hypothesis:**
- Tighter (-5%): Fewer large losses, more whipsaws
- Wider (-10-12%): Fewer exits, but larger losses
- Current (-7%): Middle ground

**Metrics to evaluate:**
- Average loss when stopped
- Stop-out frequency
- Recovery rate (would have recovered if held)

---

**take_profit_pct (Current: +10%)**

Test range: [0.08, 0.10, 0.12, 0.15]

**Hypothesis:**
- Lower (8%): More frequent profits, smaller size
- Higher (15%): Larger profits, but fewer
- Current (10%): Balanced

**Metrics to evaluate:**
- Profit capture rate
- Average profit when exited
- Missed profit opportunity (continued up after exit)

---

**max_hold_days (Current: 5)**

Test range: [3, 5, 7, 10]

**Hypothesis:**
- Shorter (3): Faster churn, less exposure
- Longer (10): More trend capture, more risk
- Current (5): Swing trading timeframe

**Metrics to evaluate:**
- Average P&L by hold duration
- Optimal exit timing
- Time decay of signal strength

---

## Optimization Framework Design

### Approach: Grid Search with Walk-Forward Validation

**Method:**
1. Split data into training and validation sets
2. Test all parameter combinations on training set
3. Validate best performers on validation set
4. Select optimal parameters with statistical significance

**Validation Strategy:**
```
Training: Days 1-8 (Apr 10-18)
Validation: Days 9-12 (Apr 19-22)
```

### Evaluation Metrics

**Primary Metrics:**
1. **Sharpe Ratio** (risk-adjusted return)
2. **Win Rate** (% of profitable trades)
3. **Profit Factor** (gross profit / gross loss)
4. **Max Drawdown** (largest peak-to-trough decline)

**Secondary Metrics:**
5. Average Win / Average Loss ratio
6. Trade frequency (signals per day)
7. Average holding period
8. Recovery time from drawdowns

### Statistical Validation

**Criteria for acceptance:**
- Minimum 20 trades in backtest
- Win rate > 50%
- Sharpe ratio > 1.0
- Max drawdown < 10%
- Statistically significant improvement over baseline (t-test)

---

## Implementation Plan

### Phase 1: Data Preparation (Day 1 - Apr 24)

**Tasks:**
1. Extract historical data from decision logs
2. Parse P&L tracking data
3. Build position reconstruction logic
4. Create clean dataset for backtesting

**Deliverable:** `data/processed/backtest_dataset.json`

**Script:** `src/stock_swing/analysis/prepare_backtest_data.py`

---

### Phase 2: Backtest Engine (Day 1-2 - Apr 24-25)

**Tasks:**
1. Implement parameter grid search
2. Build position simulator
3. Calculate performance metrics
4. Add statistical validation

**Deliverable:** `src/stock_swing/optimization/backtest_engine.py`

**Core Logic:**
```python
class BacktestEngine:
    def run_backtest(self, params: dict) -> BacktestResult:
        """
        Simulate trading with given parameters
        Returns: metrics, trades, equity curve
        """
        
    def grid_search(self, param_grid: dict) -> List[BacktestResult]:
        """
        Test all parameter combinations
        Returns: sorted results by Sharpe ratio
        """
        
    def validate(self, params: dict, validation_data: list) -> BacktestResult:
        """
        Validate parameters on out-of-sample data
        Returns: validation metrics
        """
```

---

### Phase 3: Parameter Testing (Day 2-3 - Apr 25-26)

**Tasks:**
1. Run grid search on training set
2. Identify top 5 parameter sets
3. Validate on validation set
4. Compare to baseline performance

**Test Matrix:**
```
min_momentum: [0.02, 0.03, 0.04, 0.05, 0.07]  (5 values)
min_signal_strength: [0.50, 0.55, 0.60, 0.65, 0.70]  (5 values)
stop_loss_pct: [-0.05, -0.07, -0.10, -0.12]  (4 values)
take_profit_pct: [0.08, 0.10, 0.12, 0.15]  (4 values)
max_hold_days: [3, 5, 7, 10]  (4 values)

Total combinations: 5 × 5 × 4 × 4 × 4 = 1,600 tests
```

**Optimization:**
- Run most promising combinations first
- Prune obviously poor performers early
- Focus on top 100 combinations for deep analysis

---

### Phase 4: Analysis & Recommendations (Day 3-4 - Apr 26-27)

**Tasks:**
1. Generate performance comparison report
2. Statistical significance testing
3. Risk/reward analysis
4. Parameter sensitivity analysis
5. Final recommendations

**Deliverable:** `docs/reports/parameter_optimization_results.md`

**Report Contents:**
- Best performing parameter sets
- Performance comparison table
- Equity curve comparisons
- Risk metrics comparison
- Sensitivity analysis (which parameters matter most)
- Recommended parameter updates

---

### Phase 5: Implementation (Day 5 - Apr 28)

**Tasks:**
1. Update configuration files with optimal parameters
2. Deploy to production (if approved)
3. Monitor initial performance
4. Document changes

**Files to update:**
```
src/stock_swing/strategy_engine/breakout_momentum_strategy.py
src/stock_swing/strategy_engine/simple_exit_strategy.py
src/stock_swing/risk/position_sizing.py
```

---

## Risk Management During Optimization

### Safeguards

1. **Overfitting Prevention:**
   - Use walk-forward validation
   - Require statistical significance
   - Minimum sample size (20+ trades)
   - Conservative parameter selection

2. **Gradual Rollout:**
   - Test new parameters in dry-run first
   - Monitor for 2-3 days before full deployment
   - Keep rollback option ready

3. **Performance Bounds:**
   - Max drawdown limit: 15%
   - Minimum win rate: 45%
   - Maximum position size: unchanged
   - Exposure limits: unchanged

---

## Success Criteria

### Minimum Requirements

- ✅ Sharpe ratio improvement > 0.2
- ✅ Win rate improvement > 5%
- ✅ Max drawdown reduction OR acceptable increase (<2%)
- ✅ Statistical significance (p < 0.05)

### Stretch Goals

- 🎯 Sharpe ratio > 1.5
- 🎯 Win rate > 55%
- 🎯 Profit factor > 2.0
- 🎯 Average win/loss > 1.5

---

## Tools & Scripts to Build

### 1. Data Extraction Script

**File:** `src/stock_swing/analysis/prepare_backtest_data.py`

**Purpose:** Convert raw logs to structured backtest data

**Output Format:**
```json
{
  "trades": [
    {
      "symbol": "AAPL",
      "entry_date": "2026-04-10",
      "entry_price": 150.00,
      "exit_date": "2026-04-15",
      "exit_price": 155.00,
      "pnl": 5.00,
      "pnl_pct": 0.033,
      "hold_days": 5,
      "signal_strength": 0.75,
      "momentum": 0.045,
      "exit_reason": "take_profit"
    }
  ],
  "daily_snapshots": [...],
  "signals": [...]
}
```

---

### 2. Backtest Engine

**File:** `src/stock_swing/optimization/backtest_engine.py`

**Key Methods:**
```python
def simulate_strategy(data, params):
    """Run simulation with given parameters"""
    
def calculate_metrics(equity_curve, trades):
    """Calculate all performance metrics"""
    
def grid_search(data, param_grid):
    """Test all combinations"""
    
def validate_params(params, validation_data):
    """Out-of-sample validation"""
```

---

### 3. Reporting Tool

**File:** `src/stock_swing/optimization/generate_report.py`

**Output:**
- Markdown report with tables
- Performance charts (equity curves)
- Parameter sensitivity heatmaps
- Statistical test results

---

## Timeline Summary

| Day | Date | Tasks | Deliverables |
|-----|------|-------|--------------|
| **Day 1** | Apr 24 (Thu) | Data prep + Engine start | Dataset ready |
| **Day 2** | Apr 25 (Fri) | Engine complete + Testing start | Backtest engine |
| **Day 3** | Apr 26 (Sat) | Testing + Analysis | Test results |
| **Day 4** | Apr 27 (Sun) | Analysis + Report | Optimization report |
| **Day 5** | Apr 28 (Mon) | Review + Deploy | Updated parameters |

---

## Expected Outcomes

### Best Case Scenario

- Sharpe ratio: 1.2 → 1.8 (+50%)
- Win rate: 50% → 58% (+8pp)
- Max drawdown: 4.3% → 3.5% (-0.8pp)
- **Result:** Deploy new parameters immediately

### Realistic Scenario

- Sharpe ratio: 1.2 → 1.4 (+17%)
- Win rate: 50% → 53% (+3pp)
- Max drawdown: 4.3% → 4.5% (+0.2pp)
- **Result:** Deploy with monitoring

### Worst Case Scenario

- No significant improvement found
- Current parameters are near-optimal
- **Result:** Keep current settings, learn from analysis

---

## Next Steps (Today - Apr 22)

### Immediate Actions

1. ✅ **Review this preparation document**
2. ⏳ **Extract decision logs**
   ```bash
   cd ~/stock_swing
   python -m src.stock_swing.analysis.extract_decisions
   ```
3. ⏳ **Analyze current performance**
   ```bash
   python -m src.stock_swing.analysis.baseline_metrics
   ```

### Tomorrow (Apr 23)

- Refine parameter ranges based on initial analysis
- Design backtest engine architecture
- Set up testing infrastructure

### Thursday (Apr 24) - Week 3 Starts

- Begin implementation of backtest engine
- Start data preparation pipeline
- Initial parameter testing

---

**Preparation Status:** 📋 Documented, ready to begin implementation

**Questions for Master:**
1. Approve this optimization approach?
2. Any specific parameters to prioritize?
3. Risk tolerance for parameter changes?

---

End of Preparation Document
