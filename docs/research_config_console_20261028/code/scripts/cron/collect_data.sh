#!/bin/bash
# Description: Data collection wrapper for cron jobs
# Usage: ./collect_data.sh [collect_data args...]

set -euo pipefail

# Project root
PROJECT_ROOT="$HOME/stock_swing"
cd "$PROJECT_ROOT"

# Log file
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/collect_data_$(date +%Y%m%d_%H%M%S).log"
RUN_LOG="$(mktemp "$LOG_DIR/collect_data_run.XXXXXX.log")"

# Activate venv
if [ -d "$PROJECT_ROOT/venv" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
else
    echo "Virtual environment not found at $PROJECT_ROOT/venv" >> "$LOG_FILE"
    printf '%s\n' "CRON_SUMMARY_JSON={\"job\":\"collect_data\",\"status\":\"error\",\"exit_code\":1,\"reason\":\"missing_venv\",\"log_file\":\"$LOG_FILE\"}"
    exit 1
fi

# Check if API keys are configured
if ! grep -q "FINNHUB_API_KEY=your_key_here" "$PROJECT_ROOT/.env" 2>/dev/null; then
    true
else
    echo "API keys not configured in .env" >> "$LOG_FILE"
fi

set +e
python -m stock_swing.cli.collect_data --cron-summary-json "$@" >"$RUN_LOG" 2>&1
EXIT_CODE=$?
set -e

{
    echo "================================================"
    echo "📡 stock_swing Data Collection"
    echo "⏰ Started at: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "🧩 Args: $*"
    echo "================================================"
    cat "$RUN_LOG"
    echo "================================================"
    echo "⏰ Completed at: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "📝 Log file: $LOG_FILE"
    echo "================================================"
} >> "$LOG_FILE"

SUMMARY_LINE="$(grep '^CRON_SUMMARY_JSON=' "$RUN_LOG" | tail -n 1 || true)"
if [ -n "$SUMMARY_LINE" ]; then
    printf '%s\n' "$SUMMARY_LINE"
elif [ $EXIT_CODE -eq 0 ]; then
    printf '%s\n' "CRON_SUMMARY_JSON={\"job\":\"collect_data\",\"status\":\"ok\",\"exit_code\":0,\"log_file\":\"$LOG_FILE\"}"
else
    printf '%s\n' "CRON_SUMMARY_JSON={\"job\":\"collect_data\",\"status\":\"error\",\"exit_code\":$EXIT_CODE,\"log_file\":\"$LOG_FILE\"}"
fi

rm -f "$RUN_LOG"

exit $EXIT_CODE
