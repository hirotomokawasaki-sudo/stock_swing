"""Safety layer for production hardening.

This module implements production safety controls:
- Kill switch for emergency stop
- Audit logging for all critical operations
- Safety monitoring and alerts

CRITICAL: Safety controls are fail-safe by default.
All safety checks must pass before execution proceeds.

See EXECUTION_POLICY.md for safety requirements.
"""

from .kill_switch import KillSwitch, KillSwitchState
from .audit_logger import AuditLogger, AuditEvent, AuditLevel

__all__ = [
    "KillSwitch",
    "KillSwitchState",
    "AuditLogger",
    "AuditEvent",
    "AuditLevel",
]
