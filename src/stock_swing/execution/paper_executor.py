"""Paper executor for paper-safe order submission.

This module implements paper-mode order submission with all required
pre-submission checks per EXECUTION_POLICY.md.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
import math
from datetime import datetime, timezone
from typing import Any

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine.decision_engine import DecisionRecord
from stock_swing.risk.position_sizing import PositionSizingInputs, PositionSizingPolicy
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
    sizing_details: dict[str, Any] | None = None


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
        self.position_sizing = PositionSizingPolicy()
        
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

        # Recalculate quantity using hybrid position sizing
        market_regime = None
        if isinstance(decision.evidence, dict):
            market_regime = decision.evidence.get("market_regime")
        sized_qty, sizing_details = self._calculate_position_size(decision, market_regime=market_regime or "neutral")
        if sized_qty < 1:
            reason = sizing_details.get("skip_reason") if sizing_details else "final_shares_below_1"
            raise ValueError(f"Decision {decision.decision_id} sized below 1 share, skipping ({reason})")

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
                qty=sized_qty,
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
            qty=sized_qty,
            time_in_force=proposed.time_in_force,
            limit_price=proposed.limit_price,
            submitted_at=datetime.now(timezone.utc),
            status=status,
            reject_reason=reject_reason,
            sizing_details=sizing_details,
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
    
    def _calculate_position_size(
        self,
        decision: DecisionRecord,
        market_regime: str = "neutral",
    ) -> tuple[int, dict[str, Any]]:
        """Calculate hybrid position size using account equity and current exposure.

        Initial implementation uses a default 5% stop-based risk-per-share and
        treats unknown regime as neutral.
        """
        proposed = decision.proposed_order
        if not proposed:
            return 0, {"skip_reason": "missing_proposed_order"}

        account_env = self.broker_client.fetch_account()
        account = account_env.payload if hasattr(account_env, 'payload') else account_env
        equity = float(account.get("equity", 0) or 0)

        positions_env = self.broker_client.fetch_positions()
        positions_resp = positions_env.payload if hasattr(positions_env, 'payload') else positions_env
        current_total_exposure = 0.0
        try:
            for pos in positions_resp:
                qty = float(pos.get("qty", 0) or 0)
                price = float(pos.get("current_price", pos.get("avg_entry_price", 0)) or 0)
                current_total_exposure += abs(qty * price)
        except Exception:
            current_total_exposure = 0.0

        current_price = None
        try:
            latest_env = self.broker_client.fetch_bars(proposed.symbol, timeframe="1Day", limit=1)
            latest = latest_env.payload if hasattr(latest_env, 'payload') else latest_env
            bars = latest.get("bars", []) if isinstance(latest, dict) else latest
            if bars:
                bar = bars[-1]
                current_price = float(bar.get("c") or bar.get("close") or 0)
        except Exception:
            current_price = None

        if not current_price or current_price <= 0:
            current_price = float(proposed.limit_price or 0)
        if not current_price or current_price <= 0:
            return proposed.qty, {
                "fallback": True,
                "reason": "missing_current_price",
                "final_shares": proposed.qty,
            }

        explicit_risk_per_share = None
        if isinstance(decision.evidence, dict):
            explicit_risk_per_share = decision.evidence.get("risk_per_share")

        result = self.position_sizing.size(PositionSizingInputs(
            account_equity=equity,
            current_price=current_price,
            current_total_exposure=current_total_exposure,
            market_regime=market_regime or "neutral",
            risk_per_share=explicit_risk_per_share,
        ))
        details = {
            "account_equity": round(equity, 2),
            "current_price": round(current_price, 4),
            "current_total_exposure": round(current_total_exposure, 2),
            "shares_by_risk": result.shares_by_risk,
            "shares_by_notional": result.shares_by_notional,
            "shares_by_exposure": result.shares_by_exposure,
            "final_shares": result.final_shares,
            "max_loss_usd": result.max_loss_usd,
            "max_position_notional_usd": result.max_position_notional_usd,
            "max_total_exposure_usd": result.max_total_exposure_usd,
            "remaining_exposure_capacity_usd": result.remaining_exposure_capacity_usd,
            "risk_per_share_used": result.risk_per_share_used,
            "regime_used": result.regime_used,
            "skip_reason": result.skip_reason,
        }
        return result.final_shares, details

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
