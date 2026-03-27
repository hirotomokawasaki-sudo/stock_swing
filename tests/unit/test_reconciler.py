"""Tests for reconciler."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from stock_swing.execution import OrderSubmission, Reconciler


def create_test_submission(
    submission_id: str = "sub-123",
    broker_order_id: str = "broker-order-123",
    status: str = "submitted",
) -> OrderSubmission:
    """Create test order submission."""
    return OrderSubmission(
        submission_id=submission_id,
        decision_id="decision-1",
        broker_order_id=broker_order_id,
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=10,
        time_in_force="day",
        limit_price=None,
        submitted_at=datetime.now(timezone.utc),
        status=status,
    )


def test_reconciler_status_match() -> None:
    """Test reconciler when statuses match."""
    broker = MagicMock()
    broker.get_order.return_value = {
        "payload": {
            "id": "broker-order-123",
            "symbol": "AAPL",
            "qty": 10,
            "status": "accepted",  # Maps to "submitted"
            "filled_qty": 0,
        }
    }
    
    reconciler = Reconciler(broker_client=broker)
    submission = create_test_submission(status="submitted")
    
    result = reconciler.reconcile(submission)
    
    assert result.status_matched is True
    assert result.broker_status == "submitted"
    assert result.internal_status == "submitted"
    assert len(result.discrepancies) == 0


def test_reconciler_status_mismatch() -> None:
    """Test reconciler when statuses don't match."""
    broker = MagicMock()
    broker.get_order.return_value = {
        "payload": {
            "id": "broker-order-123",
            "symbol": "AAPL",
            "qty": 10,
            "status": "filled",
            "filled_qty": 10,
            "filled_avg_price": 180.5,
        }
    }
    
    reconciler = Reconciler(broker_client=broker)
    submission = create_test_submission(status="submitted")
    
    result = reconciler.reconcile(submission)
    
    assert result.status_matched is False
    assert result.broker_status == "filled"
    assert result.internal_status == "submitted"
    assert any("status_mismatch" in d for d in result.discrepancies)


def test_reconciler_fills_detected() -> None:
    """Test reconciler detects fills from broker."""
    broker = MagicMock()
    broker.get_order.return_value = {
        "payload": {
            "id": "broker-order-123",
            "symbol": "AAPL",
            "qty": 10,
            "status": "filled",
            "filled_qty": 10,
            "filled_avg_price": 180.5,
            "filled_at": "2026-03-27T12:00:00Z",
        }
    }
    
    reconciler = Reconciler(broker_client=broker)
    submission = create_test_submission()
    
    result = reconciler.reconcile(submission)
    
    assert len(result.fills_detected) == 1
    fill = result.fills_detected[0]
    assert fill["qty"] == 10
    assert fill["avg_price"] == 180.5


def test_reconciler_order_not_found() -> None:
    """Test reconciler when broker has no record of order."""
    broker = MagicMock()
    broker.get_order.return_value = None
    
    reconciler = Reconciler(broker_client=broker)
    submission = create_test_submission()
    
    result = reconciler.reconcile(submission)
    
    assert result.status_matched is False
    assert result.broker_status == "not_found"
    assert any("order_not_found_at_broker" in d for d in result.discrepancies)


def test_reconciler_symbol_mismatch() -> None:
    """Test reconciler detects symbol mismatch."""
    broker = MagicMock()
    broker.get_order.return_value = {
        "payload": {
            "id": "broker-order-123",
            "symbol": "MSFT",  # Different symbol
            "qty": 10,
            "status": "accepted",
            "filled_qty": 0,
        }
    }
    
    reconciler = Reconciler(broker_client=broker)
    submission = create_test_submission()
    
    result = reconciler.reconcile(submission)
    
    assert any("symbol_mismatch" in d for d in result.discrepancies)


def test_reconciler_qty_mismatch() -> None:
    """Test reconciler detects quantity mismatch."""
    broker = MagicMock()
    broker.get_order.return_value = {
        "payload": {
            "id": "broker-order-123",
            "symbol": "AAPL",
            "qty": 20,  # Different quantity
            "status": "accepted",
            "filled_qty": 0,
        }
    }
    
    reconciler = Reconciler(broker_client=broker)
    submission = create_test_submission()
    
    result = reconciler.reconcile(submission)
    
    assert any("qty_mismatch" in d for d in result.discrepancies)


def test_reconciler_no_broker_order_id() -> None:
    """Test reconciler requires broker_order_id."""
    broker = MagicMock()
    reconciler = Reconciler(broker_client=broker)
    
    submission = create_test_submission(broker_order_id=None)
    
    try:
        reconciler.reconcile(submission)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "no broker_order_id" in str(e)
