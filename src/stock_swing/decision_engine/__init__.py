"""Decision engine for risk validation and candidate → actionable decision transformation.

This module implements the final decision layer that:
1. Evaluates candidate signals from strategies
2. Applies risk validation checks
3. Generates actionable or denied decision records
4. Enforces runtime mode constraints
5. Produces DECISION_SCHEMA.md compliant outputs

CRITICAL: This layer has NO execution authority.
Execution authority belongs to the execution layer only.

See DECISION_SCHEMA.md for decision record structure.
See EXECUTION_POLICY.md for execution constraints.
"""

from .decision_engine import DecisionEngine, DecisionRecord
from .risk_validator import RiskValidator, RiskState

__all__ = [
    "DecisionEngine",
    "DecisionRecord",
    "RiskValidator",
    "RiskState",
]
