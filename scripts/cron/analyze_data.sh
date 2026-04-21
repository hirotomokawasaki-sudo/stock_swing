#!/bin/bash
# Description: Data analysis wrapper for cron jobs
# Usage: ./analyze_data.sh [--symbols SYMBOL1,SYMBOL2]

set -e  # Exit on error

# Project root
PROJECT_ROOT="$HOME/stock_swing"
cd "$PROJECT_ROOT"

# Log file
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/analyze_data_$(date +%Y%m%d_%H%M%S).log"

# Default symbols
DEFAULT_SYMBOLS="NVDA,MSFT,GOOGL,AMZN,META,TSLA,AVGO,AMD,TSM,ASML,INTC,MU,ARM,AMAT,LRCX,KLAC,QCOM,MRVL,PLTR,ADBE,CRM,ORCL,NOW,SNOW,MDB,DDOG,PATH,FICO,SMCI,PANW,CRWD,FTNT,ANET,CSCO,IBM,HPE,DELL,HPQ,SNPS,CDNS,V,MA,INTU,NBIS,CRDO,RBRK,CIEN,SHOC,SOXQ,SOXX,SMH,FTXL,PTF,SMHX,FRWD,TTEQ,GTOP,CHPX,CHPS,PSCT,QTEC,TDIV,SKYY,QTUM"

# Parse arguments
SYMBOLS="${1:-$DEFAULT_SYMBOLS}"

echo "================================================" | tee -a "$LOG_FILE"
echo "📊 stock_swing Data Analysis" | tee -a "$LOG_FILE"
echo "⏰ Started at: $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$LOG_FILE"
echo "📈 Symbols: $SYMBOLS" | tee -a "$LOG_FILE"
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

# Check runtime mode
MODE_FILE="$PROJECT_ROOT/config/runtime/current_mode.yaml"
if [ -f "$MODE_FILE" ]; then
    MODE=$(grep "mode:" "$MODE_FILE" | awk '{print $2}')
    echo "✅ Runtime mode: $MODE" | tee -a "$LOG_FILE"
    
    if [ "$MODE" != "research" ] && [ "$MODE" != "paper" ]; then
        echo "⚠️  WARNING: Not in research/paper mode" | tee -a "$LOG_FILE"
        echo "   Continuing anyway..." | tee -a "$LOG_FILE"
    fi
else
    echo "⚠️  Runtime mode config not found" | tee -a "$LOG_FILE"
fi

# Check if data exists
DATA_COUNT=$(find "$PROJECT_ROOT/data/raw" -type f 2>/dev/null | wc -l)
echo "📁 Raw data files: $DATA_COUNT" | tee -a "$LOG_FILE"

if [ "$DATA_COUNT" -eq 0 ]; then
    echo "⚠️  WARNING: No raw data found" | tee -a "$LOG_FILE"
    echo "   Run data collection first" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"

# Run analysis
echo "🚀 Running data analysis..." | tee -a "$LOG_FILE"
python -m stock_swing.cli.analyze_data --symbols "$SYMBOLS" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

echo "" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"
echo "⏰ Completed at: $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$LOG_FILE"

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Analysis completed successfully" | tee -a "$LOG_FILE"
else
    echo "❌ Analysis failed with exit code $EXIT_CODE" | tee -a "$LOG_FILE"
fi

echo "📝 Log file: $LOG_FILE" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"

exit $EXIT_CODE
