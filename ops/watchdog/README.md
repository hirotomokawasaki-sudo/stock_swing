# watchdog

Console supervision and fail-safe operational checks.

## Current coverage
- HTTP console (`localhost:3335` by default via `console/manage.sh`)
- WebSocket server (`localhost:3334`)

## Commands
```bash
cd /Users/hirotomookawasaki/stock_swing

# start / stop / restart console services
./console/manage.sh start
./console/manage.sh stop
./console/manage.sh restart

# status / health
./console/manage.sh status
./console/manage.sh health

# self-heal once
./console/manage.sh watchdog-run-once

# background watchdog loop
./console/manage.sh watchdog-start
./console/manage.sh watchdog-status
./console/manage.sh watchdog-stop
```

## Behavior
- Writes pid files under `.run/`
- Writes logs under `logs/`
- Restarts HTTP console if `/health` fails
- Restarts WebSocket server if the listener disappears
- Default watchdog interval: 60 seconds (`WATCHDOG_INTERVAL` で変更可)
