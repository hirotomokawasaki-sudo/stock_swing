# STRATEGY_SCOPE.md

## Initial strategy scope
### Included
- Event-driven swing trading
- Short-term breakout / momentum
- U.S. stocks and ETFs
- Long-only or non-negative exposure structures

### Excluded
- Options as a core strategy
- Futures
- Margin strategies
- HFT / tick-level systems
- Self-modifying live strategies

## Initial strategy set
1. `event_swing_v1`
2. `breakout_momentum_v1`

## Expansion rule
No new strategy may be enabled until:
- feature dependencies are documented
- signal schema is documented
- risk implications are documented
- paper validation exists
