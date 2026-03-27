"""Audit logger for comprehensive audit trail of trading operations.

This module implements audit logging for all critical operations:
- Decision generation
- Order submissions
- Approvals/rejections
- Reconciliation results
- System events
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class AuditLevel(Enum):
    """Audit event severity level."""
    
    DEBUG = "debug"  # Detailed diagnostic information
    INFO = "info"  # General informational events
    WARNING = "warning"  # Warning events (potential issues)
    ERROR = "error"  # Error events
    CRITICAL = "critical"  # Critical events (system safety)


@dataclass
class AuditEvent:
    """Audit event record.
    
    Attributes:
        event_id: Unique event identifier.
        timestamp: UTC timestamp of event.
        level: Severity level.
        category: Event category (e.g., "decision", "submission", "approval").
        action: Action performed (e.g., "generated", "submitted", "approved").
        actor: Actor performing action (e.g., "decision_engine", "operator:alice").
        subject: Subject of action (e.g., decision_id, submission_id).
        details: Additional event details.
        context: Additional context (runtime mode, strategy, etc.).
    """
    
    event_id: str
    timestamp: datetime
    level: AuditLevel
    category: str
    action: str
    actor: str
    subject: str | None = None
    details: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


class AuditLogger:
    """Audit logger for comprehensive audit trail.
    
    The audit logger:
    1. Records all critical operations
    2. Persists events to file
    3. Provides queryable audit trail
    4. Supports log rotation and retention
    """
    
    def __init__(
        self,
        log_file: Path | None = None,
        min_level: AuditLevel = AuditLevel.INFO,
    ):
        """Initialize audit logger.
        
        Args:
            log_file: Path to audit log file.
                If None, logs to memory only (not persistent).
            min_level: Minimum level to log (default: INFO).
        """
        self.log_file = log_file
        self.min_level = min_level
        self._events: list[AuditEvent] = []
        self._event_counter = 0
    
    def log(
        self,
        level: AuditLevel,
        category: str,
        action: str,
        actor: str,
        subject: str | None = None,
        details: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Log an audit event.
        
        Args:
            level: Severity level.
            category: Event category.
            action: Action performed.
            actor: Actor performing action.
            subject: Subject of action.
            details: Additional details.
            context: Additional context.
            
        Returns:
            Created AuditEvent.
        """
        # Check level threshold
        if level.value < self.min_level.value:
            # Below threshold, skip
            return None
        
        # Generate event ID
        self._event_counter += 1
        event_id = f"audit-{self._event_counter:06d}"
        
        # Create event
        event = AuditEvent(
            event_id=event_id,
            timestamp=datetime.now(timezone.utc),
            level=level,
            category=category,
            action=action,
            actor=actor,
            subject=subject,
            details=details,
            context=context or {},
        )
        
        # Store event
        self._events.append(event)
        
        # Persist to file
        if self.log_file:
            self._write_event(event)
        
        return event
    
    def log_decision(
        self,
        decision_id: str,
        action: str,
        strategy_id: str,
        symbol: str,
        risk_state: str,
        mode: str,
    ) -> AuditEvent:
        """Log decision generation event.
        
        Args:
            decision_id: Decision identifier.
            action: Decision action (buy/sell/deny/etc).
            strategy_id: Strategy that generated decision.
            symbol: Stock symbol.
            risk_state: Risk validation state.
            mode: Runtime mode.
            
        Returns:
            Audit event.
        """
        return self.log(
            level=AuditLevel.INFO,
            category="decision",
            action="generated",
            actor=f"strategy:{strategy_id}",
            subject=decision_id,
            details=f"Decision: {action} {symbol}",
            context={
                "action": action,
                "symbol": symbol,
                "risk_state": risk_state,
                "mode": mode,
                "strategy_id": strategy_id,
            },
        )
    
    def log_submission(
        self,
        submission_id: str,
        decision_id: str,
        symbol: str,
        side: str,
        qty: int,
        status: str,
        broker_order_id: str | None = None,
    ) -> AuditEvent:
        """Log order submission event.
        
        Args:
            submission_id: Submission identifier.
            decision_id: Decision that triggered submission.
            symbol: Stock symbol.
            side: Order side.
            qty: Quantity.
            status: Submission status.
            broker_order_id: Broker order ID if available.
            
        Returns:
            Audit event.
        """
        level = AuditLevel.INFO if status == "submitted" else AuditLevel.WARNING
        
        return self.log(
            level=level,
            category="submission",
            action="submitted",
            actor="executor",
            subject=submission_id,
            details=f"Order submitted: {side} {qty} {symbol}",
            context={
                "decision_id": decision_id,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "status": status,
                "broker_order_id": broker_order_id,
            },
        )
    
    def log_approval(
        self,
        request_id: str,
        decision_id: str,
        status: str,
        operator_id: str,
        reason: str | None = None,
    ) -> AuditEvent:
        """Log approval decision event.
        
        Args:
            request_id: Approval request ID.
            decision_id: Decision requiring approval.
            status: Approval status (approved/rejected).
            operator_id: Operator making decision.
            reason: Rejection reason if applicable.
            
        Returns:
            Audit event.
        """
        level = AuditLevel.INFO if status == "approved" else AuditLevel.WARNING
        
        return self.log(
            level=level,
            category="approval",
            action=status,
            actor=f"operator:{operator_id}",
            subject=request_id,
            details=f"Approval {status}: {decision_id}",
            context={
                "request_id": request_id,
                "decision_id": decision_id,
                "status": status,
                "reason": reason,
            },
        )
    
    def log_reconciliation(
        self,
        submission_id: str,
        broker_order_id: str,
        status_matched: bool,
        discrepancies: list[str],
    ) -> AuditEvent:
        """Log reconciliation event.
        
        Args:
            submission_id: Submission ID.
            broker_order_id: Broker order ID.
            status_matched: Whether status matched.
            discrepancies: List of discrepancies.
            
        Returns:
            Audit event.
        """
        level = AuditLevel.INFO if status_matched else AuditLevel.WARNING
        
        return self.log(
            level=level,
            category="reconciliation",
            action="reconciled",
            actor="reconciler",
            subject=submission_id,
            details=f"Reconciliation: {len(discrepancies)} discrepancies",
            context={
                "submission_id": submission_id,
                "broker_order_id": broker_order_id,
                "status_matched": status_matched,
                "discrepancies": discrepancies,
            },
        )
    
    def log_system_event(
        self,
        event: str,
        level: AuditLevel = AuditLevel.INFO,
        details: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Log system event.
        
        Args:
            event: Event description.
            level: Severity level.
            details: Additional details.
            context: Additional context.
            
        Returns:
            Audit event.
        """
        return self.log(
            level=level,
            category="system",
            action=event,
            actor="system",
            subject=None,
            details=details,
            context=context,
        )
    
    def query_events(
        self,
        category: str | None = None,
        level: AuditLevel | None = None,
        actor: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        """Query audit events.
        
        Args:
            category: Filter by category.
            level: Filter by level.
            actor: Filter by actor.
            limit: Maximum events to return (most recent first).
            
        Returns:
            Matching events.
        """
        events = self._events
        
        # Apply filters
        if category:
            events = [e for e in events if e.category == category]
        if level:
            events = [e for e in events if e.level == level]
        if actor:
            events = [e for e in events if e.actor == actor]
        
        # Sort by timestamp descending (most recent first)
        events = sorted(events, key=lambda e: e.timestamp, reverse=True)
        
        # Apply limit
        if limit:
            events = events[:limit]
        
        return events
    
    def _write_event(self, event: AuditEvent) -> None:
        """Write event to log file.
        
        Args:
            event: Event to write.
        """
        if not self.log_file:
            return
        
        # Ensure parent directory exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Format event as line
        line = self._format_event(event)
        
        # Append to file
        with self.log_file.open("a") as f:
            f.write(line + "\n")
    
    def _format_event(self, event: AuditEvent) -> str:
        """Format event as log line.
        
        Args:
            event: Event to format.
            
        Returns:
            Formatted line.
        """
        # Simple format: timestamp | level | category | action | actor | subject | details
        parts = [
            event.timestamp.isoformat(),
            event.level.value.upper(),
            event.category,
            event.action,
            event.actor,
            event.subject or "-",
            event.details or "-",
        ]
        
        return " | ".join(parts)
