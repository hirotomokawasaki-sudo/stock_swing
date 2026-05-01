#!/bin/bash
# Console process manager for stock_swing.
# Usage:
#   ./console/manage.sh start
#   ./console/manage.sh stop
#   ./console/manage.sh restart
#   ./console/manage.sh status
#   ./console/manage.sh health
#   ./console/manage.sh watchdog-start
#   ./console/manage.sh watchdog-stop
#   ./console/manage.sh watchdog-status

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$ROOT/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
RUN_DIR="$PROJECT_ROOT/.run"
SCRIPT_PATH="$ROOT/manage.sh"

CONSOLE_PORT="${CONSOLE_PORT:-3335}"
CONSOLE_HOST="${CONSOLE_HOST:-0.0.0.0}"
CONSOLE_WS_PORT="${CONSOLE_WS_PORT:-3334}"
CONSOLE_WS_HOST="${CONSOLE_WS_HOST:-127.0.0.1}"
WATCHDOG_INTERVAL="${WATCHDOG_INTERVAL:-60}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/venv/bin/python}"

HTTP_PID_FILE="$RUN_DIR/console_http.pid"
WS_PID_FILE="$RUN_DIR/console_ws.pid"
WATCHDOG_PID_FILE="$RUN_DIR/console_watchdog.pid"
HTTP_LOG_FILE="$LOG_DIR/console_http.log"
WS_LOG_FILE="$LOG_DIR/console_websocket.log"
WATCHDOG_LOG_FILE="$LOG_DIR/console_watchdog.log"
HTTP_LATEST_LINK="$LOG_DIR/console_latest.log"

ensure_dirs() {
  mkdir -p "$LOG_DIR" "$RUN_DIR"
}

require_python() {
  if [ ! -x "$PYTHON_BIN" ]; then
    echo "❌ Python not found: $PYTHON_BIN"
    echo "   Create or fix the virtualenv first."
    exit 1
  fi
}

read_pid() {
  local pid_file="$1"
  if [ -f "$pid_file" ]; then
    tr -d '[:space:]' < "$pid_file"
  fi
}

pid_running() {
  local pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

cleanup_pidfile() {
  local pid_file="$1"
  local pid
  pid="$(read_pid "$pid_file" || true)"
  if [ -n "$pid" ] && ! pid_running "$pid"; then
    rm -f "$pid_file"
  fi
}

port_listener_pids() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
}

port_listening() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

start_http() {
  ensure_dirs
  require_python
  cleanup_pidfile "$HTTP_PID_FILE"

  local pid
  pid="$(read_pid "$HTTP_PID_FILE" || true)"
  if pid_running "$pid"; then
    echo "ℹ️  HTTP console already running (pid=$pid, port=$CONSOLE_PORT)"
    return 0
  fi

  local listeners
  listeners="$(port_listener_pids "$CONSOLE_PORT")"
  if [ -n "$listeners" ]; then
    echo "❌ Port $CONSOLE_PORT is already in use by pid(s): $listeners"
    return 1
  fi

  echo "▶️  Starting HTTP console on http://localhost:$CONSOLE_PORT"
  (
    cd "$ROOT"
    export CONSOLE_PORT CONSOLE_HOST
    nohup "$PYTHON_BIN" app.py >> "$HTTP_LOG_FILE" 2>&1 &
    echo $! > "$HTTP_PID_FILE"
  )

  ln -sfn "$(basename "$HTTP_LOG_FILE")" "$HTTP_LATEST_LINK"
  sleep 2
  pid="$(read_pid "$HTTP_PID_FILE" || true)"
  if ! pid_running "$pid" || ! port_listening "$CONSOLE_PORT"; then
    echo "❌ HTTP console failed to start. See $HTTP_LOG_FILE"
    return 1
  fi
  echo "✅ HTTP console started (pid=$pid)"
}

start_ws() {
  ensure_dirs
  require_python
  cleanup_pidfile "$WS_PID_FILE"

  local pid
  pid="$(read_pid "$WS_PID_FILE" || true)"
  if pid_running "$pid"; then
    echo "ℹ️  WebSocket server already running (pid=$pid, port=$CONSOLE_WS_PORT)"
    return 0
  fi

  local listeners
  listeners="$(port_listener_pids "$CONSOLE_WS_PORT")"
  if [ -n "$listeners" ]; then
    echo "❌ Port $CONSOLE_WS_PORT is already in use by pid(s): $listeners"
    return 1
  fi

  echo "▶️  Starting WebSocket server on ws://$CONSOLE_WS_HOST:$CONSOLE_WS_PORT"
  (
    cd "$ROOT"
    export CONSOLE_WS_PORT CONSOLE_WS_HOST
    nohup "$PYTHON_BIN" websocket_server.py >> "$WS_LOG_FILE" 2>&1 &
    echo $! > "$WS_PID_FILE"
  )

  sleep 2
  pid="$(read_pid "$WS_PID_FILE" || true)"
  if ! pid_running "$pid" || ! port_listening "$CONSOLE_WS_PORT"; then
    echo "❌ WebSocket server failed to start. See $WS_LOG_FILE"
    return 1
  fi
  echo "✅ WebSocket server started (pid=$pid)"
}

stop_pidfile() {
  local label="$1"
  local pid_file="$2"
  cleanup_pidfile "$pid_file"
  local pid
  pid="$(read_pid "$pid_file" || true)"
  if ! pid_running "$pid"; then
    echo "ℹ️  $label is not running"
    rm -f "$pid_file"
    return 0
  fi

  echo "⏹️  Stopping $label (pid=$pid)"
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! pid_running "$pid"; then
      rm -f "$pid_file"
      echo "✅ $label stopped"
      return 0
    fi
    sleep 1
  done

  echo "⚠️  Force-killing $label (pid=$pid)"
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$pid_file"
  echo "✅ $label stopped"
}

show_status_line() {
  local label="$1"
  local pid_file="$2"
  local port="$3"
  cleanup_pidfile "$pid_file"
  local pid listeners
  pid="$(read_pid "$pid_file" || true)"
  listeners="$(port_listener_pids "$port")"

  if pid_running "$pid"; then
    echo "✅ $label: running (pid=$pid, port=$port)"
  elif [ -n "$listeners" ]; then
    echo "⚠️  $label: pidfile missing/stale, but port $port is in use by pid(s): $listeners"
  else
    echo "❌ $label: stopped"
  fi
}

health_http() {
  curl -fsS --max-time 5 "http://127.0.0.1:$CONSOLE_PORT/health" >/dev/null 2>&1
}

health_ws() {
  port_listening "$CONSOLE_WS_PORT"
}

health() {
  local ok=0
  echo "🏥 stock_swing console health"
  echo "HTTP target : http://localhost:$CONSOLE_PORT"
  echo "WS target   : ws://$CONSOLE_WS_HOST:$CONSOLE_WS_PORT"

  if health_http; then
    echo "✅ HTTP health check passed"
  else
    echo "❌ HTTP health check failed"
    ok=1
  fi

  if health_ws; then
    echo "✅ WebSocket listener detected"
  else
    echo "❌ WebSocket listener missing"
    ok=1
  fi

  return "$ok"
}

restart_http() {
  stop_pidfile "HTTP console" "$HTTP_PID_FILE"
  start_http
}

restart_ws() {
  stop_pidfile "WebSocket server" "$WS_PID_FILE"
  start_ws
}

watchdog_run_once() {
  ensure_dirs
  local changed=0

  if health_http; then
    echo "✅ Watchdog: HTTP healthy"
  else
    echo "⚠️  Watchdog: HTTP unhealthy, restarting"
    restart_http
    changed=1
  fi

  if health_ws; then
    echo "✅ Watchdog: WebSocket healthy"
  else
    echo "⚠️  Watchdog: WebSocket unhealthy, restarting"
    restart_ws
    changed=1
  fi

  if [ "$changed" -eq 0 ]; then
    echo "ℹ️  Watchdog: no action needed"
  fi
}

watchdog_loop() {
  # Re-export env vars in case called directly by launchd
  export CONSOLE_PORT="${CONSOLE_PORT:-3335}"
  export CONSOLE_HOST="${CONSOLE_HOST:-0.0.0.0}"
  export CONSOLE_WS_PORT="${CONSOLE_WS_PORT:-3334}"
  export CONSOLE_WS_HOST="${CONSOLE_WS_HOST:-127.0.0.1}"
  export WATCHDOG_INTERVAL="${WATCHDOG_INTERVAL:-60}"
  export PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/venv/bin/python}"

  ensure_dirs
  echo "👀 Watchdog loop started (interval=${WATCHDOG_INTERVAL}s, port=${CONSOLE_PORT})"
  while true; do
    echo "---- $(date '+%Y-%m-%d %H:%M:%S %Z') ----"
    "$SCRIPT_PATH" watchdog-run-once || true
    sleep "$WATCHDOG_INTERVAL"
  done
}

watchdog_start() {
  ensure_dirs
  cleanup_pidfile "$WATCHDOG_PID_FILE"
  local pid
  pid="$(read_pid "$WATCHDOG_PID_FILE" || true)"
  if pid_running "$pid"; then
    echo "ℹ️  Watchdog already running (pid=$pid)"
    return 0
  fi

  echo "▶️  Starting watchdog loop"
  nohup "$SCRIPT_PATH" watchdog-loop >> "$WATCHDOG_LOG_FILE" 2>&1 &
  echo $! > "$WATCHDOG_PID_FILE"
  sleep 1
  pid="$(read_pid "$WATCHDOG_PID_FILE" || true)"
  if ! pid_running "$pid"; then
    echo "❌ Watchdog failed to start. See $WATCHDOG_LOG_FILE"
    return 1
  fi
  echo "✅ Watchdog started (pid=$pid)"
}

watchdog_status() {
  show_status_line "Watchdog" "$WATCHDOG_PID_FILE" 0
}

case "${1:-start}" in
  start)
    start_http
    start_ws
    ;;
  stop)
    stop_pidfile "Watchdog" "$WATCHDOG_PID_FILE"
    stop_pidfile "WebSocket server" "$WS_PID_FILE"
    stop_pidfile "HTTP console" "$HTTP_PID_FILE"
    ;;
  restart)
    stop_pidfile "WebSocket server" "$WS_PID_FILE"
    stop_pidfile "HTTP console" "$HTTP_PID_FILE"
    start_http
    start_ws
    ;;
  status)
    show_status_line "HTTP console" "$HTTP_PID_FILE" "$CONSOLE_PORT"
    show_status_line "WebSocket server" "$WS_PID_FILE" "$CONSOLE_WS_PORT"
    cleanup_pidfile "$WATCHDOG_PID_FILE"
    local_pid="$(read_pid "$WATCHDOG_PID_FILE" || true)"
    if pid_running "$local_pid"; then
      echo "✅ Watchdog: running (pid=$local_pid, interval=${WATCHDOG_INTERVAL}s)"
    else
      echo "❌ Watchdog: stopped"
    fi
    ;;
  health)
    health
    ;;
  watchdog-run-once)
    watchdog_run_once
    ;;
  watchdog-loop)
    watchdog_loop
    ;;
  watchdog-start)
    watchdog_start
    ;;
  watchdog-stop)
    stop_pidfile "Watchdog" "$WATCHDOG_PID_FILE"
    ;;
  watchdog-status)
    cleanup_pidfile "$WATCHDOG_PID_FILE"
    pid="$(read_pid "$WATCHDOG_PID_FILE" || true)"
    if pid_running "$pid"; then
      echo "✅ Watchdog running (pid=$pid, interval=${WATCHDOG_INTERVAL}s)"
    else
      echo "❌ Watchdog stopped"
    fi
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|health|watchdog-run-once|watchdog-start|watchdog-stop|watchdog-status}"
    exit 1
    ;;
esac
