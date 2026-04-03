#!/bin/bash
# Description: End-to-end paper trading demo runner (US Tech/IT universe)
# Usage:
#   ./scripts/run_paper_demo.sh                              # default 10 tech symbols
#   ./scripts/run_paper_demo.sh --dry-run                    # preview without orders
#   ./scripts/run_paper_demo.sh --universe full              # 14 tech + ETF symbols
#   ./scripts/run_paper_demo.sh --symbols NVDA,AMD,PLTR      # custom symbols
#   ./scripts/run_paper_demo.sh --min-momentum 0.01          # lower threshold
#   ./scripts/run_paper_demo.sh --allow-outside-hours        # queue outside market hours

set -euo pipefail
PROJECT_ROOT="$HOME/stock_swing"
cd "$PROJECT_ROOT"

if [ ! -d "$PROJECT_ROOT/venv" ]; then
  echo "ERROR: venv not found"
  echo "  Run: python3 -m venv venv && source venv/bin/activate && pip install -e ."
  exit 1
fi

source "$PROJECT_ROOT/venv/bin/activate"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/paper_demo_$(date +%Y%m%d_%H%M%S).log"

echo "stock_swing Paper Trading Demo (US Tech) - $(date '+%Y-%m-%d %H:%M:%S %Z')"
python -m stock_swing.cli.paper_demo "$@" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}
echo "Log: $LOG_FILE"
exit $EXIT_CODE
