#!/bin/bash
# Description: Order reconciliation wrapper for cron jobs

set -euo pipefail
PROJECT_ROOT="$HOME/stock_swing"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/reconcile_orders_$(date +%Y%m%d_%H%M%S).log"
RUN_LOG="$(mktemp "$LOG_DIR/reconcile_orders_run.XXXXXX.log")"

if [ -d "$PROJECT_ROOT/venv" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
else
    echo "Virtual environment not found at $PROJECT_ROOT/venv" >> "$LOG_FILE"
    printf '%s\n' "CRON_SUMMARY_JSON={\"job\":\"reconcile_orders\",\"status\":\"error\",\"exit_code\":1,\"reason\":\"missing_venv\",\"log_file\":\"$LOG_FILE\"}"
    exit 1
fi

set +e
python -m stock_swing.cli.reconcile_orders --cron-summary-json >"$RUN_LOG" 2>&1
EXIT_CODE=$?
set -e

{
    echo "================================================"
    echo "🔄 stock_swing Order Reconciliation"
    echo "⏰ Started at: $(date '+%Y-%m-%d %H:%M:%S %Z')"
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
    printf '%s\n' "CRON_SUMMARY_JSON={\"job\":\"reconcile_orders\",\"status\":\"ok\",\"exit_code\":0,\"log_file\":\"$LOG_FILE\"}"
else
    printf '%s\n' "CRON_SUMMARY_JSON={\"job\":\"reconcile_orders\",\"status\":\"error\",\"exit_code\":$EXIT_CODE,\"log_file\":\"$LOG_FILE\"}"
fi

rm -f "$RUN_LOG"

exit $EXIT_CODE
