#!/usr/bin/env python3
"""Order Reconciliation entry point — delegates to the real CLI module."""
import runpy
import sys
from pathlib import Path

# Ensure project src is on the path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if __name__ == "__main__":
    runpy.run_module("stock_swing.cli.reconcile_orders", run_name="__main__", alter_sys=True)
