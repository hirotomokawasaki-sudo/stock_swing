"""Tests for audit logger."""

import tempfile
from pathlib import Path

from stock_swing.safety import AuditLevel, AuditLogger


def test_audit_logger_init() -> None:
    """Test audit logger initialization."""
    logger = AuditLogger()
    
    assert logger.min_level == AuditLevel.INFO


def test_audit_logger_log_event() -> None:
    """Test logging an event."""
    logger = AuditLogger()
    
    event = logger.log(
        level=AuditLevel.INFO,
        category="test",
        action="test_action",
        actor="test_actor",
        subject="test_subject",
        details="Test details",
    )
    
    assert event is not None
    assert event.level == AuditLevel.INFO
    assert event.category == "test"
    assert event.action == "test_action"
    assert event.actor == "test_actor"


def test_audit_logger_min_level() -> None:
    """Test minimum level filtering."""
    logger = AuditLogger(min_level=AuditLevel.WARNING)
    
    # INFO should be skipped
    info_event = logger.log(
        level=AuditLevel.INFO,
        category="test",
        action="info",
        actor="test",
    )
    assert info_event is None
    
    # WARNING should be logged
    warning_event = logger.log(
        level=AuditLevel.WARNING,
        category="test",
        action="warning",
        actor="test",
    )
    assert warning_event is not None


def test_audit_logger_log_decision() -> None:
    """Test logging decision event."""
    logger = AuditLogger()
    
    event = logger.log_decision(
        decision_id="decision-123",
        action="buy",
        strategy_id="event_swing_v1",
        symbol="AAPL",
        risk_state="pass",
        mode="paper",
    )
    
    assert event.category == "decision"
    assert event.action == "generated"
    assert event.subject == "decision-123"
    assert event.context["symbol"] == "AAPL"


def test_audit_logger_log_submission() -> None:
    """Test logging submission event."""
    logger = AuditLogger()
    
    event = logger.log_submission(
        submission_id="sub-123",
        decision_id="decision-123",
        symbol="AAPL",
        side="buy",
        qty=10,
        status="submitted",
        broker_order_id="broker-456",
    )
    
    assert event.category == "submission"
    assert event.action == "submitted"
    assert event.context["qty"] == 10


def test_audit_logger_log_approval() -> None:
    """Test logging approval event."""
    logger = AuditLogger()
    
    event = logger.log_approval(
        request_id="req-123",
        decision_id="decision-123",
        status="approved",
        operator_id="alice",
    )
    
    assert event.category == "approval"
    assert event.action == "approved"
    assert event.actor == "operator:alice"


def test_audit_logger_query_events() -> None:
    """Test querying events."""
    logger = AuditLogger()
    
    # Log multiple events
    logger.log_decision("d1", "buy", "s1", "AAPL", "pass", "paper")
    logger.log_decision("d2", "sell", "s1", "MSFT", "pass", "paper")
    logger.log_submission("sub1", "d1", "AAPL", "buy", 10, "submitted")
    
    # Query by category
    decisions = logger.query_events(category="decision")
    assert len(decisions) == 2
    
    submissions = logger.query_events(category="submission")
    assert len(submissions) == 1
    
    # Query with limit
    limited = logger.query_events(limit=1)
    assert len(limited) == 1


def test_audit_logger_persistence() -> None:
    """Test audit log persistence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "audit.log"
        
        logger = AuditLogger(log_file=log_file)
        
        logger.log_decision("d1", "buy", "s1", "AAPL", "pass", "paper")
        logger.log_submission("sub1", "d1", "AAPL", "buy", 10, "submitted")
        
        # Check file exists and has content
        assert log_file.exists()
        content = log_file.read_text()
        assert "decision" in content
        assert "submission" in content
        assert "AAPL" in content
