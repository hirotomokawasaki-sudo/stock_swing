#!/bin/bash
# Description: Broker paper trading readiness check
# Usage: ./broker_health_check.sh

set -euo pipefail

PROJECT_ROOT="$HOME/stock_swing"
cd "$PROJECT_ROOT"

if [ ! -d "$PROJECT_ROOT/venv" ]; then
  echo "❌ Virtual environment not found at $PROJECT_ROOT/venv"
  exit 1
fi

source "$PROJECT_ROOT/venv/bin/activate"
python -m stock_swing.cli.broker_healthcheck
