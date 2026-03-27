"""Production-hardened executor with kill switch and audit logging.

This module extends LiveGuardedExecutor with production safety controls:
- Kill switch for emergency stop
- Comprehensive audit logging
- Safety monitoring

CRITICAL: This executor enforces all production safety controls.
"""

from __future__ import annotations

from pathlib import Path

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine.decision_engine import DecisionRecord
from stock_swing.execution.live_guarded_executor import (
    ApprovalRequest,
    LiveGuardedExecutor,
)
from stock_swing.execution.paper_executor import OrderSubmission
from stock_swing.safety import AuditLevel, AuditLogger, KillSwitch
from stock_swing.sources.broker_client import BrokerClient


class ProductionExecutor(LiveGuardedExecutor):
    """Production-hardened executor with safety controls.
    
    This executor extends LiveGuardedExecutor with:
    1. Kill switch check before every submission
    2. Comprehensive audit logging of all operations
    3. Safety monitoring and alerts
    
    CRITICAL: Kill switch is fail-safe. If kill switch check fails,
    execution is blocked.
    """
    
    def __init__(
        self,
        runtime_mode: RuntimeMode,
        broker_client: BrokerClient,
        kill_switch: KillSwitch | None = None,
        audit_logger: AuditLogger | None = None,
    ):
        """Initialize production executor.
        
        Args:
            runtime_mode: Current runtime mode.
            broker_client: Broker client for order submission.
            kill_switch: Kill switch instance (creates default if None).
            audit_logger: Audit logger instance (creates default if None).
            
        Raises:
            ValueError: If runtime_mode is not LIVE_GUARDED or PAPER.
        """
        # Initialize parent (LiveGuardedExecutor)
        super().__init__(runtime_mode, broker_client)
        
        # Initialize safety controls
        self.kill_switch = kill_switch or KillSwitch()
        self.audit_logger = audit_logger or AuditLogger()
        
        # Log initialization
        self.audit_logger.log_system_event(
            event="executor_initialized",
            level=AuditLevel.INFO,
            details=f"ProductionExecutor initialized in {runtime_mode.value} mode",
            context={"runtime_mode": runtime_mode.value},
        )
    
    def request_approval(
        self,
        decision: DecisionRecord,
    ) -> ApprovalRequest:
        """Request operator approval for live order.
        
        Args:
            decision: Decision record requiring approval.
            
        Returns:
            ApprovalRequest record.
            
        Raises:
            RuntimeError: If kill switch is triggered.
            ValueError: If decision does not require approval or is not actionable.
        """
        # CRITICAL: Check kill switch
        self.kill_switch.check()
        
        # Request approval (parent method)
        request = super().request_approval(decision)
        
        # Audit log
        self.audit_logger.log(
            level=AuditLevel.INFO,
            category="approval",
            action="requested",
            actor="executor",
            subject=request.request_id,
            details=f"Approval requested for {decision.symbol} {decision.action}",
            context={
                "decision_id": decision.decision_id,
                "symbol": request.symbol,
                "side": request.side,
                "qty": request.qty,
            },
        )
        
        return request
    
    def approve(
        self,
        request_id: str,
        operator_id: str = "operator",
    ) -> ApprovalRequest:
        """Approve an approval request.
        
        Args:
            request_id: Approval request ID.
            operator_id: Operator identifier approving the request.
            
        Returns:
            Updated ApprovalRequest.
            
        Raises:
            RuntimeError: If kill switch is triggered.
            ValueError: If request not found or already processed.
        """
        # CRITICAL: Check kill switch
        self.kill_switch.check()
        
        # Get request for logging
        request = self.get_approval_request(request_id)
        if not request:
            raise ValueError(f"Approval request {request_id} not found")
        
        # Approve (parent method)
        approved = super().approve(request_id, operator_id)
        
        # Audit log
        self.audit_logger.log_approval(
            request_id=request_id,
            decision_id=request.decision_id,
            status="approved",
            operator_id=operator_id,
        )
        
        return approved
    
    def reject(
        self,
        request_id: str,
        reason: str,
        operator_id: str = "operator",
    ) -> ApprovalRequest:
        """Reject an approval request.
        
        Args:
            request_id: Approval request ID.
            reason: Rejection reason.
            operator_id: Operator identifier rejecting the request.
            
        Returns:
            Updated ApprovalRequest.
            
        Raises:
            RuntimeError: If kill switch is triggered.
            ValueError: If request not found or already processed.
        """
        # CRITICAL: Check kill switch (allow rejections even if triggered)
        # Note: We allow rejections during kill switch to clean up pending approvals
        
        # Get request for logging
        request = self.get_approval_request(request_id)
        if not request:
            raise ValueError(f"Approval request {request_id} not found")
        
        # Reject (parent method)
        rejected = super().reject(request_id, reason, operator_id)
        
        # Audit log
        self.audit_logger.log_approval(
            request_id=request_id,
            decision_id=request.decision_id,
            status="rejected",
            operator_id=operator_id,
            reason=reason,
        )
        
        return rejected
    
    def submit(
        self,
        decision: DecisionRecord,
    ) -> OrderSubmission:
        """Submit order from approved decision.
        
        Args:
            decision: Decision record with proposed order.
            
        Returns:
            OrderSubmission record.
            
        Raises:
            RuntimeError: If kill switch is triggered.
            ValueError: If pre-submission checks fail or approval not granted.
        """
        # CRITICAL: Check kill switch before submission
        self.kill_switch.check()
        
        # Log decision
        self.audit_logger.log_decision(
            decision_id=decision.decision_id,
            action=decision.action,
            strategy_id=decision.strategy_id,
            symbol=decision.symbol,
            risk_state=decision.risk_state,
            mode=decision.mode,
        )
        
        # Submit order (parent method)
        try:
            submission = super().submit(decision)
            
            # Audit log successful submission
            self.audit_logger.log_submission(
                submission_id=submission.submission_id,
                decision_id=decision.decision_id,
                symbol=submission.symbol,
                side=submission.side,
                qty=submission.qty,
                status=submission.status,
                broker_order_id=submission.broker_order_id,
            )
            
            return submission
        
        except Exception as e:
            # Audit log submission failure
            self.audit_logger.log(
                level=AuditLevel.ERROR,
                category="submission",
                action="failed",
                actor="executor",
                subject=decision.decision_id,
                details=f"Submission failed: {str(e)}",
                context={
                    "decision_id": decision.decision_id,
                    "symbol": decision.symbol,
                    "error": str(e),
                },
            )
            raise
