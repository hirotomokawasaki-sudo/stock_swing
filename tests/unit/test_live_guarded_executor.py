"""Tests for live-guarded executor."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine.decision_engine import DecisionRecord, ProposedOrder
from stock_swing.execution import ApprovalStatus, LiveGuardedExecutor


def create_test_decision(
    requires_approval: bool = True,
    action: str = "buy",
    risk_state: str = "pass",
) -> DecisionRecord:
    """Create test decision record."""
    return DecisionRecord(
        decision_id="test-decision-1",
        schema_version="v1",
        generated_at=datetime.now(timezone.utc),
        mode="live_guarded",
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action=action,
        confidence=0.75,
        signal_strength=0.8,
        risk_state=risk_state,
        deny_reasons=[],
        requires_operator_approval=requires_approval,
        time_horizon="3d",
        evidence={"feature_refs": [], "raw_refs": [], "notes": []},
        proposed_order=ProposedOrder(
            symbol="AAPL",
            side="buy",
            order_type="market",
            qty=10,
            time_in_force="day",
        ),
    )


def test_live_guarded_executor_init() -> None:
    """Test live-guarded executor initialization."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    assert executor.runtime_mode == RuntimeMode.LIVE_GUARDED
    assert executor.broker_client == broker


def test_live_guarded_executor_init_rejects_research() -> None:
    """Test live-guarded executor rejects research mode."""
    broker = MagicMock()
    
    with pytest.raises(ValueError, match="only supports LIVE_GUARDED or PAPER"):
        LiveGuardedExecutor(
            runtime_mode=RuntimeMode.RESEARCH,
            broker_client=broker,
        )


def test_request_approval() -> None:
    """Test approval request creation."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision(requires_approval=True)
    request = executor.request_approval(decision)
    
    assert request.decision_id == "test-decision-1"
    assert request.symbol == "AAPL"
    assert request.side == "buy"
    assert request.qty == 10
    assert request.status == ApprovalStatus.PENDING
    assert request.approved_at is None
    assert request.approved_by is None


def test_request_approval_no_approval_required() -> None:
    """Test approval request fails when approval not required."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision(requires_approval=False)
    
    with pytest.raises(ValueError, match="does not require operator approval"):
        executor.request_approval(decision)


def test_request_approval_non_actionable() -> None:
    """Test approval request fails for non-actionable decision."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision(action="deny")
    
    with pytest.raises(ValueError, match="non-executable action"):
        executor.request_approval(decision)


def test_approve_request() -> None:
    """Test approving an approval request."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    request = executor.request_approval(decision)
    
    # Approve request
    approved = executor.approve(request.request_id, operator_id="alice")
    
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.approved_by == "alice"
    assert approved.approved_at is not None
    assert approved.rejection_reason is None


def test_reject_request() -> None:
    """Test rejecting an approval request."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    request = executor.request_approval(decision)
    
    # Reject request
    rejected = executor.reject(
        request.request_id,
        reason="Market conditions changed",
        operator_id="bob",
    )
    
    assert rejected.status == ApprovalStatus.REJECTED
    assert rejected.approved_by == "bob"
    assert rejected.rejection_reason == "Market conditions changed"


def test_approve_already_approved() -> None:
    """Test approving an already-approved request fails."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    request = executor.request_approval(decision)
    
    # First approval succeeds
    executor.approve(request.request_id)
    
    # Second approval fails
    with pytest.raises(ValueError, match="already approved"):
        executor.approve(request.request_id)


def test_submit_without_approval_fails() -> None:
    """Test submit fails without approval in live-guarded mode."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    
    # Try to submit without approval
    with pytest.raises(ValueError, match="has no approval request"):
        executor.submit(decision)


def test_submit_with_pending_approval_fails() -> None:
    """Test submit fails with pending approval."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    executor.request_approval(decision)
    
    # Try to submit with pending approval
    with pytest.raises(ValueError, match="not approved"):
        executor.submit(decision)


def test_submit_with_approval_succeeds() -> None:
    """Test submit succeeds after approval."""
    broker = MagicMock()
    broker.submit_order.return_value = {"id": "broker-order-123", "status": "accepted"}
    
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    request = executor.request_approval(decision)
    executor.approve(request.request_id)
    
    # Submit should succeed
    submission = executor.submit(decision)
    
    assert submission.decision_id == "test-decision-1"
    assert submission.symbol == "AAPL"
    assert submission.status == "submitted"
    assert submission.broker_order_id == "broker-order-123"


def test_submit_paper_mode_no_approval_needed() -> None:
    """Test submit in paper mode doesn't require approval."""
    broker = MagicMock()
    broker.submit_order.return_value = {"id": "broker-order-123", "status": "accepted"}
    
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.PAPER,
        broker_client=broker,
    )
    
    # Create decision without approval requirement
    decision = create_test_decision(requires_approval=False)
    
    # Submit should succeed without approval
    submission = executor.submit(decision)
    
    assert submission.status == "submitted"


def test_get_approval_request() -> None:
    """Test retrieving approval request by ID."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    request = executor.request_approval(decision)
    
    # Retrieve request
    retrieved = executor.get_approval_request(request.request_id)
    
    assert retrieved is not None
    assert retrieved.request_id == request.request_id
    assert retrieved.decision_id == decision.decision_id


def test_duplicate_approval_request() -> None:
    """Test duplicate approval request returns existing request."""
    broker = MagicMock()
    executor = LiveGuardedExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
    )
    
    decision = create_test_decision()
    
    # First request
    request1 = executor.request_approval(decision)
    
    # Second request for same decision
    request2 = executor.request_approval(decision)
    
    # Should return same request
    assert request1.request_id == request2.request_id
