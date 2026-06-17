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
#   ./console/manage.sh rotate-logs

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
LAUNCHD_WATCHDOG_LOG_FILE="$LOG_DIR/launchd_watchdog.log"
LAUNCHD_WATCHDOG_ERR_FILE="$LOG_DIR/launchd_watchdog.err"
LOG_ARCHIVE_DIR="$LOG_DIR/archive"
HTTP_LATEST_LINK="$LOG_DIR/console_latest.log"
LOG_ROTATE_KEEP="${LOG_ROTATE_KEEP:-10}"
LOG_ROTATE_MAX_BYTES="${LOG_ROTATE_MAX_BYTES:-1048576}"
LAUNCHD_WATCHDOG_LABEL="${LAUNCHD_WATCHDOG_LABEL:-com.hirotomookawasaki.stock_swing.console.watchdog}"

ensure_dirs() {
  mkdir -p "$LOG_DIR" "$RUN_DIR" "$LOG_ARCHIVE_DIR"
}

log_size_bytes() {
  local log_file="$1"
  if [ -f "$log_file" ]; then
    wc -c < "$log_file" | tr -d '[:space:]'
  else
    echo 0
  fi
}

prune_rotated_logs() {
  local stem="$1"
  local ext="$2"
  local old_files
  old_files=$(find "$LOG_ARCHIVE_DIR" -type f -name "${stem}_*.${ext}" 2>/dev/null | sort -r | tail -n +$((LOG_ROTATE_KEEP + 1)) || true)
  if [ -n "$old_files" ]; then
    while IFS= read -r old_file; do
      [ -n "$old_file" ] && rm -f "$old_file"
    done <<EOF
$old_files
EOF
  fi
}

rotate_log_file() {
  local log_file="$1"
  local mode="${2:-force}"
  local filename stem ext ts archive_dir archive_file size_bytes

  ensure_dirs
  filename="$(basename "$log_file")"
  stem="${filename%.*}"
  ext="${filename##*.}"

  if [ ! -f "$log_file" ]; then
    : > "$log_file"
    chmod 600 "$log_file" 2>/dev/null || true
    return 0
  fi

  size_bytes="$(log_size_bytes "$log_file")"
  if [ "$mode" != "force" ] && [ "$size_bytes" -lt "$LOG_ROTATE_MAX_BYTES" ]; then
    return 0
  fi

  if [ "$size_bytes" -gt 0 ]; then
    ts="$(date '+%Y%m%d_%H%M%S')"
    archive_dir="$LOG_ARCHIVE_DIR/$(date '+%Y-%m-%d')"
    archive_file="$archive_dir/${stem}_${ts}.${ext}"
    mkdir -p "$archive_dir"
    cp "$log_file" "$archive_file"
    : > "$log_file"
  else
    : > "$log_file"
  fi

  chmod 600 "$log_file" 2>/dev/null || true
  prune_rotated_logs "$stem" "$ext"
}

rotate_runtime_logs_if_needed() {
  rotate_log_file "$HTTP_LOG_FILE" size
  rotate_log_file "$WS_LOG_FILE" size
  rotate_log_file "$WATCHDOG_LOG_FILE" size
  rotate_log_file "$LAUNCHD_WATCHDOG_LOG_FILE" size
  rotate_log_file "$LAUNCHD_WATCHDOG_ERR_FILE" size
}

force_rotate_all_logs() {
  rotate_log_file "$HTTP_LOG_FILE" force
  rotate_log_file "$WS_LOG_FILE" force
  rotate_log_file "$WATCHDOG_LOG_FILE" force
  rotate_log_file "$LAUNCHD_WATCHDOG_LOG_FILE" force
  rotate_log_file "$LAUNCHD_WATCHDOG_ERR_FILE" force
}

prepare_watchdog_log() {
  rotate_log_file "$WATCHDOG_LOG_FILE" force
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

single_port_listener_pid() {
  local port="$1"
  local listeners listener_count
  listeners="$(port_listener_pids "$port")"
  listener_count="$(printf '%s\n' "$listeners" | sed '/^$/d' | wc -l | tr -d '[:space:]')"
  if [ "$listener_count" = "1" ]; then
    printf '%s\n' "$listeners" | sed '/^$/d' | head -n 1
  fi
}

is_websocket_process() {
  local pid="$1"
  local command
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  case "$command" in
    *"websocket_server.py"*) return 0 ;;
    *) return 1 ;;
  esac
}

adopt_ws_pidfile() {
  cleanup_pidfile "$WS_PID_FILE"

  local pid listener
  pid="$(read_pid "$WS_PID_FILE" || true)"
  if pid_running "$pid"; then
    return 0
  fi

  listener="$(single_port_listener_pid "$CONSOLE_WS_PORT")"
  if [ -n "$listener" ] && pid_running "$listener" && is_websocket_process "$listener"; then
    echo "$listener" > "$WS_PID_FILE"
    echo "ℹ️  WebSocket server already running without pidfile; adopted pid=$listener"
    return 0
  fi

  return 1
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

  rotate_log_file "$HTTP_LOG_FILE"

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
  if adopt_ws_pidfile; then
    pid="$(read_pid "$WS_PID_FILE" || true)"
    echo "ℹ️  WebSocket server already running (pid=$pid, port=$CONSOLE_WS_PORT)"
    return 0
  fi

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

  rotate_log_file "$WS_LOG_FILE"

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

stop_ws() {
  adopt_ws_pidfile >/dev/null 2>&1 || true
  stop_pidfile "WebSocket server" "$WS_PID_FILE"
}

restart_ws() {
  stop_ws
  start_ws
}

watchdog_run_once() {
  ensure_dirs
  rotate_runtime_logs_if_needed
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

  prepare_watchdog_log
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

launchd_watchdog_target() {
  echo "gui/$(id -u)/$LAUNCHD_WATCHDOG_LABEL"
}

launchd_watchdog_snapshot() {
  launchctl print "$(launchd_watchdog_target)" 2>/dev/null || return 1
}

show_watchdog_status() {
  cleanup_pidfile "$WATCHDOG_PID_FILE"
  local pid snapshot launchd_state launchd_pid
  pid="$(read_pid "$WATCHDOG_PID_FILE" || true)"

  if pid_running "$pid"; then
    echo "✅ Watchdog: running (pid=$pid, interval=${WATCHDOG_INTERVAL}s)"
    return 0
  fi

  snapshot="$(launchd_watchdog_snapshot || true)"
  if [ -n "$snapshot" ]; then
    launchd_state="$(printf '%s\n' "$snapshot" | awk -F'= ' '/state = / {print $2; exit}')"
    launchd_pid="$(printf '%s\n' "$snapshot" | awk -F'= ' '/pid = / {print $2; exit}')"
    if [ "$launchd_state" = "running" ]; then
      echo "✅ Watchdog: running via launchd (pid=${launchd_pid:-unknown}, label=$LAUNCHD_WATCHDOG_LABEL, interval=${WATCHDOG_INTERVAL}s)"
    else
      echo "⚠️  Watchdog: launchd loaded (state=${launchd_state:-unknown}, label=$LAUNCHD_WATCHDOG_LABEL)"
    fi
    return 0
  fi

  echo "❌ Watchdog: stopped"
}

watchdog_status() {
  show_watchdog_status
}

case "${1:-start}" in
  start)
    start_http
    start_ws
    ;;
  stop)
    stop_pidfile "Watchdog" "$WATCHDOG_PID_FILE"
    stop_ws
    stop_pidfile "HTTP console" "$HTTP_PID_FILE"
    ;;
  restart)
    restart_ws
    restart_http
    ;;
  status)
    show_status_line "HTTP console" "$HTTP_PID_FILE" "$CONSOLE_PORT"
    show_status_line "WebSocket server" "$WS_PID_FILE" "$CONSOLE_WS_PORT"
    show_watchdog_status
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
    show_watchdog_status
    ;;
  rotate-logs)
    force_rotate_all_logs
    echo "✅ Rotated active console/watchdog logs into $LOG_ARCHIVE_DIR/$(date '+%Y-%m-%d')"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|health|watchdog-run-once|watchdog-start|watchdog-stop|watchdog-status|rotate-logs}"
    exit 1
    ;;
esac
