#!/bin/bash
# Description: Order reconciliation wrapper for cron jobs

set -e
PROJECT_ROOT="$HOME/stock_swing"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/reconcile_orders_$(date +%Y%m%d_%H%M%S).log"

echo "================================================" | tee -a "$LOG_FILE"
echo "🔄 stock_swing Order Reconciliation" | tee -a "$LOG_FILE"
echo "⏰ Started at: $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"

if [ -d "$PROJECT_ROOT/venv" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
else
    echo "❌ Virtual environment not found at $PROJECT_ROOT/venv" | tee -a "$LOG_FILE"
    exit 1
fi

python -m stock_swing.cli.reconcile_orders 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

echo "================================================" | tee -a "$LOG_FILE"
echo "⏰ Completed at: $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$LOG_FILE"
echo "📝 Log file: $LOG_FILE" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"

exit $EXIT_CODE
