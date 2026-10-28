#!/bin/bash
# Description: Backup OpenClaw cron jobs to project repository
# Usage: ./backup_cron_jobs.sh [--auto-commit]

set -e

PROJECT_ROOT="$HOME/stock_swing"
SOURCE_FILE="$HOME/.openclaw/cron/jobs.json"
BACKUP_FILE="$PROJECT_ROOT/cron_backup/jobs.json"
AUTO_COMMIT=false

# Parse arguments
if [ "$1" = "--auto-commit" ]; then
    AUTO_COMMIT=true
fi

echo "🔄 Backing up OpenClaw Cron Jobs"
echo "================================"
echo ""

# Check if source exists
if [ ! -f "$SOURCE_FILE" ]; then
    echo "❌ Source file not found: $SOURCE_FILE"
    exit 1
fi

# Create backup directory if not exists
mkdir -p "$PROJECT_ROOT/cron_backup"

# Compare files
if [ -f "$BACKUP_FILE" ]; then
    if cmp -s "$SOURCE_FILE" "$BACKUP_FILE"; then
        echo "✅ Cron jobs are already up to date"
        echo "   No changes detected"
        exit 0
    else
        echo "📝 Changes detected in cron jobs"
    fi
else
    echo "📝 Creating initial backup"
fi

# Copy file
cp "$SOURCE_FILE" "$BACKUP_FILE"
echo "✅ Backup created: $BACKUP_FILE"

# Show diff if previous backup exists
if [ -f "$BACKUP_FILE.prev" ]; then
    echo ""
    echo "📊 Changes:"
    diff "$BACKUP_FILE.prev" "$BACKUP_FILE" || true
fi

# Save previous backup for next time
cp "$BACKUP_FILE" "$BACKUP_FILE.prev"

# Auto-commit if requested
if [ "$AUTO_COMMIT" = true ]; then
    echo ""
    echo "🔄 Auto-committing to Git..."
    cd "$PROJECT_ROOT"
    
    git add cron_backup/jobs.json
    
    # Check if there are changes to commit
    if git diff --cached --quiet; then
        echo "✅ No changes to commit"
    else
        git commit -m "chore: backup cron jobs - auto-backup at $(date '+%Y-%m-%d %H:%M:%S')"
        git push origin main
        echo "✅ Changes pushed to GitHub"
    fi
fi

echo ""
echo "================================"
echo "✅ Backup complete"

# Show summary
JOBS_COUNT=$(jq '.jobs | length' "$BACKUP_FILE")
echo ""
echo "📊 Summary:"
echo "   Total jobs: $JOBS_COUNT"
echo "   Backup location: $BACKUP_FILE"

if [ "$AUTO_COMMIT" = false ]; then
    echo ""
    echo "💡 Tip: Use --auto-commit to automatically commit and push to GitHub"
fi
