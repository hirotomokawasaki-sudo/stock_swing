"""Tests for OpenClaw adapter."""

from datetime import datetime, timezone

from stock_swing.decision_engine.decision_engine import DecisionRecord, ProposedOrder
from stock_swing.execution.paper_executor import FillRecord, OrderSubmission
from stock_swing.execution.reconciler import ReconciliationResult
from stock_swing.openclaw_adapter import (
    DecisionSummarizer,
    ExecutionSummarizer,
    SignalSummarizer,
)
from stock_swing.strategy_engine.base_strategy import CandidateSignal


def test_signal_summarizer_single() -> None:
    """Test signal summarizer with single signal."""
    signal = CandidateSignal(
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        signal_strength=0.75,
        generated_at=datetime.now(timezone.utc),
        time_horizon="3d",
        confidence=0.70,
        reasoning="Strong earnings setup with bullish momentum",
        feature_refs=["earnings_event", "price_momentum"],
        metadata={"momentum": 0.08, "days_until_event": 3},
    )
    
    summary = SignalSummarizer.summarize(signal)
    
    assert "Candidate Signal" in summary
    assert "AAPL" in summary
    assert "BUY" in summary
    assert "75%" in summary
    assert "70%" in summary
    assert "earnings_event" in summary
    assert "candidate signal only" in summary.lower()


def test_signal_summarizer_batch() -> None:
    """Test signal summarizer with multiple signals."""
    signals = [
        CandidateSignal(
            strategy_id="event_swing_v1",
            symbol="AAPL",
            action="buy",
            signal_strength=0.75,
            generated_at=datetime.now(timezone.utc),
            time_horizon="3d",
            confidence=0.70,
            reasoning="Test",
            feature_refs=[],
            metadata={},
        ),
        CandidateSignal(
            strategy_id="breakout_momentum_v1",
            symbol="MSFT",
            action="buy",
            signal_strength=0.80,
            generated_at=datetime.now(timezone.utc),
            time_horizon="2d",
            confidence=0.75,
            reasoning="Test",
            feature_refs=[],
            metadata={},
        ),
    ]
    
    summary = SignalSummarizer.summarize_batch(signals)
    
    assert "Total Signals: 2" in summary
    assert "AAPL" in summary
    assert "MSFT" in summary
    assert "BUY: 2 signals" in summary


def test_decision_summarizer_actionable() -> None:
    """Test decision summarizer with actionable decision."""
    decision = DecisionRecord(
        decision_id="test-decision-1",
        schema_version="v1",
        generated_at=datetime.now(timezone.utc),
        mode="paper",
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        confidence=0.75,
        signal_strength=0.80,
        risk_state="pass",
        deny_reasons=[],
        requires_operator_approval=False,
        time_horizon="3d",
        evidence={"feature_refs": [], "raw_refs": [], "notes": ["Strong signal"]},
        proposed_order=ProposedOrder(
            symbol="AAPL",
            side="buy",
            order_type="market",
            qty=10,
            time_in_force="day",
        ),
    )
    
    summary = DecisionSummarizer.summarize(decision)
    
    assert "BUY" in summary
    assert "AAPL" in summary
    assert "pass" in summary
    assert "Proposed Order" in summary
    assert "10 shares" in summary
    assert "Actionable" in summary


def test_decision_summarizer_denied() -> None:
    """Test decision summarizer with denied decision."""
    decision = DecisionRecord(
        decision_id="test-decision-1",
        schema_version="v1",
        generated_at=datetime.now(timezone.utc),
        mode="paper",
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="deny",
        confidence=0.30,
        signal_strength=0.40,
        risk_state="deny",
        deny_reasons=["signal_strength below minimum"],
        requires_operator_approval=False,
        time_horizon="3d",
        evidence={"feature_refs": [], "raw_refs": [], "notes": []},
        proposed_order=None,
    )
    
    summary = DecisionSummarizer.summarize(decision)
    
    assert "DENY" in summary
    assert "deny" in summary
    assert "signal_strength below minimum" in summary
    assert "Not actionable" in summary


def test_decision_summarizer_batch() -> None:
    """Test decision summarizer with multiple decisions."""
    decisions = [
        DecisionRecord(
            decision_id="d1",
            schema_version="v1",
            generated_at=datetime.now(timezone.utc),
            mode="paper",
            strategy_id="event_swing_v1",
            symbol="AAPL",
            action="buy",
            confidence=0.75,
            signal_strength=0.80,
            risk_state="pass",
            deny_reasons=[],
            requires_operator_approval=False,
            time_horizon="3d",
            evidence={"feature_refs": [], "raw_refs": [], "notes": []},
            proposed_order=ProposedOrder(
                symbol="AAPL",
                side="buy",
                order_type="market",
                qty=10,
                time_in_force="day",
            ),
        ),
        DecisionRecord(
            decision_id="d2",
            schema_version="v1",
            generated_at=datetime.now(timezone.utc),
            mode="paper",
            strategy_id="event_swing_v1",
            symbol="MSFT",
            action="deny",
            confidence=0.30,
            signal_strength=0.40,
            risk_state="deny",
            deny_reasons=["too weak"],
            requires_operator_approval=False,
            time_horizon="3d",
            evidence={"feature_refs": [], "raw_refs": [], "notes": []},
            proposed_order=None,
        ),
    ]
    
    summary = DecisionSummarizer.summarize_batch(decisions)
    
    assert "Total Decisions: 2" in summary
    assert "BUY: 1" in summary
    assert "DENY: 1" in summary
    assert "pass: 1" in summary
    assert "deny: 1" in summary
    assert "Actionable: 1" in summary


def test_execution_summarizer_submission() -> None:
    """Test execution summarizer with order submission."""
    submission = OrderSubmission(
        submission_id="sub-123",
        decision_id="decision-1",
        broker_order_id="broker-order-456",
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=10,
        time_in_force="day",
        limit_price=None,
        submitted_at=datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc),
        status="submitted",
    )
    
    summary = ExecutionSummarizer.summarize_submission(submission)
    
    assert "Order Submission" in summary
    assert "AAPL" in summary
    assert "BUY" in summary
    assert "10 shares" in summary
    assert "broker-order-456" in summary
    assert "submitted" in summary.lower()


def test_execution_summarizer_fill() -> None:
    """Test execution summarizer with fill record."""
    fill = FillRecord(
        fill_id="fill-123",
        submission_id="sub-123",
        broker_order_id="broker-order-456",
        symbol="AAPL",
        side="buy",
        qty=10,
        price=180.50,
        filled_at=datetime(2026, 3, 27, 12, 5, 0, tzinfo=timezone.utc),
        broker_fill_id="broker-fill-789",
    )
    
    summary = ExecutionSummarizer.summarize_fill(fill)
    
    assert "Order Fill" in summary
    assert "AAPL" in summary
    assert "10 shares" in summary
    assert "$180.50" in summary
    assert "$1805.00" in summary  # Total


def test_execution_summarizer_reconciliation() -> None:
    """Test execution summarizer with reconciliation result."""
    result = ReconciliationResult(
        submission_id="sub-123",
        broker_order_id="broker-order-456",
        reconciled_at=datetime(2026, 3, 27, 12, 10, 0, tzinfo=timezone.utc),
        status_matched=True,
        broker_status="filled",
        internal_status="filled",
        fills_detected=[{"qty": 10, "avg_price": 180.50}],
        discrepancies=[],
    )
    
    summary = ExecutionSummarizer.summarize_reconciliation(result)
    
    assert "Reconciliation Result" in summary
    assert "Status Match" in summary
    assert "Yes" in summary
    assert "filled" in summary
    assert "10 shares" in summary
    assert "No discrepancies" in summary


def test_execution_summarizer_reconciliation_discrepancies() -> None:
    """Test execution summarizer with discrepancies."""
    result = ReconciliationResult(
        submission_id="sub-123",
        broker_order_id="broker-order-456",
        reconciled_at=datetime(2026, 3, 27, 12, 10, 0, tzinfo=timezone.utc),
        status_matched=False,
        broker_status="filled",
        internal_status="submitted",
        fills_detected=[],
        discrepancies=["status_mismatch: internal=submitted, broker=filled"],
    )
    
    summary = ExecutionSummarizer.summarize_reconciliation(result)
    
    assert "No" in summary
    assert "Discrepancies Found: 1" in summary
    assert "status_mismatch" in summary


def test_execution_summarizer_batch() -> None:
    """Test execution summarizer with multiple submissions."""
    submissions = [
        OrderSubmission(
            submission_id="sub-1",
            decision_id="d1",
            broker_order_id="b1",
            symbol="AAPL",
            side="buy",
            order_type="market",
            qty=10,
            time_in_force="day",
            limit_price=None,
            submitted_at=datetime.now(timezone.utc),
            status="filled",
        ),
        OrderSubmission(
            submission_id="sub-2",
            decision_id="d2",
            broker_order_id="b2",
            symbol="MSFT",
            side="buy",
            order_type="market",
            qty=5,
            time_in_force="day",
            limit_price=None,
            submitted_at=datetime.now(timezone.utc),
            status="submitted",
        ),
    ]
    
    summary = ExecutionSummarizer.summarize_submissions_batch(submissions)
    
    assert "Total Submissions: 2" in summary
    assert "AAPL" in summary
    assert "MSFT" in summary
    assert "filled: 1" in summary
    assert "submitted: 1" in summary
