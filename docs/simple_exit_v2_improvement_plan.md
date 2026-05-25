# Simple Exit V2 Improvement Plan

## Overview
Improving the quality and performance of the exit strategy to maximize profits while minimizing unnecessary losses. The focus is on implementing a dynamic stop approach that adjusts to market conditions.

## Objectives
- Introduce adaptable exit points based on volatility and trend strength.
- Optimize average returns and minimize losses by implementing early exit techniques.

## Key Components
### Dynamic Stop
- Implement a trailing stop that adjusts based on real-time price movements.
- Utilize indicators such as ATR (Average True Range) to set adaptive stop limits.

### Volatility-aware Adjustments
- Analyze market volatility to dynamically adjust stop-loss parameters.
- Enhance the probability of capturing favourable price movements while avoiding premature exits.

### Performance Metrics
- Evaluate exit strategy success by comparing P&L, win rates, and drawdown.
- Focus on improving P&L and reducing maximum drawdowns.

## Evaluation
- Conduct backtesting using historical trade data.
- Monitor improvement in average return per trade and overall portfolio health.

## Implementation
- Document finalized rules and adjustments.
- Develop testing scripts to continuously validate adjustments.
- Gradually roll out improvements across trading strategies.

## Near-term Improvement Candidates
### Candidate: conservative stalled-winner filter (C6)
- Status: shortlist candidate for future improvement review
- Rule: exit when `hold_days >= 6` and `peak_return_pct < 5%` and `current_return_pct < 0.5%`
- Intent: clean up stagnant weak positions without cutting small winners too early

### Why C6 is currently preferred among stalled-winner variants
- In the 2026-05-23 first-pass comparison, baseline remained best on closed-trade replay.
- Among stalled-winner variants, C6 was the most conservative and operationally reasonable.
- It did not worsen closed-trade replay results versus baseline in the tested window.
- On open-position snapshot review, it flagged `GOOGL` while leaving `GTOP` untouched, matching the intended behavior of trimming stagnant losers while preserving marginal winners.

### Evaluation plan for C6
- Keep C6 as the primary stalled-winner candidate in `scripts/compare_exit_variants.py`.
- Continue monitoring open-position decisions alongside baseline and the original C variant.
- Re-evaluate after accumulating longer holding-period samples and more trades where stalled-winner logic can actually trigger.
- Do not promote to production default until it shows either realized PnL benefit or clear operational benefit in live open-position management.

---

This document will serve as a living guideline for implementing and refining the simple exit V2 strategy with a focus on adaptive, market-aware exit techniques. Further adjustments will be made based on ongoing analysis and feedback.
