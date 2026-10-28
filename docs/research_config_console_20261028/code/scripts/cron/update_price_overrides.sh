#!/bin/bash
# Update price overrides from Massive API to fix stale Alpaca positions API prices
# Run daily at market close

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Activate virtual environment
source venv/bin/activate

# Run price override update
python scripts/fix_stale_broker_prices.py

echo "✓ Price overrides updated successfully"
