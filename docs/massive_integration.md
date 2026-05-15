# Massive API Integration

## Overview

Massive (formerly Polygon.io) provides high-quality market data via REST and WebSocket APIs.

**Plan:** Basic
**API Key:** Configured in `.env` as `MASSIVE_API_KEY`

## Features

### Implemented (Phase 1)

✅ **REST API Client** (`src/stock_swing/sources/massive_client.py`)
- Historical OHLC bars (minute/daily)
- Technical indicators (SMA, RSI)
- Ticker metadata

✅ **Data Quality Comparison** (`scripts/compare_bars_quality.py`)
- Compare Alpaca vs Massive bars
- Identify gaps/differences
- Validate data accuracy

### Planned (Phase 2)

- [ ] WebSocket real-time feeds
- [ ] Console integration for live prices
- [ ] Unrealized PnL real-time updates

### Planned (Phase 3)

- [ ] Options data (Greeks, IV)
- [ ] Put/Call ratio for sentiment
- [ ] Advanced technical indicators

## Usage

### Fetch Daily Bars

```python
from src.stock_swing.sources.massive_client import MassiveClient

client = MassiveClient()
bars = client.fetch_daily_bars(
    "NVDA",
    from_date="2026-04-01",
    to_date="2026-05-12"
)

for bar in bars:
    print(f"{bar.timestamp}: ${bar.close:.2f} (vol: {bar.volume:,})")
```

### Fetch Minute Bars

```python
# Get 1-minute bars
bars = client.fetch_minute_bars(
    "NVDA",
    from_date="2026-05-01",
    to_date="2026-05-12",
    multiplier=1  # 1 = 1-minute, 5 = 5-minute, etc.
)
```

### Fetch Technical Indicators

```python
# Get SMA(20)
sma_values = client.fetch_sma("NVDA", window=20)

# Get RSI(14)
rsi_values = client.fetch_rsi("NVDA", window=14)
```

### Compare Data Quality

```bash
# Compare Alpaca vs Massive for last 20 days
python scripts/compare_bars_quality.py --symbol NVDA --days 20

# Compare 5-minute bars
python scripts/compare_bars_quality.py --symbol NVDA --days 5 --timeframe 5Min

# Compare daily bars
python scripts/compare_bars_quality.py --symbol NVDA --days 365 --timeframe 1Day
```

## API Limits

**Basic Plan:**
- Real-time data: No (15-minute delay)
- Rate limit: ~5 requests/minute
- Historical data: ✅ Full access

**Recommendations:**
- Use for **historical backtesting** (high quality bars)
- Use for **technical indicator validation** (API-computed SMA/RSI vs self-computed)
- **Not suitable** for real-time trading (15-min delay)
- Consider Starter plan ($29/mo) for WebSocket real-time feeds

## Integration Roadmap

### Week 1 (2026-05-12 - 05-18)
- [x] Install Massive Python client
- [x] Create `MassiveClient` wrapper
- [x] Test API connection
- [x] Create comparison script
- [ ] Run comprehensive data quality comparison (NVDA, AMD, AAPL)
- [ ] Decide: Use Massive bars vs Alpaca bars

### Week 2 (2026-05-19 - 05-25)
- [ ] If Massive bars are better: Integrate into `collect_data.py`
- [ ] Update feature_engine to use minute-level bars
- [ ] Run backtest with improved data
- [ ] Measure precision/recall improvement

### Week 3+ (If needed)
- [ ] Upgrade to Starter plan for WebSocket
- [ ] Integrate WebSocket into console
- [ ] Add live ticker display
- [ ] Real-time unrealized PnL

## Files

- `src/stock_swing/sources/massive_client.py` - Client wrapper
- `scripts/compare_bars_quality.py` - Data quality comparison tool
- `docs/massive_integration.md` - This file
- `.env` - Contains `MASSIVE_API_KEY`

## WebSocket Configuration (Business Plan)

**IMPORTANT: The default WebSocket documentation shows generic endpoints.**
**For Business plan accounts, use the contract-specific endpoints below:**

### Correct WebSocket Connection
```bash
# Connect to Business plan WebSocket
wscat -c wss://nasdaq-basic-business.massive.com/stocks
```

### Authentication
```json
{"action":"auth", "params":"jWjKRcHk7x8_egXHGCGrbWnS67dPgWtp"}
```

### Subscribe to Real-time Data
```json
# Subscribe to 1-minute aggregate bars
{"action":"subscribe", "params":"AM.AAPL,AM.MSFT"}

# Data format examples:
# AM.AAPL = Apple 1-minute aggregate bars
# AM.MSFT = Microsoft 1-minute aggregate bars
```

### Key Differences from Default Docs
| Item | Default (Free tier) | Business Plan (Contract) |
|------|---------------------|-------------------------|
| WebSocket URL | `wss://socket.massive.com/stocks` | `wss://nasdaq-basic-business.massive.com/stocks` |
| Auth Method | API key in header | `{"action":"auth", "params":"<token>"}` |
| Real-time Access | 15-min delay | Real-time |

⚠️ **Note**: Always use contract-specific credentials when logged into the Business plan account.

## References

- [Massive Docs](https://massive.com/docs/) (⚠️ Shows default endpoints - use contract-specific URLs above)
- [Python Client GitHub](https://github.com/massive-com/client-python)
- [REST API Quickstart](https://massive.com/docs/rest/quickstart)
- [WebSocket Docs](https://massive.com/docs/websocket/overview) (⚠️ Generic docs - see Business plan config above)
