"""OpenClaw adapter for human-readable summaries and operator outputs.

This module provides OpenClaw-facing interfaces for:
- Signal summaries
- Decision summaries
- Execution summaries
- Reconciliation reports
- Operator-friendly outputs

CRITICAL: This adapter has NO execution authority.
All outputs are informational only.

See SYSTEM_OVERVIEW.md for OpenClaw separation rationale.
"""

from .signal_summarizer import SignalSummarizer
from .decision_summarizer import DecisionSummarizer
from .execution_summarizer import ExecutionSummarizer

__all__ = [
    "SignalSummarizer",
    "DecisionSummarizer",
    "ExecutionSummarizer",
]
