# StockSwing Version History

## Version 3.0.0 (2026-05-12)

**Major Release: Intraday Momentum + VWAP Integration**

### New Features

#### Massive API Integration
- Added Massive.com as primary market data source
- VWAP (Volume Weighted Average Price) data integration
- Transaction count tracking
- 5-minute bar data collection
- Higher quality historical data (100% coverage, no gaps)

#### Intraday Momentum Feature
- `IntradayMomentumFeature` class for minute-level analysis
- Parameters (optimal from grid search):
  - Lookback bars: 25
  - Smoothing window: 5
  - VWAP threshold: 0.5%
  - Momentum threshold: 0.3%
- Metrics computed:
  - Smoothed momentum (noise-reduced)
  - VWAP signal (above/below/neutral)
  - Intraday volatility
  - Volume trend
  - Risk metrics (ATR-based)

#### Hybrid Strategy
- Combines Daily + Intraday momentum
- Signal confidence boosting when both align
- +20% confidence boost for intraday-confirmed signals
- VWAP filter to reduce false positives

### Performance Improvements

**Backtested on 60 days of data:**

| Metric | Ver2 (Daily) | Ver3 (Hybrid) | Improvement |
|--------|--------------|---------------|-------------|
| **Win Rate** | 69.23% | **76.4%** | **+7.2%** |
| Avg Return | 2.93% | 2.88% | -1.7% |
| Total Trades | 65 | 55 | -15% (more selective) |
| Total Return | 190.49% | 158.5% | -16.8% (fewer trades) |
| Sharpe Ratio | ~0.40 | 0.43 | +7.5% |

**Key Insight:** Ver3 produces higher quality signals (better win rate) with fewer false positives.

### Technical Changes

#### New Files
```
src/stock_swing/sources/massive_client.py                    - Massive API wrapper
src/stock_swing/feature_engine/intraday_momentum_feature.py  - Intraday momentum
config/features/intraday_momentum.yaml                       - Optimal parameters
docs/massive_integration.md                                  - Integration guide
docs/paper_demo_integration_guide.md                         - Paper demo guide
scripts/backtest_momentum_comparison.py                      - Backtest comparison
scripts/backtest_grid_search.py                              - Parameter optimization
```

#### Modified Files
```
src/stock_swing/cli/paper_demo.py        - Hybrid strategy integration
src/stock_swing/cli/collect_data.py      - Massive source support
requirements.txt                          - massive>=2.7.0
.env                                      - MASSIVE_API_KEY
```

#### New Environment Variables
```bash
MASSIVE_API_KEY                  - Massive API authentication
PAPER_DEMO_USE_INTRADAY=true    - Enable/disable intraday feature
```

### Configuration

**Optimal parameters (from grid search):**
```yaml
# config/features/intraday_momentum.yaml
lookback_bars: 25
smoothing_window: 5
vwap_threshold: 0.005
signal_criteria:
  momentum_threshold: 0.003
  vwap_filter: true
```

### Migration Notes

Ver2 → Ver3 is backward compatible:
- Intraday feature is opt-in via `PAPER_DEMO_USE_INTRADAY`
- Falls back to daily-only if 5-minute data unavailable
- No breaking changes to existing strategies

### Testing

- **Unit tests:** 15 passed
- **Integration tests:** All passed
- **Backtest validation:** 48 parameter combinations tested
- **Dry run:** Successful

### Known Limitations

- Massive Basic plan has 15-minute delay (acceptable for swing trading)
- 5-minute bars require more API calls (rate limit: 5 req/min)
- Intraday feature requires market hours data (weekends have limited bars)

### Credits

- Massive.com for high-quality market data
- Grid search optimization: 60 days × 5 symbols × 48 configs
- Backtesting framework improvements

---

## Version 2.0.0 (2026-05-11)

**Account Migration & Console Improvements**

### Major Changes
- Alpaca account migration (2bf02097 → 9a0de1fb)
- PnL tracking reset with baseline preservation
- Archive management for historical performance
- Console dashboard enhancements

### Features
- Trailing stop strategy (SimpleExitV2)
- Sector diversification (prioritize_buy_signals_v2)
- Dynamic portfolio allocation
- Launchd watchdog monitoring

---

## Version 1.0.0 (Initial Release)

**Foundation: Swing Trading System**

### Core Features
- Broker integration (Alpaca paper trading)
- Daily momentum strategy
- PnL tracking
- Console dashboard
- Audit logging
- Kill switch

### Strategies
- BreakoutMomentumStrategy
- EventSwingStrategy
- SimpleExitStrategy
