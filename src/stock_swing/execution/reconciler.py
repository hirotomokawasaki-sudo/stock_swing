"""Reconciler for ensuring order and fill state matches broker truth.

This module implements reconciliation against broker truth per EXECUTION_POLICY.md.
Internal state must not invent fills or positions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from stock_swing.execution.paper_executor import FillRecord, OrderSubmission
from stock_swing.sources.broker_client import BrokerClient


class DiscrepancyType(str, Enum):
    """Standardized discrepancy types for reconciliation."""
    ORDER_NOT_FOUND = "order_not_found"
    STATUS_MISMATCH = "status_mismatch"
    SYMBOL_MISMATCH = "symbol_mismatch"
    QTY_MISMATCH = "qty_mismatch"
    SIDE_MISMATCH = "side_mismatch"
    PRICE_MISMATCH = "price_mismatch"
    ACCEPTED_NOT_FILLED = "accepted_not_filled"
    FILLED_PENDING_SYNC = "filled_pending_sync"


@dataclass
class Discrepancy:
    """Structured discrepancy information."""
    type: DiscrepancyType
    severity: str  # "critical", "warning", "info"
    message: str
    internal_value: Any = None
    broker_value: Any = None
    resolution_hint: str | None = None


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
    discrepancies: list[Discrepancy] = field(default_factory=list)
    discrepancies_legacy: list[str] = field(default_factory=list)  # Backward compatibility
    symbol: str | None = None
    side: str | None = None


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
            order_not_found = Discrepancy(
                type=DiscrepancyType.ORDER_NOT_FOUND,
                severity="critical",
                message=f"Order {submission.broker_order_id} not found at broker",
                internal_value=submission.broker_order_id,
                broker_value=None,
                resolution_hint="Check if order was rejected or never submitted"
            )
            return ReconciliationResult(
                submission_id=submission.submission_id,
                broker_order_id=submission.broker_order_id,
                reconciled_at=datetime.now(timezone.utc),
                status_matched=False,
                broker_status="not_found",
                internal_status=submission.status,
                fills_detected=[],
                discrepancies=[order_not_found],
                discrepancies_legacy=["order_not_found_at_broker"],
                symbol=submission.symbol,
                side=submission.side,
            )
        
        # Extract broker state
        broker_status = self._normalize_broker_status(broker_order.get("status", "unknown"))
        broker_filled_qty = self._to_number(broker_order.get("filled_qty", 0))
        
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
        discrepancies_legacy = []
        
        if not status_matched:
            disc = Discrepancy(
                type=DiscrepancyType.STATUS_MISMATCH,
                severity="warning",
                message=f"Status mismatch: internal={submission.status}, broker={broker_status}",
                internal_value=submission.status,
                broker_value=broker_status,
                resolution_hint="Wait for broker status to update or investigate order state"
            )
            discrepancies.append(disc)
            discrepancies_legacy.append(f"status_mismatch: internal={submission.status}, broker={broker_status}")
        
        # Check symbol match
        if broker_order.get("symbol") != submission.symbol:
            disc = Discrepancy(
                type=DiscrepancyType.SYMBOL_MISMATCH,
                severity="critical",
                message=f"Symbol mismatch: internal={submission.symbol}, broker={broker_order.get('symbol')}",
                internal_value=submission.symbol,
                broker_value=broker_order.get('symbol'),
                resolution_hint="Critical error - investigate order submission logic"
            )
            discrepancies.append(disc)
            discrepancies_legacy.append(f"symbol_mismatch: internal={submission.symbol}, broker={broker_order.get('symbol')}")
        
        # Check quantity match
        broker_qty = self._to_number(broker_order.get("qty"))
        if broker_qty != submission.qty:
            disc = Discrepancy(
                type=DiscrepancyType.QTY_MISMATCH,
                severity="warning",
                message=f"Quantity mismatch: internal={submission.qty}, broker={broker_qty}",
                internal_value=submission.qty,
                broker_value=broker_qty,
                resolution_hint="May indicate partial fill or order modification"
            )
            discrepancies.append(disc)
            discrepancies_legacy.append(f"qty_mismatch: internal={submission.qty}, broker={broker_order.get('qty')}")
        
        return ReconciliationResult(
            submission_id=submission.submission_id,
            broker_order_id=submission.broker_order_id,
            reconciled_at=datetime.now(timezone.utc),
            status_matched=status_matched,
            broker_status=broker_status,
            internal_status=submission.status,
            fills_detected=fills_detected,
            discrepancies=discrepancies,
            discrepancies_legacy=discrepancies_legacy,
            symbol=submission.symbol,
            side=submission.side,
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
    
    def _to_number(self, value: Any) -> int | float:
        """Convert broker numeric fields that may arrive as strings.

        Alpaca/paper APIs often serialize qty fields as strings like "10" or "0".
        Reconciliation should compare numerically, not lexically.
        """
        if value is None or value == "":
            return 0
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        try:
            if "." in text:
                return float(text)
            return int(text)
        except Exception:
            return 0

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
