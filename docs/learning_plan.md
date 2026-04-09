# stock_swing Learning & Optimization Plan

## Week 1: Baseline Data Collection (Apr 10-16, 2026)

### Daily Tasks
- [ ] Review morning report (23:25 JST run)
- [ ] Review evening report (05:55 JST run)
- [ ] Log observations in `docs/observations/`

### Metrics to Track
1. **Signal Quality**
   - Total signals generated per day
   - Breakout vs EventSwing ratio
   - Signal strength distribution

2. **Execution**
   - Actionable vs denied ratio
   - Common denial reasons
   - Order fill rates

3. **Performance**
   - Daily PnL
   - Win rate (% of profitable positions)
   - Average holding period
   - Max drawdown

4. **Risk Utilization**
   - Exposure usage (current / max)
   - Sector concentration
   - Position size distribution

### End of Week Analysis
```bash
cd ~/stock_swing
python -m stock_swing.cli.analyze_performance --start-date 2026-04-10 --end-date 2026-04-16
```

**Output:**
- Weekly performance summary
- Parameter recommendations
- Risk utilization report

---

## Week 2: Parameter Validation (Apr 17-23, 2026)

### Focus Areas
1. **Momentum Threshold Analysis**
   - Current: 5% minimum
   - Test scenarios: 3%, 7%, 10%
   - Measure: signal count vs quality

2. **False Positive Investigation**
   - Signals that resulted in losses
   - Common characteristics
   - Filter improvements

3. **Regime Detection**
   - Accuracy of bullish/cautious classification
   - Performance by regime
   - Adjustment needs

### Implementation Tasks
- [ ] Add backtesting script for parameter sweeps
- [ ] Create signal quality metrics
- [ ] Build regime accuracy validator

---

## Week 3: Strategy Tuning (Apr 24-30, 2026)

### Experiments
1. **Confidence Weighting**
   - Adjust position sizing by confidence
   - Test: high confidence = 1.5x, low = 0.5x

2. **Sector Diversification**
   - Enforce max 3 positions per sector
   - Measure impact on drawdown

3. **Time-of-Day Optimization**
   - Compare pre-market vs mid-day vs close signals
   - Best execution timing

### Config Changes
```yaml
# config/strategy/breakout_momentum_v1.yaml
min_momentum: [test 0.03, 0.05, 0.07]
min_signal_strength: [test 0.5, 0.6, 0.7]
confidence_boost: [test 1.0, 1.2, 1.5]
```

---

## Week 4: Risk Management Enhancement (May 1-7, 2026)

### New Features
1. **Stop Loss Automation**
   - Implement trailing stops
   - Test 5%, 7%, 10% levels

2. **Position Duration Limits**
   - Auto-close after N days
   - Test: 3, 5, 7 days

3. **Drawdown Protection**
   - Pause trading if portfolio down >10%
   - Reduce position sizes if down >5%

4. **Loss Streak Protection**
   - Reduce exposure after 3 consecutive losses
   - Reset after 1 win

### Implementation
- [ ] Add `src/stock_swing/risk/stop_loss_manager.py`
- [ ] Extend `kill_switch.py` with drawdown conditions
- [ ] Create position age tracker

---

## Ongoing: Weekly Review Checklist

Every Sunday:
1. Run performance analysis
2. Review parameter recommendations
3. Update this plan based on findings
4. Commit observations to Git
5. Adjust next week's focus

---

Last updated: 2026-04-09
Next review: 2026-04-16
