"""Live-guarded executor for live execution with operator approval enforcement.

This module extends PaperExecutor to support live-guarded execution mode
with mandatory operator approval for all live orders.

CRITICAL: This is live-guarded mode. Every order requires explicit operator approval.
No autonomous live execution is permitted.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine.decision_engine import DecisionRecord
from stock_swing.execution.paper_executor import OrderSubmission, PaperExecutor
from stock_swing.sources.broker_client import BrokerClient


class ApprovalStatus(Enum):
    """Operator approval status."""
    
    PENDING = "pending"  # Awaiting operator approval
    APPROVED = "approved"  # Operator approved
    REJECTED = "rejected"  # Operator rejected


@dataclass
class ApprovalRequest:
    """Operator approval request for live order.
    
    Attributes:
        request_id: Unique approval request identifier.
        decision_id: Decision requiring approval.
        symbol: Stock symbol.
        side: Order side (buy/sell).
        qty: Quantity.
        order_type: Order type.
        created_at: UTC timestamp when request was created.
        status: Approval status (pending/approved/rejected).
        approved_at: UTC timestamp when approved (None if pending).
        approved_by: Operator identifier who approved (None if pending).
        rejection_reason: Reason for rejection (None if approved/pending).
    """
    
    request_id: str
    decision_id: str
    symbol: str
    side: str
    qty: int
    order_type: str
    created_at: datetime
    status: ApprovalStatus
    approved_at: datetime | None = None
    approved_by: str | None = None
    rejection_reason: str | None = None


class LiveGuardedExecutor(PaperExecutor):
    """Live-guarded executor with mandatory operator approval.
    
    This executor extends PaperExecutor to support live-guarded mode:
    1. Every decision requiring execution generates an approval request
    2. Operator must explicitly approve before order submission
    3. Approval workflow is tracked and auditable
    4. Live mode requires broker configuration with live endpoints
    
    CRITICAL: No autonomous live execution. All orders require operator approval.
    """
    
    def __init__(
        self,
        runtime_mode: RuntimeMode,
        broker_client: BrokerClient,
    ):
        """Initialize live-guarded executor.
        
        Args:
            runtime_mode: Current runtime mode.
            broker_client: Broker client for order submission.
            
        Raises:
            ValueError: If runtime_mode is not LIVE_GUARDED or PAPER.
        """
        # SAFETY: Only allow LIVE_GUARDED or PAPER mode
        if runtime_mode not in {RuntimeMode.LIVE_GUARDED, RuntimeMode.PAPER}:
            raise ValueError(
                f"LiveGuardedExecutor only supports LIVE_GUARDED or PAPER mode, got {runtime_mode.value}"
            )
        
        # Initialize parent (PaperExecutor)
        # Override runtime check since we support LIVE_GUARDED
        self.runtime_mode = runtime_mode
        self.broker_client = broker_client
        
        # Track submissions (inherited from PaperExecutor)
        self.submissions: dict[str, OrderSubmission] = {}
        self.fills: dict[str, OrderSubmission] = {}
        self.decision_to_submission: dict[str, str] = {}
        
        # Track approval requests
        self.approval_requests: dict[str, ApprovalRequest] = {}
        self.decision_to_approval: dict[str, str] = {}  # decision_id -> request_id
    
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
            ValueError: If decision does not require approval or is not actionable.
        """
        # Validate decision requires approval
        if not decision.requires_operator_approval:
            raise ValueError(
                f"Decision {decision.decision_id} does not require operator approval"
            )
        
        # Validate decision is actionable
        if decision.action not in {"buy", "sell"}:
            raise ValueError(
                f"Decision {decision.decision_id} has non-executable action={decision.action}"
            )
        
        if decision.risk_state != "pass":
            raise ValueError(
                f"Decision {decision.decision_id} has risk_state={decision.risk_state}, must be 'pass'"
            )
        
        if not decision.proposed_order:
            raise ValueError(
                f"Decision {decision.decision_id} has no proposed_order"
            )
        
        # Check for existing approval request
        if decision.decision_id in self.decision_to_approval:
            existing_id = self.decision_to_approval[decision.decision_id]
            return self.approval_requests[existing_id]
        
        # Generate request ID
        request_id = self._generate_request_id(decision)
        
        # Create approval request
        proposed = decision.proposed_order
        request = ApprovalRequest(
            request_id=request_id,
            decision_id=decision.decision_id,
            symbol=proposed.symbol,
            side=proposed.side,
            qty=proposed.qty,
            order_type=proposed.order_type,
            created_at=datetime.now(timezone.utc),
            status=ApprovalStatus.PENDING,
        )
        
        # Track request
        self.approval_requests[request_id] = request
        self.decision_to_approval[decision.decision_id] = request_id
        
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
            ValueError: If request not found or already processed.
        """
        if request_id not in self.approval_requests:
            raise ValueError(f"Approval request {request_id} not found")
        
        request = self.approval_requests[request_id]
        
        if request.status != ApprovalStatus.PENDING:
            raise ValueError(
                f"Approval request {request_id} already {request.status.value}"
            )
        
        # Update request
        request.status = ApprovalStatus.APPROVED
        request.approved_at = datetime.now(timezone.utc)
        request.approved_by = operator_id
        
        return request
    
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
            ValueError: If request not found or already processed.
        """
        if request_id not in self.approval_requests:
            raise ValueError(f"Approval request {request_id} not found")
        
        request = self.approval_requests[request_id]
        
        if request.status != ApprovalStatus.PENDING:
            raise ValueError(
                f"Approval request {request_id} already {request.status.value}"
            )
        
        # Update request
        request.status = ApprovalStatus.REJECTED
        request.approved_at = datetime.now(timezone.utc)
        request.approved_by = operator_id
        request.rejection_reason = reason
        
        return request
    
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
            ValueError: If pre-submission checks fail or approval not granted.
        """
        # Pre-submission checks (inherited from PaperExecutor)
        self._check_runtime_mode_guarded()
        self._check_risk_pass(decision)
        self._check_schema_valid(decision)
        self._check_duplicate(decision)
        self._check_actionable(decision)
        
        # CRITICAL: Check approval for live-guarded mode
        if self.runtime_mode == RuntimeMode.LIVE_GUARDED:
            self._check_approval(decision)
        
        # Submit order (use parent method)
        return super(LiveGuardedExecutor, self).submit(decision)
    
    def get_approval_request(self, request_id: str) -> ApprovalRequest | None:
        """Get approval request by ID.
        
        Args:
            request_id: Approval request ID.
            
        Returns:
            ApprovalRequest or None if not found.
        """
        return self.approval_requests.get(request_id)
    
    def _check_runtime_mode_guarded(self) -> None:
        """Check runtime mode is LIVE_GUARDED or PAPER."""
        if self.runtime_mode not in {RuntimeMode.LIVE_GUARDED, RuntimeMode.PAPER}:
            raise ValueError(
                f"LiveGuardedExecutor requires LIVE_GUARDED or PAPER mode, got {self.runtime_mode.value}"
            )
    
    def _check_approval(self, decision: DecisionRecord) -> None:
        """Check operator approval is granted.
        
        Args:
            decision: Decision to check.
            
        Raises:
            ValueError: If approval not granted.
        """
        # Check approval request exists
        if decision.decision_id not in self.decision_to_approval:
            raise ValueError(
                f"Decision {decision.decision_id} has no approval request. "
                f"Call request_approval() first."
            )
        
        # Get approval request
        request_id = self.decision_to_approval[decision.decision_id]
        request = self.approval_requests[request_id]
        
        # Check approval status
        if request.status != ApprovalStatus.APPROVED:
            raise ValueError(
                f"Decision {decision.decision_id} not approved. "
                f"Approval status: {request.status.value}"
            )
    
    def _generate_request_id(self, decision: DecisionRecord) -> str:
        """Generate deterministic approval request ID.
        
        Args:
            decision: Decision record.
            
        Returns:
            Request ID (UUID string).
        """
        content = f"approval|{decision.decision_id}|{decision.generated_at.isoformat()}"
        hash_digest = hashlib.sha256(content.encode()).digest()
        return str(uuid.UUID(bytes=hash_digest[:16]))
