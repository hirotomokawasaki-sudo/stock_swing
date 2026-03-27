"""Tests for production executor."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine.decision_engine import DecisionRecord, ProposedOrder
from stock_swing.execution import ProductionExecutor
from stock_swing.safety import AuditLogger, KillSwitch


def create_test_decision() -> DecisionRecord:
    """Create test decision record."""
    return DecisionRecord(
        decision_id="test-decision-1",
        schema_version="v1",
        generated_at=datetime.now(timezone.utc),
        mode="live_guarded",
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        confidence=0.75,
        signal_strength=0.8,
        risk_state="pass",
        deny_reasons=[],
        requires_operator_approval=True,
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


def test_production_executor_init() -> None:
    """Test production executor initialization."""
    broker = MagicMock()
    kill_switch = KillSwitch()
    audit_logger = AuditLogger()
    
    executor = ProductionExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
        kill_switch=kill_switch,
        audit_logger=audit_logger,
    )
    
    assert executor.kill_switch is kill_switch
    assert executor.audit_logger is audit_logger


def test_production_executor_kill_switch_blocks_approval() -> None:
    """Test kill switch blocks approval request."""
    broker = MagicMock()
    kill_switch = KillSwitch()
    
    executor = ProductionExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
        kill_switch=kill_switch,
    )
    
    # Trigger kill switch
    kill_switch.trigger(reason="Emergency", triggered_by="operator")
    
    decision = create_test_decision()
    
    # Approval request should fail
    with pytest.raises(RuntimeError, match="Kill switch is TRIGGERED"):
        executor.request_approval(decision)


def test_production_executor_kill_switch_blocks_submission() -> None:
    """Test kill switch blocks submission."""
    broker = MagicMock()
    kill_switch = KillSwitch()
    
    executor = ProductionExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
        kill_switch=kill_switch,
    )
    
    decision = create_test_decision()
    
    # Request and approve
    request = executor.request_approval(decision)
    executor.approve(request.request_id)
    
    # Trigger kill switch
    kill_switch.trigger(reason="Emergency", triggered_by="operator")
    
    # Submission should fail
    with pytest.raises(RuntimeError, match="Kill switch is TRIGGERED"):
        executor.submit(decision)


def test_production_executor_audit_logs_approval() -> None:
    """Test audit logging of approval."""
    broker = MagicMock()
    audit_logger = AuditLogger()
    
    executor = ProductionExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
        audit_logger=audit_logger,
    )
    
    decision = create_test_decision()
    
    # Request approval
    request = executor.request_approval(decision)
    
    # Check audit log
    events = audit_logger.query_events(category="approval", action="requested")
    assert len(events) == 1
    assert events[0].subject == request.request_id
    
    # Approve
    executor.approve(request.request_id, operator_id="alice")
    
    # Check audit log
    events = audit_logger.query_events(category="approval", action="approved")
    assert len(events) == 1
    assert events[0].actor == "operator:alice"


def test_production_executor_audit_logs_submission() -> None:
    """Test audit logging of submission."""
    broker = MagicMock()
    broker.submit_order.return_value = {"id": "broker-123", "status": "accepted"}
    audit_logger = AuditLogger()
    
    executor = ProductionExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
        audit_logger=audit_logger,
    )
    
    decision = create_test_decision()
    
    # Request and approve
    request = executor.request_approval(decision)
    executor.approve(request.request_id)
    
    # Submit
    executor.submit(decision)
    
    # Check audit log
    decision_events = audit_logger.query_events(category="decision")
    assert len(decision_events) == 1
    
    submission_events = audit_logger.query_events(category="submission")
    assert len(submission_events) == 1
    assert submission_events[0].context["symbol"] == "AAPL"


def test_production_executor_audit_logs_rejection() -> None:
    """Test audit logging of rejection."""
    broker = MagicMock()
    audit_logger = AuditLogger()
    
    executor = ProductionExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
        audit_logger=audit_logger,
    )
    
    decision = create_test_decision()
    
    # Request approval
    request = executor.request_approval(decision)
    
    # Reject
    executor.reject(request.request_id, reason="Market conditions", operator_id="bob")
    
    # Check audit log
    events = audit_logger.query_events(category="approval", action="rejected")
    assert len(events) == 1
    assert events[0].context["reason"] == "Market conditions"


def test_production_executor_full_workflow() -> None:
    """Test full workflow with safety controls."""
    broker = MagicMock()
    broker.submit_order.return_value = {"id": "broker-123", "status": "accepted"}
    kill_switch = KillSwitch()
    audit_logger = AuditLogger()
    
    executor = ProductionExecutor(
        runtime_mode=RuntimeMode.LIVE_GUARDED,
        broker_client=broker,
        kill_switch=kill_switch,
        audit_logger=audit_logger,
    )
    
    decision = create_test_decision()
    
    # Full workflow
    request = executor.request_approval(decision)
    executor.approve(request.request_id, operator_id="alice")
    submission = executor.submit(decision)
    
    # Verify submission succeeded
    assert submission.broker_order_id == "broker-123"
    
    # Verify audit trail
    events = audit_logger.query_events()
    assert len(events) >= 4  # init + approval request + approve + decision + submission
    
    # Verify kill switch is still active
    assert kill_switch.is_active() is True
