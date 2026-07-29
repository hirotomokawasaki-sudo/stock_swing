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
    auto_proposed_order: bool = True,
) -> DecisionRecord:
    """Create test decision record."""
    if proposed_order is None and action in {"buy", "sell"} and auto_proposed_order:
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
        strategy_version_id="event_swing_v1@test",
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
    broker.fetch_account.return_value.payload = {"equity": 100_000}
    broker.fetch_positions.return_value.payload = []
    broker.fetch_bars.return_value.payload = {"bars": [{"c": 100.0}]}
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
    # 2026-07-30: DEFAULT_MAX_POSITION_NOTIONAL_PCT 0.06 → 0.08 (80K上限対応)
    # legacy path: equity=$100K, price=$100, notional=0.08*0.5*100K=$4K → 40 shares
    assert submission.qty == 40
    assert submission.status == "submitted"
    assert submission.broker_order_id == "broker-order-123"
    
    # Verify broker was called
    broker.submit_order.assert_called_once_with(
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=40,  # 2026-07-30: 0.08 * 0.5 * 100K / 100 = 40 shares
        time_in_force="day",
        limit_price=None,
    )


def test_paper_executor_submit_reject() -> None:
    """Test order submission rejection."""
    broker = MagicMock()
    broker.fetch_account.return_value.payload = {"equity": 100_000}
    broker.fetch_positions.return_value.payload = []
    broker.fetch_bars.return_value.payload = {"bars": [{"c": 100.0}]}
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
    
    with pytest.raises(ValueError, match="non-executable action=deny"):
        executor.submit(decision)


def test_paper_executor_check_duplicate() -> None:
    """Test executor rejects duplicate submission."""
    broker = MagicMock()
    broker.fetch_account.return_value.payload = {"equity": 100_000}
    broker.fetch_positions.return_value.payload = []
    broker.fetch_bars.return_value.payload = {"bars": [{"c": 100.0}]}
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
    broker.fetch_account.return_value.payload = {"equity": 100_000}
    broker.fetch_positions.return_value.payload = []
    broker.fetch_bars.return_value.payload = {"bars": [{"c": 100.0}]}
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
    
    decision = create_test_decision(proposed_order=None, auto_proposed_order=False)
    
    with pytest.raises(ValueError, match="has no proposed_order"):
        executor.submit(decision)


def test_paper_executor_submit_reuses_precomputed_sizing() -> None:
    """Test precomputed sizing avoids recalculating broker-dependent inputs."""
    broker = MagicMock()
    broker.submit_order.return_value = {"id": "broker-order-123", "status": "accepted"}

    executor = PaperExecutor(
        runtime_mode=RuntimeMode.PAPER,
        broker_client=broker,
    )

    decision = create_test_decision()
    submission = executor.submit(
        decision,
        precomputed_qty=7,
        precomputed_sizing={
            "final_shares": 7,
            "skip_reason": None,
            "remaining_exposure_capacity_usd": 1500.0,
        },
    )

    assert submission.qty == 7
    assert submission.sizing_details["remaining_exposure_capacity_usd"] == 1500.0
    broker.submit_order.assert_called_once_with(
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=7,
        time_in_force="day",
        limit_price=None,
    )
    broker.fetch_account.assert_not_called()
    broker.fetch_positions.assert_not_called()
    broker.fetch_bars.assert_not_called()
