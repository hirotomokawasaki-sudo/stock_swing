"""Kill switch for emergency stop of all trading activity.

This module implements an emergency kill switch that can halt all
trading activity immediately. The kill switch is fail-safe: when in doubt,
it blocks execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class KillSwitchState(Enum):
    """Kill switch state."""
    
    ACTIVE = "active"  # Normal operation, execution allowed
    TRIGGERED = "triggered"  # Kill switch triggered, all execution blocked
    UNKNOWN = "unknown"  # State cannot be determined (fail-safe: block)


@dataclass
class KillSwitchTrigger:
    """Record of kill switch trigger event.
    
    Attributes:
        triggered_at: UTC timestamp when triggered.
        triggered_by: Operator/system identifier.
        reason: Reason for trigger.
        context: Additional context.
    """
    
    triggered_at: datetime
    triggered_by: str
    reason: str
    context: dict[str, str] | None = None


class KillSwitch:
    """Emergency kill switch for halting all trading activity.
    
    The kill switch provides:
    1. Immediate halt of all execution when triggered
    2. Persistent state across restarts
    3. Fail-safe behavior (unknown state = blocked)
    4. Audit trail of trigger events
    
    State is stored in a file for persistence. If the file cannot be read,
    the kill switch defaults to TRIGGERED (fail-safe).
    """
    
    def __init__(self, state_file: Path | None = None):
        """Initialize kill switch.
        
        Args:
            state_file: Path to kill switch state file.
                If None, uses in-memory state (not persistent).
        """
        self.state_file = state_file
        self._state = KillSwitchState.ACTIVE
        self._trigger_history: list[KillSwitchTrigger] = []
        
        # Load state from file if provided
        if self.state_file and self.state_file.exists():
            self._load_state()
    
    def is_active(self) -> bool:
        """Check if kill switch allows execution.
        
        Returns:
            True if execution is allowed, False otherwise.
            
        Note:
            Returns False if state is UNKNOWN (fail-safe).
        """
        state = self.get_state()
        return state == KillSwitchState.ACTIVE
    
    def get_state(self) -> KillSwitchState:
        """Get current kill switch state.
        
        Returns:
            Current state.
            
        Note:
            If state file exists but cannot be read, returns TRIGGERED (fail-safe).
        """
        if self.state_file and self.state_file.exists():
            # Reload from file to ensure freshness
            try:
                self._load_state()
            except Exception:
                # Fail-safe: if we can't read state, assume triggered
                return KillSwitchState.TRIGGERED
        
        return self._state
    
    def trigger(
        self,
        reason: str,
        triggered_by: str = "system",
        context: dict[str, str] | None = None,
    ) -> None:
        """Trigger kill switch to halt all execution.
        
        Args:
            reason: Reason for triggering kill switch.
            triggered_by: Operator/system identifier.
            context: Additional context information.
        """
        self._state = KillSwitchState.TRIGGERED
        
        # Record trigger event
        trigger = KillSwitchTrigger(
            triggered_at=datetime.now(timezone.utc),
            triggered_by=triggered_by,
            reason=reason,
            context=context,
        )
        self._trigger_history.append(trigger)
        
        # Persist state
        if self.state_file:
            self._save_state()
    
    def reset(self, operator_id: str = "operator") -> None:
        """Reset kill switch to active state.
        
        Args:
            operator_id: Operator identifier resetting the switch.
            
        Note:
            Reset requires explicit operator action. This is a safety measure
            to ensure accidental triggers don't auto-recover.
        """
        self._state = KillSwitchState.ACTIVE
        
        # Persist state
        if self.state_file:
            self._save_state()
    
    def check(self) -> None:
        """Check kill switch state and raise if triggered.
        
        Raises:
            RuntimeError: If kill switch is triggered or unknown.
        """
        state = self.get_state()
        
        if state == KillSwitchState.TRIGGERED:
            raise RuntimeError(
                "Kill switch is TRIGGERED. All execution is blocked. "
                "An operator must explicitly reset the kill switch."
            )
        elif state == KillSwitchState.UNKNOWN:
            raise RuntimeError(
                "Kill switch state is UNKNOWN. Execution blocked (fail-safe). "
                "Check kill switch state file and reset if appropriate."
            )
    
    def get_trigger_history(self) -> list[KillSwitchTrigger]:
        """Get history of kill switch triggers.
        
        Returns:
            List of trigger events (most recent last).
        """
        return self._trigger_history.copy()
    
    def _load_state(self) -> None:
        """Load state from file.
        
        Raises:
            Exception: If state file cannot be read or is invalid.
        """
        if not self.state_file or not self.state_file.exists():
            return
        
        # Simple file-based state: "active" or "triggered"
        content = self.state_file.read_text().strip().lower()
        
        if content == "active":
            self._state = KillSwitchState.ACTIVE
        elif content == "triggered":
            self._state = KillSwitchState.TRIGGERED
        else:
            # Invalid content: fail-safe to triggered
            self._state = KillSwitchState.TRIGGERED
    
    def _save_state(self) -> None:
        """Save state to file."""
        if not self.state_file:
            return
        
        # Ensure parent directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write state
        content = self._state.value
        self.state_file.write_text(content)
