"""Paper executor for paper-safe order submission.

This module implements paper-mode order submission with all required
pre-submission checks per EXECUTION_POLICY.md.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine.decision_engine import DecisionRecord
from stock_swing.sources.broker_client import BrokerClient


@dataclass
class OrderSubmission:
    """Record of order submission.
    
    Attributes:
        submission_id: Unique submission identifier.
        decision_id: Decision that triggered this submission.
        broker_order_id: Broker-assigned order ID (None until submitted).
        symbol: Stock symbol.
        side: Order side (buy/sell).
        order_type: Order type (market/limit).
        qty: Quantity (shares).
        time_in_force: Time in force.
        limit_price: Limit price if applicable.
        submitted_at: UTC timestamp when submitted.
        status: Order status (pending/submitted/filled/cancelled/rejected).
        broker_status: Latest status from broker.
        reject_reason: Rejection reason if applicable.
    """
    
    submission_id: str
    decision_id: str
    broker_order_id: str | None
    symbol: str
    side: str
    order_type: str
    qty: int
    time_in_force: str
    limit_price: float | None
    submitted_at: datetime
    status: str  # pending, submitted, filled, cancelled, rejected
    broker_status: str | None = None
    reject_reason: str | None = None


@dataclass
class FillRecord:
    """Record of order fill.
    
    Attributes:
        fill_id: Unique fill identifier.
        submission_id: Submission that generated this fill.
        broker_order_id: Broker-assigned order ID.
        symbol: Stock symbol.
        side: Fill side (buy/sell).
        qty: Filled quantity.
        price: Fill price.
        filled_at: UTC timestamp when filled.
        broker_fill_id: Broker-assigned fill ID.
    """
    
    fill_id: str
    submission_id: str
    broker_order_id: str
    symbol: str
    side: str
    qty: int
    price: float
    filled_at: datetime
    broker_fill_id: str | None = None


class PaperExecutor:
    """Paper executor for paper-safe order submission.
    
    This executor implements:
    1. Pre-submission checks (mode, risk, schema, deduplication)
    2. Paper-mode order submission
    3. Order tracking
    
    CRITICAL: This is paper-safe only. Live mode is explicitly blocked.
    """
    
    def __init__(
        self,
        runtime_mode: RuntimeMode,
        broker_client: BrokerClient,
    ):
        """Initialize paper executor.
        
        Args:
            runtime_mode: Current runtime mode.
            broker_client: Broker client for order submission.
            
        Raises:
            ValueError: If runtime_mode is not PAPER.
        """
        # SAFETY: Only allow PAPER mode
        if runtime_mode != RuntimeMode.PAPER:
            raise ValueError(
                f"PaperExecutor only supports PAPER mode, got {runtime_mode.value}"
            )
        
        self.runtime_mode = runtime_mode
        self.broker_client = broker_client
        
        # Track submissions (in-memory for now, would be persisted in production)
        self.submissions: dict[str, OrderSubmission] = {}
        self.fills: dict[str, FillRecord] = {}
        self.decision_to_submission: dict[str, str] = {}  # decision_id -> submission_id
    
    def submit(
        self,
        decision: DecisionRecord,
    ) -> OrderSubmission:
        """Submit order from decision record.
        
        Args:
            decision: Decision record with proposed order.
            
        Returns:
            OrderSubmission record.
            
        Raises:
            ValueError: If pre-submission checks fail.
        """
        # Pre-submission checks
        self._check_runtime_mode()
        self._check_risk_pass(decision)
        self._check_schema_valid(decision)
        self._check_duplicate(decision)
        self._check_actionable(decision)
        
        # Extract order details
        proposed = decision.proposed_order
        if not proposed:
            raise ValueError(f"Decision {decision.decision_id} has no proposed_order")
        
        # Generate submission ID
        submission_id = self._generate_submission_id(decision)
        
        # Submit to broker
        broker_order_id = None
        status = "pending"
        reject_reason = None
        
        try:
            # Submit order (paper mode)
            broker_response = self.broker_client.submit_order(
                symbol=proposed.symbol,
                side=proposed.side,
                order_type=proposed.order_type,
                qty=proposed.qty,
                time_in_force=proposed.time_in_force,
                limit_price=proposed.limit_price,
            )
            
            broker_order_id = broker_response.get("id")
            status = "submitted"
        except Exception as e:
            status = "rejected"
            reject_reason = str(e)
        
        # Create submission record
        submission = OrderSubmission(
            submission_id=submission_id,
            decision_id=decision.decision_id,
            broker_order_id=broker_order_id,
            symbol=proposed.symbol,
            side=proposed.side,
            order_type=proposed.order_type,
            qty=proposed.qty,
            time_in_force=proposed.time_in_force,
            limit_price=proposed.limit_price,
            submitted_at=datetime.now(timezone.utc),
            status=status,
            reject_reason=reject_reason,
        )
        
        # Track submission
        self.submissions[submission_id] = submission
        self.decision_to_submission[decision.decision_id] = submission_id
        
        return submission
    
    def get_submission(self, submission_id: str) -> OrderSubmission | None:
        """Get submission by ID.
        
        Args:
            submission_id: Submission ID.
            
        Returns:
            OrderSubmission or None if not found.
        """
        return self.submissions.get(submission_id)
    
    def _check_runtime_mode(self) -> None:
        """Check runtime mode is PAPER."""
        if self.runtime_mode != RuntimeMode.PAPER:
            raise ValueError(f"PaperExecutor requires PAPER mode, got {self.runtime_mode.value}")
    
    def _check_risk_pass(self, decision: DecisionRecord) -> None:
        """Check risk state is pass."""
        if decision.risk_state != "pass":
            raise ValueError(
                f"Decision {decision.decision_id} has risk_state={decision.risk_state}, must be 'pass'"
            )
    
    def _check_schema_valid(self, decision: DecisionRecord) -> None:
        """Check decision schema is valid."""
        if decision.schema_version != "v1":
            raise ValueError(
                f"Decision {decision.decision_id} has unsupported schema_version={decision.schema_version}"
            )
        
        if decision.action not in {"buy", "sell"}:
            raise ValueError(
                f"Decision {decision.decision_id} has non-executable action={decision.action}"
            )
    
    def _check_duplicate(self, decision: DecisionRecord) -> None:
        """Check for duplicate submission."""
        if decision.decision_id in self.decision_to_submission:
            existing_id = self.decision_to_submission[decision.decision_id]
            raise ValueError(
                f"Decision {decision.decision_id} already submitted as {existing_id}"
            )
    
    def _check_actionable(self, decision: DecisionRecord) -> None:
        """Check decision is actionable."""
        if decision.action == "deny":
            raise ValueError(f"Decision {decision.decision_id} is denied, cannot execute")
        
        if decision.action == "review":
            raise ValueError(f"Decision {decision.decision_id} requires review, cannot execute")
        
        if decision.proposed_order is None:
            raise ValueError(f"Decision {decision.decision_id} has no proposed_order")
    
    def _generate_submission_id(self, decision: DecisionRecord) -> str:
        """Generate deterministic submission ID.
        
        Args:
            decision: Decision record.
            
        Returns:
            Submission ID (UUID string).
        """
        content = f"{decision.decision_id}|{decision.generated_at.isoformat()}"
        hash_digest = hashlib.sha256(content.encode()).digest()
        return str(uuid.UUID(bytes=hash_digest[:16]))
