"""Research-only utilities (backtest trial tracking, etc.).

Everything under this package is for offline research/validation
(R11/R13-C style historical backtests). Nothing here is imported by
paper_demo.py or any other production execution path.
"""
from stock_swing.research.trial_registry import TrialRecord, TrialRegistry

__all__ = ["TrialRecord", "TrialRegistry"]
