"""Decision engine for transforming candidate signals to actionable decisions.

This module implements the final decision layer that:
1. Validates candidate signals through risk checks
2. Generates decision records compliant with DECISION_SCHEMA.md
3. Enforces runtime mode constraints
4. Produces actionable or denied decisions

CRITICAL: This layer has NO execution authority.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine.risk_validator import RiskState, RiskValidator
from stock_swing.strategy_engine.base_strategy import CandidateSignal


@dataclass
class ProposedOrder:
    """Proposed order structure.
    
    Attributes:
        symbol: Stock symbol.
        side: Order side (buy/sell).
        order_type: Order type (market/limit).
        qty: Quantity (shares).
        time_in_force: Time in force (day/gtc/etc).
        limit_price: Limit price if order_type=limit.
    """
    
    symbol: str
    side: str  # buy, sell
    order_type: str  # market, limit
    qty: int
    time_in_force: str  # day, gtc
    limit_price: float | None = None


@dataclass
class PositionSizingSnapshot:
    """Structured sizing snapshot attached to a decision."""

    final_shares: int | None = None
    shares_by_risk: int | None = None
    shares_by_notional: int | None = None
    shares_by_exposure: int | None = None
    regime_used: str | None = None
    asset_class_used: str | None = None
    risk_per_share: float | None = None
    stop_price: float | None = None
    latest_close: float | None = None
    atr: float | None = None
    max_loss_usd: float | None = None
    max_position_notional_usd: float | None = None
    remaining_exposure_capacity_usd: float | None = None
    account_equity: float | None = None
    current_price: float | None = None
    current_total_exposure: float | None = None
    current_sector_exposure: float | None = None
    sector_used: str | None = None
    max_sector_exposure_usd: float | None = None
    remaining_sector_capacity_usd: float | None = None
    confidence: float | None = None
    applied_constraint: str | None = None
    skip_reason: str | None = None


@dataclass
class DecisionRecord:
    """Final decision record (DECISION_SCHEMA.md compliant).
    
    This is the output of the decision engine.
    Only decisions with action != "deny" and risk_state == "pass" are actionable.
    
    Attributes:
        decision_id: Unique decision identifier.
        schema_version: Schema version (always "v1").
        generated_at: UTC timestamp when decision was generated.
        mode: Runtime mode (research/paper/live_guarded/live).
        strategy_id: Strategy that generated the signal.
        symbol: Stock symbol.
        action: Final action (buy/sell/hold/deny/review).
        confidence: Signal confidence [0.0, 1.0].
        signal_strength: Signal strength [0.0, 1.0].
        risk_state: Risk validation state (pass/deny/review).
        deny_reasons: List of denial reasons (if action=deny).
        requires_operator_approval: Whether operator approval is required.
        time_horizon: Expected hold period.
        evidence: Evidence references (features, raw data, notes).
        proposed_order: Proposed order (None if denied/hold).
    """
    
    decision_id: str
    schema_version: str
    generated_at: datetime
    mode: str
    strategy_id: str
    symbol: str
    action: str
    confidence: float
    signal_strength: float
    risk_state: str
    deny_reasons: list[str]
    requires_operator_approval: bool
    time_horizon: str
    evidence: dict[str, Any]
    proposed_order: ProposedOrder | None
    sizing: PositionSizingSnapshot = field(default_factory=PositionSizingSnapshot)


class DecisionEngine:
    """Decision engine for candidate signal → actionable decision transformation.
    
    This is the final layer before execution. It:
    1. Validates candidates through risk checks
    2. Generates DECISION_SCHEMA.md compliant decision records
    3. Enforces runtime mode constraints
    4. Determines operator approval requirements
    """
    
    def __init__(
        self,
        runtime_mode: RuntimeMode,
        risk_validator: RiskValidator | None = None,
    ):
        """Initialize decision engine.
        
        Args:
            runtime_mode: Current runtime mode.
            risk_validator: Risk validator instance (creates default if None).
        """
        self.runtime_mode = runtime_mode
        self.risk_validator = risk_validator or RiskValidator()
    
    def process(
        self,
        candidate: CandidateSignal,
        current_positions: dict[str, int] | None = None,
    ) -> DecisionRecord:
        """Process a candidate signal into a decision record.
        
        Args:
            candidate: Candidate signal from strategy.
            current_positions: Current positions (symbol → quantity).
            
        Returns:
            DecisionRecord (actionable or denied).
        """
        # Validate through risk checks
        risk_result = self.risk_validator.validate(
            candidate=candidate,
            current_positions=current_positions,
        )
        
        # Generate decision ID
        decision_id = self._generate_decision_id(candidate)
        
        # Determine action and operator approval
        action = candidate.action
        requires_approval = False
        
        if risk_result.risk_state == RiskState.DENY:
            action = "deny"
        elif risk_result.risk_state == RiskState.REVIEW:
            action = "review"
            requires_approval = True
        
        # In live_guarded mode, always require approval
        if self.runtime_mode == RuntimeMode.LIVE_GUARDED and action in {"buy", "sell"}:
            requires_approval = True
        
        # In research mode, never execute
        if self.runtime_mode == RuntimeMode.RESEARCH:
            action = "hold"  # Research mode doesn't execute
        
        # Generate proposed order (only if action is buy/sell and risk passed)
        proposed_order = None
        if action in {"buy", "sell"} and risk_result.risk_state == RiskState.PASS:
            proposed_order = ProposedOrder(
                symbol=candidate.symbol,
                side=action,  # buy or sell
                order_type="market",  # Default to market for now
                qty=10,  # Placeholder - would come from position sizing
                time_in_force="day",
            )
        
        # Build evidence
        evidence = {
            "feature_refs": candidate.feature_refs,
            "raw_refs": [],
            "notes": [candidate.reasoning],
        }
        sizing = PositionSizingSnapshot()
        if isinstance(candidate.metadata, dict):
            if candidate.metadata.get("risk_per_share") is not None:
                evidence["risk_per_share"] = candidate.metadata.get("risk_per_share")
                sizing.risk_per_share = candidate.metadata.get("risk_per_share")
            if candidate.metadata.get("stop_price") is not None:
                evidence["stop_price"] = candidate.metadata.get("stop_price")
                sizing.stop_price = candidate.metadata.get("stop_price")
            if candidate.metadata.get("latest_close") is not None:
                evidence["latest_close"] = candidate.metadata.get("latest_close")
                sizing.latest_close = candidate.metadata.get("latest_close")
            if candidate.metadata.get("atr") is not None:
                evidence["atr"] = candidate.metadata.get("atr")
                sizing.atr = candidate.metadata.get("atr")
        if risk_result.deny_reasons:
            evidence["notes"].extend(risk_result.deny_reasons)
        
        # Create decision record
        decision = DecisionRecord(
            decision_id=decision_id,
            schema_version="v1",
            generated_at=datetime.now(timezone.utc),
            mode=self.runtime_mode.value,
            strategy_id=candidate.strategy_id,
            symbol=candidate.symbol,
            action=action,
            confidence=candidate.confidence,
            signal_strength=candidate.signal_strength,
            risk_state=risk_result.risk_state.value,
            deny_reasons=risk_result.deny_reasons,
            requires_operator_approval=requires_approval,
            time_horizon=candidate.time_horizon,
            evidence=evidence,
            proposed_order=proposed_order,
            sizing=sizing,
        )
        
        return decision
    
    def _generate_decision_id(self, candidate: CandidateSignal) -> str:
        """Generate deterministic decision ID.
        
        Args:
            candidate: Candidate signal.
            
        Returns:
            Decision ID (UUID string).
        """
        # Deterministic ID based on candidate content
        content = (
            f"{candidate.strategy_id}|"
            f"{candidate.symbol}|"
            f"{candidate.action}|"
            f"{candidate.generated_at.isoformat()}"
        )
        hash_digest = hashlib.sha256(content.encode()).digest()
        return str(uuid.UUID(bytes=hash_digest[:16]))
