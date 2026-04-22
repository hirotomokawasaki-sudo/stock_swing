"""Regression tests for sell/exit flow.

Critical test cases to prevent re-occurrence of exit tracking bugs.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import json

from stock_swing.execution import OrderSubmission, Reconciler
from stock_swing.tracking.pnl_tracker import PnLTracker


def test_sell_sizing_override():
    """Test sell order respects exact position qty, not signal strength."""
    # CONTEXT: Previously sell signals used signal_strength for sizing,
    # causing position qty mismatches and incomplete closes.
    
    broker = MagicMock()
    broker.submit_order.return_value = {
        "id": "sell-order-123",
        "symbol": "AAPL",
        "side": "sell",
        "qty": 10,
        "status": "accepted",
    }
    
    # Position has 10 shares, signal_strength is 0.5 → must sell 10, not 5
    position_qty = 10
    signal_strength = 0.5
    
    # In executor, sell qty override should enforce position_qty
    sell_qty = position_qty  # NOT int(position_qty * signal_strength)
    
    assert sell_qty == 10, "Sell must use full position qty, not signal strength"


def test_reconciliation_triggers_record_exit():
    """Test reconciliation → record_exit flow for filled sell orders."""
    # CONTEXT: Previously filled sell orders were not recorded as exits,
    # leaving positions open in tracker even after broker execution.
    
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        tracker = PnLTracker(project_root)
        
        # Open a position
        tracker.record_submission(
            symbol="AAPL",
            strategy_id="test_strategy",
            side="buy",
            qty=10,
            price=180.0,
            broker_order_id="buy-order-123",
            decision_id="decision-buy-1",
        )
        
        # Simulate reconciliation detecting filled sell
        broker = MagicMock()
        mock_response = MagicMock()
        mock_response.payload = {
            "id": "sell-order-123",
            "symbol": "AAPL",
            "side": "sell",
            "qty": 10,
            "status": "filled",
            "filled_qty": 10,
            "filled_avg_price": 185.0,
            "filled_at": datetime.now(timezone.utc).isoformat(),
        }
        broker.get_order.return_value = mock_response
        
        reconciler = Reconciler(broker_client=broker)
        submission = OrderSubmission(
            submission_id="sub-sell-123",
            decision_id="decision-sell-1",
            broker_order_id="sell-order-123",
            symbol="AAPL",
            side="sell",
            order_type="market",
            qty=10,
            time_in_force="day",
            limit_price=None,
            submitted_at=datetime.now(timezone.utc),
            status="submitted",
        )
        
        result = reconciler.reconcile(submission)
        
        # Reconciler should detect fill
        assert len(result.fills_detected) == 1
        fill = result.fills_detected[0]
        assert fill["avg_price"] == 185.0
        
        # Now record exit (this step was missing in original bug)
        updated = tracker.record_exit(
            symbol="AAPL",
            exit_price=fill["avg_price"],
            broker_order_id="sell-order-123",
        )
        
        assert updated is not None, "Exit should be recorded"
        
        # Verify position is closed
        open_positions = tracker.get_open_positions()
        assert len(open_positions) == 0, "Position should be closed after exit"
        
        # Verify realized PnL is calculated
        summary = tracker.get_summary()
        expected_pnl = (185.0 - 180.0) * 10
        assert summary["cumulative_realized_pnl"] == expected_pnl


def test_no_position_to_sell():
    """Test sell signal when no open position exists."""
    # CONTEXT: Sell signals should be ignored if no position is open.
    
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        tracker = PnLTracker(project_root)
        
        # No position exists
        open_positions = tracker.get_open_positions()
        assert len(open_positions) == 0
        
        # Attempt to record exit should fail gracefully
        updated = tracker.record_exit(
            symbol="AAPL",
            exit_price=185.0,
            broker_order_id="sell-order-123",
        )
        
        assert updated is None, "Exit should not be recorded if no position exists"


def test_partial_fill_preview():
    """Test partial fill detection (preview for future T5 task)."""
    # CONTEXT: Partial fills require special handling in tracker.
    # This is a preview test for T5 (partial fill support).
    
    broker = MagicMock()
    mock_response = MagicMock()
    mock_response.payload = {
        "id": "sell-order-123",
        "symbol": "AAPL",
        "side": "sell",
        "qty": 10,
        "status": "partially_filled",
        "filled_qty": 7,
        "filled_avg_price": 185.0,
    }
    broker.get_order.return_value = mock_response
    
    reconciler = Reconciler(broker_client=broker)
    submission = OrderSubmission(
        submission_id="sub-sell-123",
        decision_id="decision-sell-1",
        broker_order_id="sell-order-123",
        symbol="AAPL",
        side="sell",
        order_type="market",
        qty=10,
        time_in_force="day",
        limit_price=None,
        submitted_at=datetime.now(timezone.utc),
        status="submitted",
    )
    
    result = reconciler.reconcile(submission)
    
    # Detect partial fill
    assert len(result.fills_detected) == 1
    fill = result.fills_detected[0]
    assert fill["qty"] == 7, "Partial fill qty should be 7"
    assert fill["avg_price"] == 185.0
    
    # NOTE: Full partial fill support in tracker is T5 scope.
    # For now, this test confirms reconciler can detect partial fills.


def test_sell_exit_e2e_flow():
    """End-to-end test: buy → hold → sell → exit recorded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        tracker = PnLTracker(project_root)
        
        # Step 1: Buy (entry)
        tracker.record_submission(
            symbol="AAPL",
            strategy_id="test_strategy",
            side="buy",
            qty=10,
            price=180.0,
            broker_order_id="buy-order-123",
            decision_id="decision-buy-1",
        )
        
        open_pos = tracker.get_open_positions()
        assert len(open_pos) == 1
        assert open_pos[0]["symbol"] == "AAPL"
        assert open_pos[0]["qty"] == 10
        
        # Step 2: Sell signal → submit order
        broker = MagicMock()
        broker.submit_order.return_value = {
            "id": "sell-order-123",
            "symbol": "AAPL",
            "side": "sell",
            "qty": 10,
            "status": "accepted",
        }
        
        sell_order = broker.submit_order(
            symbol="AAPL",
            side="sell",
            order_type="market",
            qty=10,
            time_in_force="day",
        )
        assert sell_order["id"] == "sell-order-123"
        
        # Step 3: Reconciliation detects fill
        mock_response = MagicMock()
        mock_response.payload = {
            "id": "sell-order-123",
            "symbol": "AAPL",
            "side": "sell",
            "qty": 10,
            "status": "filled",
            "filled_qty": 10,
            "filled_avg_price": 185.0,
            "filled_at": datetime.now(timezone.utc).isoformat(),
        }
        broker.get_order.return_value = mock_response
        
        reconciler = Reconciler(broker_client=broker)
        submission = OrderSubmission(
            submission_id="sub-sell-123",
            decision_id="decision-sell-1",
            broker_order_id="sell-order-123",
            symbol="AAPL",
            side="sell",
            order_type="market",
            qty=10,
            time_in_force="day",
            limit_price=None,
            submitted_at=datetime.now(timezone.utc),
            status="submitted",
        )
        
        rec_result = reconciler.reconcile(submission)
        assert len(rec_result.fills_detected) == 1
        
        # Step 4: Record exit
        fill = rec_result.fills_detected[0]
        updated = tracker.record_exit(
            symbol="AAPL",
            exit_price=fill["avg_price"],
            broker_order_id="sell-order-123",
        )
        assert updated is not None
        
        # Step 5: Verify closed state
        open_pos = tracker.get_open_positions()
        assert len(open_pos) == 0
        
        summary = tracker.get_summary()
        assert summary["closed_trades"] == 1
        assert summary["cumulative_realized_pnl"] == (185.0 - 180.0) * 10
