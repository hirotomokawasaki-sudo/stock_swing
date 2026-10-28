#!/bin/bash
# Description: Set up optimal cron schedule for stock_swing
# Usage: ./setup_optimal_crons.sh [--dry-run] [--force]

set -e

DRY_RUN=false
FORCE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "🤖 stock_swing Optimal Cron Schedule Setup"
echo "=========================================="
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "🧪 DRY RUN MODE - No actual changes"
    echo ""
fi

if [ "$FORCE" = true ]; then
    echo "⚠️  FORCE MODE - Will remove existing jobs"
    echo ""
fi

# Check if OpenClaw is available
if ! command -v openclaw &> /dev/null; then
    echo "❌ OpenClaw not found"
    exit 1
fi

echo "✅ OpenClaw found"
echo ""

# List current jobs
echo "📋 Current Cron Jobs:"
CURRENT_JOBS=$(openclaw cron list 2>/dev/null | jq -r '.jobs[] | .name' | wc -l)
echo "   Total jobs: $CURRENT_JOBS"
echo ""

if [ "$CURRENT_JOBS" -gt 0 ] && [ "$FORCE" = false ]; then
    echo "⚠️  Existing cron jobs found"
    echo "   Use --force to remove and recreate all jobs"
    echo ""
    read -p "Continue and add new jobs? (yes/no): " response
    if [ "$response" != "yes" ]; then
        echo "❌ Aborted"
        exit 1
    fi
fi

if [ "$FORCE" = true ]; then
    echo "🗑️  Removing existing jobs..."
    if [ "$DRY_RUN" = false ]; then
        openclaw cron list 2>/dev/null | jq -r '.jobs[] | .id' | while read -r job_id; do
            openclaw cron remove --id "$job_id"
            echo "   Removed: $job_id"
        done
    else
        echo "   (dry-run: would remove $CURRENT_JOBS jobs)"
    fi
    echo ""
fi

echo "➕ Adding new cron jobs..."
echo ""

# Job definitions
declare -A JOBS

# Job 1: Performance Analysis (Daily at 00:00)
JOBS["performance_analysis"]='{"name":"stock_swing_performance_analysis","schedule":{"kind":"cron","expr":"0 0 * * *","tz":"Asia/Tokyo"},"payload":{"kind":"agentTurn","message":"Execute stock_swing performance analysis:\n\nRun: cd ~/stock_swing && source venv/bin/activate && python -m stock_swing.cli.analyze_performance\n\nThis will:\n1. Analyze performance metrics\n2. Generate parameter recommendations\n3. Create daily reports\n\nReport summary after completion.","timeoutSeconds":900},"sessionTarget":"isolated","delivery":{"mode":"announce"}}'

# Job 2: Maintenance (Daily at 01:00)
JOBS["maintenance"]='{"name":"stock_swing_maintenance","schedule":{"kind":"cron","expr":"0 1 * * *","tz":"Asia/Tokyo"},"payload":{"kind":"agentTurn","message":"Execute stock_swing maintenance:\n\nRun: ~/stock_swing/scripts/maintenance/daily_maintenance.sh\n\nThis will:\n1. Clean old data\n2. Rotate logs\n3. Backup databases\n\nReport summary after completion.","timeoutSeconds":600},"sessionTarget":"isolated","delivery":{"mode":"announce"}}'

# Job 3: Macro Data Collection (Daily at 02:00)
JOBS["macro_collection"]='{"name":"stock_swing_macro_collection","schedule":{"kind":"cron","expr":"0 2 * * *","tz":"Asia/Tokyo"},"payload":{"kind":"agentTurn","message":"Execute stock_swing macro data collection:\n\nRun: cd ~/stock_swing && source venv/bin/activate && python -m stock_swing.cli.collect_data --sources fred,sec\n\nCollecting macro indicators and SEC filings.\n\nReport summary after completion.","timeoutSeconds":600},"sessionTarget":"isolated","delivery":{"mode":"announce"}}'

# Job 4: Market Data Collection (Daily at 06:00)
JOBS["market_collection"]='{"name":"stock_swing_market_collection","schedule":{"kind":"cron","expr":"0 6 * * *","tz":"Asia/Tokyo"},"payload":{"kind":"agentTurn","message":"Execute stock_swing market data collection:\n\nRun: cd ~/stock_swing && source venv/bin/activate && python -m stock_swing.cli.collect_data --sources finnhub,broker --symbols AAPL,MSFT,GOOGL,AMZN,TSLA\n\nCollecting market data and broker positions.\n\nReport summary after completion.","timeoutSeconds":600},"sessionTarget":"isolated","delivery":{"mode":"announce"}}'

# Job 5: Strategy Generation (3x daily at 08:00, 15:00, 20:00)
JOBS["strategy_generation"]='{"name":"stock_swing_strategy_generation","schedule":{"kind":"cron","expr":"0 8,15,20 * * *","tz":"Asia/Tokyo"},"payload":{"kind":"agentTurn","message":"Execute stock_swing strategy generation:\n\nRun: cd ~/stock_swing && source venv/bin/activate && python -m stock_swing.cli.generate_strategies --symbols AAPL,MSFT,GOOGL,AMZN,TSLA\n\nGenerating trading signals from EventSwing and BreakoutMomentum strategies.\n\nReport summary after completion.","timeoutSeconds":600},"sessionTarget":"isolated","delivery":{"mode":"announce"}}'

# Job 6: Decision Making (2x daily at 09:00, 21:00)
JOBS["decision_making"]='{"name":"stock_swing_decision_making","schedule":{"kind":"cron","expr":"0 9,21 * * *","tz":"Asia/Tokyo"},"payload":{"kind":"agentTurn","message":"Execute stock_swing decision making:\n\nFirst, check market status:\npython -m stock_swing.cli.market_check\n\nIf market is open or pre-market:\ncd ~/stock_swing && source venv/bin/activate && python -m stock_swing.cli.make_decisions --symbols AAPL,MSFT,GOOGL,AMZN,TSLA\n\nCreating trading decisions with risk validation.\n\nReport summary after completion.","timeoutSeconds":300},"sessionTarget":"isolated","delivery":{"mode":"announce"}}'

# Job 7: Periodic Updates (Every 2 hours at :40)
JOBS["periodic_updates"]='{"name":"stock_swing_periodic_updates","schedule":{"kind":"cron","expr":"40 */2 * * *","tz":"Asia/Tokyo"},"payload":{"kind":"agentTurn","message":"Execute stock_swing periodic update:\n\nRun: cd ~/stock_swing && source venv/bin/activate && python -m stock_swing.cli.collect_data --symbols AAPL,MSFT,GOOGL,AMZN,TSLA\n\nQuick data refresh from all sources.\n\nReport summary after completion.","timeoutSeconds":600},"sessionTarget":"isolated","delivery":{"mode":"announce"}}'

# Job 8: Reconciliation (Daily at 06:00 - after market close)
JOBS["reconciliation"]='{"name":"stock_swing_reconciliation","schedule":{"kind":"cron","expr":"0 6 * * 1-5","tz":"Asia/Tokyo"},"payload":{"kind":"agentTurn","message":"Execute stock_swing reconciliation:\n\nRun: cd ~/stock_swing && source venv/bin/activate && python -m stock_swing.cli.reconcile\n\nReconciling orders and positions after market close.\n\nReport any discrepancies.","timeoutSeconds":600},"sessionTarget":"isolated","delivery":{"mode":"announce"}}'

# Add jobs
JOB_COUNT=0
for job_name in "${!JOBS[@]}"; do
    echo "➕ Adding: $job_name"
    
    if [ "$DRY_RUN" = false ]; then
        echo "${JOBS[$job_name]}" | openclaw cron add --job - || {
            echo "   ❌ Failed to add $job_name"
            continue
        }
        echo "   ✅ Added successfully"
        JOB_COUNT=$((JOB_COUNT + 1))
    else
        echo "   (dry-run: would add job)"
        JOB_COUNT=$((JOB_COUNT + 1))
    fi
    echo ""
done

echo "=========================================="
echo "📊 Summary:"
echo "   Jobs added: $JOB_COUNT"
echo ""

if [ "$DRY_RUN" = false ]; then
    echo "💾 Backing up cron jobs..."
    ~/stock_swing/scripts/utils/backup_cron_jobs.sh --auto-commit
    echo ""
fi

echo "✅ Setup complete!"
echo ""
echo "📋 View all jobs:"
echo "   openclaw cron list"
echo ""
echo "📊 Check next runs:"
echo "   openclaw cron status"
