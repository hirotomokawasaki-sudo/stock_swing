"""Tests for decision engine."""

from datetime import datetime, timezone

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine import DecisionEngine, RiskValidator, RiskState
from stock_swing.strategy_engine.base_strategy import CandidateSignal


def test_risk_validator_pass() -> None:
    """Test risk validator passes valid candidate."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.8,
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.75,
        reasoning="Strong signal",
        feature_refs=["earnings_event", "price_momentum"],
        metadata={},
    )
    
    validator = RiskValidator(
        min_signal_strength=0.6,
        min_confidence=0.5,
    )
    
    result = validator.validate(candidate)
    
    assert result.risk_state == RiskState.PASS
    assert len(result.deny_reasons) == 0


def test_risk_validator_deny_weak_signal() -> None:
    """Test risk validator denies weak signal."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.4,  # Below threshold
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.75,
        reasoning="Weak signal",
        feature_refs=[],
        metadata={},
    )
    
    validator = RiskValidator(min_signal_strength=0.6)
    result = validator.validate(candidate)
    
    assert result.risk_state == RiskState.DENY
    assert len(result.deny_reasons) > 0
    assert any("signal_strength" in reason for reason in result.deny_reasons)


def test_risk_validator_deny_low_confidence() -> None:
    """Test risk validator denies low confidence."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.8,
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.3,  # Below threshold
        reasoning="Low confidence",
        feature_refs=[],
        metadata={},
    )
    
    validator = RiskValidator(min_confidence=0.5)
    result = validator.validate(candidate)
    
    assert result.risk_state == RiskState.DENY
    assert any("confidence" in reason for reason in result.deny_reasons)


def test_decision_engine_pass_paper_mode() -> None:
    """Test decision engine passes valid candidate in paper mode."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.8,
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.75,
        reasoning="Strong signal",
        feature_refs=["earnings_event"],
        metadata={},
    )
    
    engine = DecisionEngine(runtime_mode=RuntimeMode.PAPER)
    decision = engine.process(candidate)
    
    assert decision.schema_version == "v1"
    assert decision.mode == "paper"
    assert decision.strategy_id == "event_swing_v1"
    assert decision.symbol == "AAPL"
    assert decision.action == "buy"
    assert decision.risk_state == "pass"
    assert decision.proposed_order is not None
    assert decision.proposed_order.symbol == "AAPL"
    assert decision.proposed_order.side == "buy"
    assert decision.proposed_order.qty == 10


def test_decision_engine_deny_weak_signal() -> None:
    """Test decision engine denies weak signal."""
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
    decision = engine.process(candidate)
    
    assert decision.action == "deny"
    assert decision.risk_state == "deny"
    assert len(decision.deny_reasons) > 0
    assert decision.proposed_order is None


def test_decision_engine_live_guarded_requires_approval() -> None:
    """Test decision engine requires approval in live_guarded mode."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.8,
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.75,
        reasoning="Strong signal",
        feature_refs=[],
        metadata={},
    )
    
    engine = DecisionEngine(runtime_mode=RuntimeMode.LIVE_GUARDED)
    decision = engine.process(candidate)
    
    assert decision.mode == "live_guarded"
    assert decision.requires_operator_approval is True


def test_decision_engine_research_mode_no_execution() -> None:
    """Test decision engine holds in research mode."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.8,
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.75,
        reasoning="Strong signal",
        feature_refs=[],
        metadata={},
    )
    
    engine = DecisionEngine(runtime_mode=RuntimeMode.RESEARCH)
    decision = engine.process(candidate)
    
    assert decision.mode == "research"
    assert decision.action == "hold"  # Research mode doesn't execute
    assert decision.proposed_order is None


def test_decision_engine_deterministic_id() -> None:
    """Test decision engine generates deterministic IDs."""
    now = datetime.now(timezone.utc)
    
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.8,
        generated_at=now,
        time_horizon="3d",
        confidence=0.75,
        reasoning="Test",
        feature_refs=[],
        metadata={},
    )
    
    engine = DecisionEngine(runtime_mode=RuntimeMode.PAPER)
    decision1 = engine.process(candidate)
    decision2 = engine.process(candidate)
    
    # Same candidate should produce same decision_id
    assert decision1.decision_id == decision2.decision_id


def test_decision_engine_evidence_structure() -> None:
    """Test decision engine includes proper evidence."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.8,
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.75,
        reasoning="Strong earnings setup",
        feature_refs=["earnings_event", "price_momentum"],
        metadata={},
    )
    
    engine = DecisionEngine(runtime_mode=RuntimeMode.PAPER)
    decision = engine.process(candidate)
    
    assert "feature_refs" in decision.evidence
    assert "earnings_event" in decision.evidence["feature_refs"]
    assert "price_momentum" in decision.evidence["feature_refs"]
    assert "notes" in decision.evidence
    assert "Strong earnings setup" in decision.evidence["notes"]


def test_decision_engine_position_limit_check() -> None:
    """Test decision engine respects position limits."""
    candidate = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.8,
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.75,
        reasoning="Test",
        feature_refs=[],
        metadata={},
    )
    
    # Already at position limit
    current_positions = {"AAPL": 100}
    
    validator = RiskValidator(max_position_size=100)
    engine = DecisionEngine(
        runtime_mode=RuntimeMode.PAPER,
        risk_validator=validator,
    )
    decision = engine.process(candidate, current_positions=current_positions)
    
    assert decision.action == "deny"
    assert decision.risk_state == "deny"
    assert any("position_size" in reason for reason in decision.deny_reasons)
