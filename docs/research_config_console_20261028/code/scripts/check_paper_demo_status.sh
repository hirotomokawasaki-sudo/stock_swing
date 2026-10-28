#!/bin/bash
# Quick health view for the 4 paper_demo cron jobs.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

python3 scripts/check_cron_health.py \
  --only paper_demo_premarket,paper_demo_market_open,paper_demo_midday,paper_demo_market_close
