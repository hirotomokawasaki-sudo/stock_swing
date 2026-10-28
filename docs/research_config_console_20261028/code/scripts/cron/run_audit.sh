#!/bin/bash
# Audit runner that always uses venv to avoid dependency issues
# Usage: ./scripts/cron/run_audit.sh [--anomaly-threshold 0.30]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"
AUDIT_SCRIPT="$PROJECT_ROOT/scripts/audit_trades_with_market_data.py"

# Ensure venv exists
if [[ ! -d "$VENV_DIR" ]]; then
    echo "ERROR: venv not found at $VENV_DIR"
    exit 1
fi

# Activate venv and run audit
source "$VENV_DIR/bin/activate"
exec python "$AUDIT_SCRIPT" "$@"
