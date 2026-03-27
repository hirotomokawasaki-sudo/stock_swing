

# Stock Swing Web Console

Web-based operations console for monitoring and managing the stock_swing trading system.

## Features

- **Overview Dashboard**: System health, cron jobs status, data counts
- **Cron Jobs**: View all scheduled jobs and their next run times
- **Data Status**: Monitor data pipeline stages and freshness
- **Logs**: Access system logs (coming soon)
- **Auto-refresh**: Updates every 30 seconds

## Quick Start

```bash
# Start the console
cd ~/stock_swing/console
python3 app.py

# Or use the startup script
./start.sh
```

Then open your browser to: **http://localhost:3333**

## Health Check

```bash
curl http://localhost:3333/health
```

## API Endpoints

- `GET /health` - Health check
- `GET /api/dashboard` - Complete dashboard data
- `GET /api/overview` - Overview summary
- `GET /api/cron_jobs` - Cron jobs information
- `GET /api/system_status` - System status

## Stopping the Console

```bash
# Find and kill the process
pkill -f "console/app.py"

# Or if running in foreground, press Ctrl+C
```

## Architecture

```
console/
├── app.py                  # HTTP server
├── ui/
│   ├── index.html         # Main page
│   ├── app.js             # Frontend logic
│   └── style.css          # Styles
├── services/
│   └── dashboard_service.py  # Data aggregation
├── adapters/
│   ├── cron_adapter.py    # Cron jobs data
│   ├── data_adapter.py    # Data storage status
│   └── system_adapter.py  # System health
└── utils/
    └── time_utils.py      # Time utilities
```

## Requirements

- Python 3.10+
- Project root: ~/stock_swing
- Cron jobs backup: ~/stock_swing/cron_backup/jobs.json

## Port

Default: **3333**

To change, edit `PORT` in `app.py`.

## Security

- Runs on localhost (0.0.0.0:3333)
- Read-only dashboard (no write operations yet)
- Future: Add authentication if exposing externally

## Development

The console watches for changes in:
- Python files in `adapters/`, `services/`, `utils/`
- UI files: `ui/*.{js,css,html}`

Auto-reload is built-in when running via `python3 app.py`.

## Troubleshooting

### Console won't start
- Check if port 3333 is already in use: `lsof -i :3333`
- Verify Python 3.10+ is installed

### No data showing
- Verify cron_backup/jobs.json exists
- Check that data/ directory has files
- Ensure config/runtime/current_mode.yaml exists

### API errors
- Check console output for Python exceptions
- Verify project_root path is correct

---

**Last Updated**: 2026-03-27
