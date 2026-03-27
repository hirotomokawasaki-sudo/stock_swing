"""Tests for paper executor."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine.decision_engine import DecisionRecord, ProposedOrder
from stock_swing.execution import PaperExecutor


def create_test_decision(
    action: str = "buy",
    risk_state: str = "pass",
    proposed_order: ProposedOrder | None = None,
) -> DecisionRecord:
    """Create test decision record."""
    if proposed_order is None and action in {"buy", "sell"}:
        proposed_order = ProposedOrder(
            symbol="AAPL",
            side="buy",
            order_type="market",
            qty=10,
            time_in_force="day",
        )
    
    return DecisionRecord(
        decision_id="test-decision-1",
        schema_version="v1",
        generated_at=datetime.now(timezone.utc),
        mode="paper",
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action=action,
        confidence=0.75,
        signal_strength=0.8,
        risk_state=risk_state,
        deny_reasons=[],
        requires_operator_approval=False,
        time_horizon="3d",
        evidence={"feature_refs": [], "raw_refs": [], "notes": []},
        proposed_order=proposed_order,
    )


def test_paper_executor_init_paper_mode() -> None:
    """Test paper executor initialization in paper mode."""
    broker = MagicMock()
    executor = PaperExecutor(
        runtime_mode=RuntimeMode.PAPER,
        broker_client=broker,
    )
    
    assert executor.runtime_mode == RuntimeMode.PAPER
    assert executor.broker_client == broker


def test_paper_executor_init_rejects_research_mode() -> None:
    """Test paper executor rejects research mode."""
    broker = MagicMock()
    
    with pytest.raises(ValueError, match="only supports PAPER mode"):
        PaperExecutor(
            runtime_mode=RuntimeMode.RESEARCH,
            broker_client=broker,
        )


def test_paper_executor_submit_success() -> None:
    """Test successful order submission."""
    broker = MagicMock()
    broker.submit_order.return_value = {"id": "broker-order-123", "status": "accepted"}
    
    executor = PaperExecutor(
        runtime_mode=RuntimeMode.PAPER,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    submission = executor.submit(decision)
    
    assert submission.decision_id == "test-decision-1"
    assert submission.symbol == "AAPL"
    assert submission.side == "buy"
    assert submission.qty == 10
    assert submission.status == "submitted"
    assert submission.broker_order_id == "broker-order-123"
    
    # Verify broker was called
    broker.submit_order.assert_called_once_with(
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=10,
        time_in_force="day",
        limit_price=None,
    )


def test_paper_executor_submit_reject() -> None:
    """Test order submission rejection."""
    broker = MagicMock()
    broker.submit_order.side_effect = Exception("Insufficient buying power")
    
    executor = PaperExecutor(
        runtime_mode=RuntimeMode.PAPER,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    submission = executor.submit(decision)
    
    assert submission.status == "rejected"
    assert submission.reject_reason == "Insufficient buying power"
    assert submission.broker_order_id is None


def test_paper_executor_check_risk_deny() -> None:
    """Test executor rejects decision with risk_state=deny."""
    broker = MagicMock()
    executor = PaperExecutor(
        runtime_mode=RuntimeMode.PAPER,
        broker_client=broker,
    )
    
    decision = create_test_decision(risk_state="deny")
    
    with pytest.raises(ValueError, match="must be 'pass'"):
        executor.submit(decision)


def test_paper_executor_check_action_deny() -> None:
    """Test executor rejects decision with action=deny."""
    broker = MagicMock()
    executor = PaperExecutor(
        runtime_mode=RuntimeMode.PAPER,
        broker_client=broker,
    )
    
    decision = create_test_decision(action="deny", proposed_order=None)
    
    with pytest.raises(ValueError, match="is denied"):
        executor.submit(decision)


def test_paper_executor_check_duplicate() -> None:
    """Test executor rejects duplicate submission."""
    broker = MagicMock()
    broker.submit_order.return_value = {"id": "broker-order-123"}
    
    executor = PaperExecutor(
        runtime_mode=RuntimeMode.PAPER,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    
    # First submission succeeds
    executor.submit(decision)
    
    # Second submission fails (duplicate)
    with pytest.raises(ValueError, match="already submitted"):
        executor.submit(decision)


def test_paper_executor_get_submission() -> None:
    """Test retrieving submission by ID."""
    broker = MagicMock()
    broker.submit_order.return_value = {"id": "broker-order-123"}
    
    executor = PaperExecutor(
        runtime_mode=RuntimeMode.PAPER,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    submission = executor.submit(decision)
    
    # Retrieve submission
    retrieved = executor.get_submission(submission.submission_id)
    
    assert retrieved is not None
    assert retrieved.submission_id == submission.submission_id
    assert retrieved.decision_id == decision.decision_id


def test_paper_executor_no_proposed_order() -> None:
    """Test executor rejects decision without proposed_order."""
    broker = MagicMock()
    executor = PaperExecutor(
        runtime_mode=RuntimeMode.PAPER,
        broker_client=broker,
    )
    
    decision = create_test_decision(proposed_order=None)
    
    with pytest.raises(ValueError, match="has no proposed_order"):
        executor.submit(decision)
