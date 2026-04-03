"""Reconciler for ensuring order and fill state matches broker truth.

This module implements reconciliation against broker truth per EXECUTION_POLICY.md.
Internal state must not invent fills or positions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from stock_swing.execution.paper_executor import FillRecord, OrderSubmission
from stock_swing.sources.broker_client import BrokerClient


@dataclass
class ReconciliationResult:
    """Result of reconciliation.
    
    Attributes:
        submission_id: Submission being reconciled.
        broker_order_id: Broker order ID.
        reconciled_at: UTC timestamp of reconciliation.
        status_matched: Whether status matches broker.
        broker_status: Broker-reported status.
        internal_status: Internal tracked status.
        fills_detected: List of fills detected from broker.
        discrepancies: List of discrepancies found.
    """
    
    submission_id: str
    broker_order_id: str
    reconciled_at: datetime
    status_matched: bool
    broker_status: str
    internal_status: str
    fills_detected: list[dict[str, Any]] = field(default_factory=list)
    discrepancies: list[str] = field(default_factory=list)


class Reconciler:
    """Reconciler for order and fill state against broker truth.
    
    This reconciler:
    1. Queries broker for order status
    2. Compares broker truth with internal state
    3. Detects fills from broker
    4. Reports discrepancies
    
    CRITICAL: Internal state must not invent fills or positions.
    Broker is source of truth for execution state.
    """
    
    def __init__(self, broker_client: BrokerClient):
        """Initialize reconciler.
        
        Args:
            broker_client: Broker client for querying order state.
        """
        self.broker_client = broker_client
    
    def reconcile(
        self,
        submission: OrderSubmission,
    ) -> ReconciliationResult:
        """Reconcile submission against broker truth.
        
        Args:
            submission: Order submission to reconcile.
            
        Returns:
            ReconciliationResult with broker truth and discrepancies.
            
        Raises:
            ValueError: If submission has no broker_order_id.
        """
        if not submission.broker_order_id:
            raise ValueError(
                f"Submission {submission.submission_id} has no broker_order_id, cannot reconcile"
            )
        
        # Query broker for order state
        broker_order = self._get_broker_order(submission.broker_order_id)
        
        if not broker_order:
            # Broker has no record of this order
            return ReconciliationResult(
                submission_id=submission.submission_id,
                broker_order_id=submission.broker_order_id,
                reconciled_at=datetime.utcnow(),
                status_matched=False,
                broker_status="not_found",
                internal_status=submission.status,
                fills_detected=[],
                discrepancies=["order_not_found_at_broker"],
            )
        
        # Extract broker state
        broker_status = self._normalize_broker_status(broker_order.get("status", "unknown"))
        broker_filled_qty = broker_order.get("filled_qty", 0)
        
        # Compare statuses
        status_matched = self._statuses_match(submission.status, broker_status)
        
        # Detect fills
        fills_detected = []
        if broker_filled_qty > 0:
            # Broker reports fills
            fills_detected.append({
                "qty": broker_filled_qty,
                "avg_price": broker_order.get("filled_avg_price"),
                "filled_at": broker_order.get("filled_at"),
            })
        
        # Detect discrepancies
        discrepancies = []
        if not status_matched:
            discrepancies.append(
                f"status_mismatch: internal={submission.status}, broker={broker_status}"
            )
        
        # Check symbol match
        if broker_order.get("symbol") != submission.symbol:
            discrepancies.append(
                f"symbol_mismatch: internal={submission.symbol}, broker={broker_order.get('symbol')}"
            )
        
        # Check quantity match
        if broker_order.get("qty") != submission.qty:
            discrepancies.append(
                f"qty_mismatch: internal={submission.qty}, broker={broker_order.get('qty')}"
            )
        
        return ReconciliationResult(
            submission_id=submission.submission_id,
            broker_order_id=submission.broker_order_id,
            reconciled_at=datetime.utcnow(),
            status_matched=status_matched,
            broker_status=broker_status,
            internal_status=submission.status,
            fills_detected=fills_detected,
            discrepancies=discrepancies,
        )
    
    def _get_broker_order(self, broker_order_id: str) -> dict[str, Any] | None:
        """Get order from broker.
        
        Args:
            broker_order_id: Broker order ID.
            
        Returns:
            Order dict or None if not found.
        """
        try:
            response = self.broker_client.get_order(broker_order_id)
            return response.payload
        except Exception:
            return None
    
    def _normalize_broker_status(self, status: str) -> str:
        """Normalize broker status to internal status.
        
        Args:
            status: Broker status string.
            
        Returns:
            Normalized status.
        """
        # Alpaca status mapping
        status_map = {
            "new": "submitted",
            "accepted": "submitted",
            "pending_new": "pending",
            "filled": "filled",
            "partially_filled": "partially_filled",
            "canceled": "cancelled",
            "rejected": "rejected",
            "expired": "cancelled",
        }
        
        return status_map.get(status.lower(), status)
    
    def _statuses_match(self, internal: str, broker: str) -> bool:
        """Check if internal and broker statuses match.
        
        Args:
            internal: Internal status.
            broker: Broker status (normalized).
            
        Returns:
            True if statuses match.
        """
        # Simple exact match for now
        # Production would have more sophisticated matching logic
        return internal == broker
