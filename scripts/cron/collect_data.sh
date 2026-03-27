#!/bin/bash
# Description: Data collection wrapper for cron jobs
# Usage: ./collect_data.sh [--symbols SYMBOL1,SYMBOL2]

set -e  # Exit on error

# Project root
PROJECT_ROOT="$HOME/stock_swing"
cd "$PROJECT_ROOT"

# Log file
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/collect_data_$(date +%Y%m%d_%H%M%S).log"

# Default symbols
DEFAULT_SYMBOLS="AAPL,MSFT,GOOGL,AMZN,TSLA"

# Parse arguments
SYMBOLS="${1:-$DEFAULT_SYMBOLS}"

echo "================================================" | tee -a "$LOG_FILE"
echo "📡 stock_swing Data Collection" | tee -a "$LOG_FILE"
echo "⏰ Started at: $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$LOG_FILE"
echo "📊 Symbols: $SYMBOLS" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Activate venv
if [ -d "$PROJECT_ROOT/venv" ]; then
    echo "✅ Activating virtual environment..." | tee -a "$LOG_FILE"
    source "$PROJECT_ROOT/venv/bin/activate"
else
    echo "❌ Virtual environment not found at $PROJECT_ROOT/venv" | tee -a "$LOG_FILE"
    exit 1
fi

# Check if API keys are configured
if ! grep -q "FINNHUB_API_KEY=your_key_here" "$PROJECT_ROOT/.env" 2>/dev/null; then
    echo "✅ API keys appear to be configured" | tee -a "$LOG_FILE"
else
    echo "⚠️  WARNING: API keys not configured in .env" | tee -a "$LOG_FILE"
    echo "   Data collection will fail without API keys" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"

# Run collection
echo "🚀 Running data collection..." | tee -a "$LOG_FILE"
python -m stock_swing.cli.collect_data --symbols "$SYMBOLS" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

echo "" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"
echo "⏰ Completed at: $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$LOG_FILE"

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Collection completed successfully" | tee -a "$LOG_FILE"
else
    echo "❌ Collection failed with exit code $EXIT_CODE" | tee -a "$LOG_FILE"
fi

echo "📝 Log file: $LOG_FILE" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"

exit $EXIT_CODE
