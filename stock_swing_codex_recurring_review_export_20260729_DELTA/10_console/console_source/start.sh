#!/bin/bash
# Backward-compatible wrapper for the console process manager.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/manage.sh" start "$@"
