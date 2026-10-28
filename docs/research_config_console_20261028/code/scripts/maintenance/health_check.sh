#!/bin/bash
# Description: System health check
# Usage: ./health_check.sh

echo "🏥 stock_swing Health Check"
echo "=========================="
echo ""

# Check venv
if [ -d "$HOME/stock_swing/venv" ]; then
    echo "✅ Virtual environment exists"
else
    echo "❌ Virtual environment not found"
fi

# Check config files
if [ -f "$HOME/stock_swing/.env" ]; then
    echo "✅ .env file exists"
else
    echo "❌ .env file not found"
fi

# Check runtime mode
if [ -f "$HOME/stock_swing/config/runtime/current_mode.yaml" ]; then
    MODE=$(grep "mode:" "$HOME/stock_swing/config/runtime/current_mode.yaml" | awk '{print $2}')
    echo "✅ Runtime mode: $MODE"
else
    echo "❌ Runtime mode config not found"
fi

# Check data directories
for dir in raw normalized features signals decisions audits; do
    if [ -d "$HOME/stock_swing/data/$dir" ]; then
        COUNT=$(find "$HOME/stock_swing/data/$dir" -type f 2>/dev/null | wc -l)
        echo "✅ data/$dir/ exists ($COUNT files)"
    else
        echo "⚠️  data/$dir/ not found"
    fi
done

echo ""
echo "✅ Health check complete"
