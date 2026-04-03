#!/bin/bash
# Description: End-to-end paper trading demo runner
# Usage: ./scripts/run_paper_demo.sh [options]

set -euo pipefail
PROJECT_ROOT="$HOME/stock_swing"
cd "$PROJECT_ROOT"

if [ ! -d "$PROJECT_ROOT/venv" ]; then
  echo "ERROR: venv not found"
  exit 1
fi

source "$PROJECT_ROOT/venv/bin/activate"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/paper_demo_$(date +%Y%m%d_%H%M%S).log"

echo "stock_swing Paper Trading Demo - $(date '+%Y-%m-%d %H:%M:%S %Z')"
python -m stock_swing.cli.paper_demo "$@" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}
echo "Log: $LOG_FILE"
exit $EXIT_CODE
