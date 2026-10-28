"""Execution layer for paper-safe order submission and reconciliation.

This module implements the execution layer that:
1. Submits orders to broker (paper mode only)
2. Reconciles fills against broker truth
3. Enforces pre-submission checks (mode, risk, deduplication)
4. Tracks order and fill state
5. Provides live-guarded execution with operator approval (Task 16)

CRITICAL: Live-guarded execution requires explicit operator approval.
No autonomous live execution is permitted.

See EXECUTION_POLICY.md for execution constraints.
"""

from .paper_executor import PaperExecutor, OrderSubmission, FillRecord
from .reconciler import Reconciler, ReconciliationResult
from .live_guarded_executor import LiveGuardedExecutor, ApprovalRequest, ApprovalStatus
from .production_executor import ProductionExecutor

__all__ = [
    "PaperExecutor",
    "OrderSubmission",
    "FillRecord",
    "Reconciler",
    "ReconciliationResult",
    "LiveGuardedExecutor",
    "ApprovalRequest",
    "ApprovalStatus",
    "ProductionExecutor",
]
