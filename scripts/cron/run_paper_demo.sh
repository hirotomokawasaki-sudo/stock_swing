#!/bin/bash
# Description: Paper demo runner for cron - market-hours aware
# Usage: ./run_paper_demo.sh [paper_demo_args...]

set -euo pipefail

PROJECT_ROOT="$HOME/stock_swing"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/paper_demo_cron_$(date +%Y%m%d_%H%M%S).log"
RUN_LOG="$(mktemp "$LOG_DIR/paper_demo_run.XXXXXX.log")"

# Activate venv
if [ -d "$PROJECT_ROOT/venv" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
else
    echo "Virtual environment not found" >> "$LOG_FILE"
    printf '%s\n' "CRON_SUMMARY_JSON={\"job\":\"paper_demo\",\"status\":\"error\",\"exit_code\":1,\"reason\":\"missing_venv\",\"log_file\":\"$LOG_FILE\"}"
    exit 1
fi

# Allow ETF buys (guardrail disabled: actual ETF PF=2.776 vs Stock PF=0.740 per broker data)
export PAPER_DEMO_ALLOW_ETF_BUYS=true

# RF-6b (2026-07-10): stock-reduced mode
# Blocks individual stocks with per-symbol rolling PF < 1.0.
# 2026-07-23: min_trades raised 3 → 5 to avoid false positives from small samples.
#   (symbols with <5 trades are no longer blocked by stock_reduced;
#    rolling_pf_gate=0.70 still blocks any symbol with ≥5 trades and PF<0.70)
# Disable: ENTRY_FILTER_STOCK_REDUCED=false
export ENTRY_FILTER_STOCK_REDUCED=true
export ENTRY_FILTER_STOCK_REDUCED_MIN_TRADES=5

# Run paper demo with outside-hours allowed (will queue orders).
# Keep cron stdout tiny; detailed logs go to the log file.
set +e
python -m stock_swing.cli.paper_demo --allow-outside-hours --min-momentum 0.05 --cron-summary-json "$@" >"$RUN_LOG" 2>&1
EXIT_CODE=$?
set -e

{
    echo "================================================"
    echo "📊 stock_swing Paper Demo (Cron)"
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
    printf '%s\n' "CRON_SUMMARY_JSON={\"job\":\"paper_demo\",\"status\":\"ok\",\"exit_code\":0,\"log_file\":\"$LOG_FILE\"}"
else
    printf '%s\n' "CRON_SUMMARY_JSON={\"job\":\"paper_demo\",\"status\":\"error\",\"exit_code\":$EXIT_CODE,\"log_file\":\"$LOG_FILE\"}"
fi

rm -f "$RUN_LOG"

exit $EXIT_CODE
