# Stock Swing Console

Real-time monitoring and management console for the Stock Swing automated trading system.

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Virtual environment created at `venv/`
- Environment variables configured (`.env` file)

### Start Console

```bash
cd /Users/hirotomookawasaki/stock_swing
./console/manage.sh start
./console/manage.sh status
./console/manage.sh health
open http://localhost:3335
```

### Stop / Restart

```bash
./console/manage.sh stop
./console/manage.sh restart
```

### Watchdog

```bash
# one-shot health check + self-heal
./console/manage.sh watchdog-run-once

# background watchdog loop (default: every 60s)
./console/manage.sh watchdog-start
./console/manage.sh watchdog-status
./console/manage.sh watchdog-stop
```

### Ports
- **HTTP Console**: `http://localhost:3335` (default via `manage.sh`)
- **WebSocket**: `ws://localhost:3334`
- `app.py` 単体実行時の既定値は `3333` のままです。`manage.sh` は運用用に `3335` を使います。

---

## 📊 Features

### Overview Tab
- **Real-time KPIs**: Equity, P&L, Position count
- **Performance Attribution**: Alpha, Beta, Sharpe Ratio
- **Portfolio Comparison Chart**: Your portfolio vs SPY benchmark (Chart.js)
- **Period Selector**: Day / 3 Days / Week / Month / All Time
- **Daily PnL Cards**: Today / Best Day / Worst Day
- **Conversion Rate**: Today vs Cumulative

### Weekly Summary Tab
- **Weekly Statistics**: Trades, Win rate, P&L, Profit factor
- **Strategy Performance**: P&L by strategy with charts
- **Top Symbols**: Best performing symbols
- **Best/Worst Trades**: Detailed breakdown
- **Equity Progression**: Weekly equity curve

### Analysis Tab
- **Strategy Analysis**: Performance metrics by strategy
- **Symbol Analysis**: Performance metrics by symbol
- **Risk Metrics**: Sharpe ratio, Max drawdown

### Charts Tab
- **Equity Curve**: Historical equity progression
- **Drawdown**: Drawdown percentage over time
- **P&L Distribution**: Trade P&L histogram
- **Monthly Returns**: Month-over-month returns

### Trading Tab
- **Recent Trades**: Last 10 trades with P&L
- **Open Positions**: Current holdings
- **Closed Trades**: Trade history

### Positions Tab
- **Position Details**: Symbol, Qty, Entry, Current, P&L
- **Holding Days**: Average holding period
- **Sorting**: By symbol, P&L, market value
- **Filtering**: Search by symbol

### Parameters Tab
- **Parameter Management**: View and validate parameters
- **Adjustable Parameters**:
  - `max_position_size`: $100-1000 (current: $400)
  - `min_signal_strength`: 0.30-0.80 (current: 0.50)
  - `min_confidence`: 0.30-0.80 (current: 0.40)
  - `symbol_position_limit_pct`: 5-20% (current: 10%)
  - `max_sector_exposure_pct`: 50-95% (current: 80%)

---

## 🔌 API Endpoints

### Dashboard
- `GET /api/dashboard?period=month` - Full dashboard data
- `GET /api/overview` - Overview KPIs
- `GET /api/trading` - Trading performance
- `GET /api/positions` - Current positions
- `GET /api/charts` - Chart data

### Performance
- `GET /api/performance/attribution?benchmark=SPY` - Alpha, Beta, Sharpe
- `GET /api/strategy_analysis` - Strategy performance
- `GET /api/live_metrics` - Real-time metrics

### Summary
- `GET /api/summary/daily` - Daily summary with alerts
- `GET /api/summary/weekly?weeks=1` - Weekly performance summary

### Utilities
- `GET /api/conversion/daily?date=YYYY-MM-DD` - Daily conversion rate
- `GET /api/symbol/<SYMBOL>` - Symbol drilldown
- `GET /api/parameters` - Parameter list with ranges
- `GET /api/parameters/<NAME>/validate?value=X` - Validate parameter value

---

## 🎨 Technology Stack

### Backend
- **Framework**: Custom HTTP server (lightweight)
- **WebSocket**: `asyncio` + `websockets`
- **Data**: JSON files + PnL Tracker

### Frontend
- **Charts**: Chart.js 4.4.0 + Zoom Plugin 2.0.1
- **Real-time**: Native WebSocket API
- **Styling**: Custom CSS (dark theme)

### Architecture
```
┌──────────────────┐
│   Browser        │
│   - Chart.js     │
│   - WebSocket    │
└────────┬─────────┘
         │ HTTP + WS
┌────────▼─────────────────┐
│  Console Servers         │
│  - app.py (HTTP:3333)    │
│  - websocket_server.py   │
│    (WS:3334)             │
└────────┬─────────────────┘
         │
┌────────▼─────────────────┐
│  Services                │
│  - DashboardService      │
│  - BenchmarkService      │
│  - SummaryService        │
│  - ParameterService      │
└────────┬─────────────────┘
         │
┌────────▼─────────────────┐
│  Data Layer              │
│  - PnL Tracker           │
│  - Broker Client (Alpaca)│
│  - Decision Files        │
│  - Benchmark Data (SPY)  │
└──────────────────────────┘
```

---

## 🔄 Real-Time Updates

### How It Works
1. **WebSocket Server** broadcasts updates every 30 seconds
2. **Frontend** receives incremental updates
3. **No page reload** required
4. **Auto-reconnect** with 5-second retry

### Updated Data
- Equity
- Unrealized P&L
- Position count
- Trading summary

### Connection Status
- 🟢 **Connected**: WebSocket active
- 🔴 **Disconnected**: Reconnecting...
- ⚫ **Unavailable**: Using polling fallback

---

## 📈 Key Metrics

### Current Performance (2026-04-26)
- **Equity**: $105,533.91
- **Alpha**: +4.22% (outperforming SPY)
- **Beta**: 0.25 (low volatility)
- **Sharpe Ratio**: 4.19 (excellent)
- **Win Rate**: 60.6% (weekly)
- **Conversion Rate**: 28.6% (today) vs 22.3% (cumulative)

---

## 🛠️ Development

### Directory Structure
```
console/
├── app.py                   # HTTP server
├── websocket_server.py      # WebSocket server
├── services/                # Business logic
│   ├── dashboard_service.py
│   ├── benchmark_service.py
│   ├── summary_service.py
│   └── parameter_service.py
└── ui/                      # Frontend
    ├── index.html
    ├── app.js
    └── style.css
```

### Adding a New Tab
1. Add button in `ui/index.html`:
   ```html
   <button class="tab" data-tab="mytab">My Tab</button>
   ```

2. Add case in `ui/app.js`:
   ```javascript
   case 'mytab': content.innerHTML = this.renderMyTab(); break;
   ```

3. Implement render method:
   ```javascript
   renderMyTab() {
       return `<div class="card"><h3>My Tab</h3>...</div>`;
   }
   ```

### Adding a New API Endpoint
1. Add route in `app.py`:
   ```python
   if p == "/api/myendpoint":
       try:
           data = my_service.get_data()
           return self._json(data)
       except Exception as e:
           return self._json({"error": str(e)}, status=500)
   ```

2. Implement service method in `services/`:
   ```python
   def get_data(self):
       # Your logic here
       return {"result": "data"}
   ```

---

## 🐛 Troubleshooting

### Console won't start
```bash
./console/manage.sh status
./console/manage.sh health

# If needed
./console/manage.sh restart
```

### WebSocket not connecting
```bash
./console/manage.sh health
./console/manage.sh restart
```

### Data not updating
```bash
# Check PnL tracker state
ls -la data/tracking/pnl_state.json

# Check decision files
ls -la data/decisions/ | tail

# Run reconciliation manually
python scripts/reconcile_orders.py
```

---

## 📝 Configuration

### Environment Variables
Required in `.env`:
```bash
BROKER_API_KEY=<your-alpaca-api-key>
BROKER_API_SECRET=<your-alpaca-api-secret>
```

### Parameters
Adjustable via Console UI or directly in config:
- Position sizing
- Risk thresholds
- Signal strength
- Sector exposure limits

---

## 📚 Related Documentation
- [Console Improvement Tasks](../docs/console_improvement_tasks.md)
- [Daily Logs](../docs/daily_logs/)
- [Console Charts Guide](../docs/console_charts_guide.md)
- [Feature: Portfolio Comparison Chart](../docs/feature_portfolio_comparison_chart.md)

---

## 🚀 Deployment

### Production Checklist
- [ ] Update benchmark data: `python scripts/fetch_benchmark.py`
- [ ] Verify cron jobs: Check `/api/cron_jobs`
- [ ] Test WebSocket: Verify 🟢 status
- [ ] Check logs: `data/audits/paper_demo_*.log`
- [ ] Monitor conversion rate: Target 20-30%

### Monitoring
- Check console every morning
- Review weekly summary every Monday
- Update parameters as needed
- Monitor HPE short position (pending fill)

---

## 📊 Success Metrics

### Trading Performance
- ✅ Conversion Rate: 28.6% (target: 20-30%)
- ✅ Alpha: +4.22% (outperforming market)
- ✅ Sharpe Ratio: 4.19 (excellent risk-adjusted returns)
- ✅ Win Rate: 60.6% (healthy)

### System Health
- ✅ All tasks (T1-T12) completed
- ✅ Real-time updates functional
- ✅ 14 features implemented
- ✅ Production-ready status

---

**Last Updated**: 2026-04-26  
**Version**: 1.0  
**Status**: Production Ready ✅
