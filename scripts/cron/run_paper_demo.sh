#!/bin/bash
# Description: Paper demo runner for cron - market-hours aware
# Usage: ./run_paper_demo.sh [paper_demo_args...]

set -euo pipefail

PROJECT_ROOT="$HOME/stock_swing"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/paper_demo_cron_$(date +%Y%m%d_%H%M%S).log"

echo "================================================" | tee -a "$LOG_FILE"
echo "📊 stock_swing Paper Demo (Cron)" | tee -a "$LOG_FILE"
echo "⏰ Started at: $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Activate venv
if [ -d "$PROJECT_ROOT/venv" ]; then
    echo "✅ Activating virtual environment..." | tee -a "$LOG_FILE"
    source "$PROJECT_ROOT/venv/bin/activate"
else
    echo "❌ Virtual environment not found" | tee -a "$LOG_FILE"
    exit 1
fi

# Run paper demo with outside-hours allowed (will queue orders)
echo "🚀 Running paper demo..." | tee -a "$LOG_FILE"
echo "🧩 Args: $*" | tee -a "$LOG_FILE"
python -m stock_swing.cli.paper_demo --allow-outside-hours "$@" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

echo "" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"
echo "⏰ Completed at: $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$LOG_FILE"

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Demo completed successfully" | tee -a "$LOG_FILE"
else
    echo "❌ Demo failed with exit code $EXIT_CODE" | tee -a "$LOG_FILE"
fi

echo "📝 Log file: $LOG_FILE" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"

exit $EXIT_CODE
