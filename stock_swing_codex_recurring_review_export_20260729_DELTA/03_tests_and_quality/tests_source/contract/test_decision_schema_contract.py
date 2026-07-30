"""Contract tests for DECISION_SCHEMA.md compliance."""

from datetime import datetime, timezone

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine import DecisionEngine
from stock_swing.strategy_engine.base_strategy import CandidateSignal


def validate_decision_record(decision: dict) -> None:
    """Validate decision record against DECISION_SCHEMA.md.
    
    Args:
        decision: Decision record as dict.
        
    Raises:
        AssertionError: If validation fails.
    """
    # Required fields
    required_fields = [
        "decision_id",
        "schema_version",
        "generated_at",
        "mode",
        "strategy_id",
        "symbol",
        "action",
        "confidence",
        "signal_strength",
        "risk_state",
        "deny_reasons",
        "requires_operator_approval",
        "time_horizon",
        "evidence",
    ]
    
    for field in required_fields:
        assert field in decision, f"Missing required field: {field}"
    
    # Schema version
    assert decision["schema_version"] == "v1"
    
    # Mode validation
    assert decision["mode"] in {"research", "paper", "live_guarded", "live"}
    
    # Action validation
    assert decision["action"] in {"buy", "sell", "hold", "deny", "review"}
    
    # Risk state validation
    assert decision["risk_state"] in {"pass", "deny", "review"}
    
    # Confidence and signal_strength ranges
    assert 0.0 <= decision["confidence"] <= 1.0
    assert 0.0 <= decision["signal_strength"] <= 1.0
    
    # Deny reasons rule
    if decision["action"] == "deny":
        assert len(decision["deny_reasons"]) > 0, "action=deny must have deny_reasons"
    
    # Proposed order rules
    if decision["action"] in {"deny", "hold"}:
        assert decision.get("proposed_order") is None, \
            "proposed_order must be None when action is deny or hold"
    
    # Evidence structure
    assert "feature_refs" in decision["evidence"]
    assert "raw_refs" in decision["evidence"]
    assert "notes" in decision["evidence"]
    assert isinstance(decision["evidence"]["feature_refs"], list)
    assert isinstance(decision["evidence"]["raw_refs"], list)
    assert isinstance(decision["evidence"]["notes"], list)


def test_decision_schema_pass() -> None:
    """Test decision record schema compliance for passed decision."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.8,
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.75,
        reasoning="Test signal",
        feature_refs=["earnings_event"],
        metadata={},
    )
    
    engine = DecisionEngine(runtime_mode=RuntimeMode.PAPER)
    decision_obj = engine.process(candidate)
    
    # Convert to dict for validation
    decision_dict = {
        "decision_id": decision_obj.decision_id,
        "schema_version": decision_obj.schema_version,
        "generated_at": decision_obj.generated_at.isoformat(),
        "mode": decision_obj.mode,
        "strategy_id": decision_obj.strategy_id,
        "symbol": decision_obj.symbol,
        "action": decision_obj.action,
        "confidence": decision_obj.confidence,
        "signal_strength": decision_obj.signal_strength,
        "risk_state": decision_obj.risk_state,
        "deny_reasons": decision_obj.deny_reasons,
        "requires_operator_approval": decision_obj.requires_operator_approval,
        "time_horizon": decision_obj.time_horizon,
        "evidence": decision_obj.evidence,
        "proposed_order": {
            "symbol": decision_obj.proposed_order.symbol,
            "side": decision_obj.proposed_order.side,
            "order_type": decision_obj.proposed_order.order_type,
            "qty": decision_obj.proposed_order.qty,
            "time_in_force": decision_obj.proposed_order.time_in_force,
        } if decision_obj.proposed_order else None,
    }
    
    validate_decision_record(decision_dict)


def test_decision_schema_deny() -> None:
    """Test decision record schema compliance for denied decision."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.3,  # Weak
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.2,  # Low
        reasoning="Weak signal",
        feature_refs=[],
        metadata={},
    )
    
    engine = DecisionEngine(runtime_mode=RuntimeMode.PAPER)
    decision_obj = engine.process(candidate)
    
    decision_dict = {
        "decision_id": decision_obj.decision_id,
        "schema_version": decision_obj.schema_version,
        "generated_at": decision_obj.generated_at.isoformat(),
        "mode": decision_obj.mode,
        "strategy_id": decision_obj.strategy_id,
        "symbol": decision_obj.symbol,
        "action": decision_obj.action,
        "confidence": decision_obj.confidence,
        "signal_strength": decision_obj.signal_strength,
        "risk_state": decision_obj.risk_state,
        "deny_reasons": decision_obj.deny_reasons,
        "requires_operator_approval": decision_obj.requires_operator_approval,
        "time_horizon": decision_obj.time_horizon,
        "evidence": decision_obj.evidence,
        "proposed_order": None,
    }
    
    validate_decision_record(decision_dict)


def test_decision_schema_research_mode() -> None:
    """Test decision record schema compliance in research mode."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.8,
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.75,
        reasoning="Research mode test",
        feature_refs=[],
        metadata={},
    )
    
    engine = DecisionEngine(runtime_mode=RuntimeMode.RESEARCH)
    decision_obj = engine.process(candidate)
    
    assert decision_obj.mode == "research"
    assert decision_obj.action == "hold"
    assert decision_obj.proposed_order is None
    
    decision_dict = {
        "decision_id": decision_obj.decision_id,
        "schema_version": decision_obj.schema_version,
        "generated_at": decision_obj.generated_at.isoformat(),
        "mode": decision_obj.mode,
        "strategy_id": decision_obj.strategy_id,
        "symbol": decision_obj.symbol,
        "action": decision_obj.action,
        "confidence": decision_obj.confidence,
        "signal_strength": decision_obj.signal_strength,
        "risk_state": decision_obj.risk_state,
        "deny_reasons": decision_obj.deny_reasons,
        "requires_operator_approval": decision_obj.requires_operator_approval,
        "time_horizon": decision_obj.time_horizon,
        "evidence": decision_obj.evidence,
        "proposed_order": None,
    }
    
    validate_decision_record(decision_dict)
