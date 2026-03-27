"""Integration tests for storage layer with PathManager."""

from datetime import datetime
from pathlib import Path

from stock_swing.core.path_manager import PathManager
from stock_swing.core.types import CanonicalRecord, DecisionRecord, RawEnvelope
from stock_swing.storage.stage_store import StageStore


def test_raw_to_normalized_flow(tmp_path: Path) -> None:
    """Test complete flow from raw ingestion to normalized storage."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    # Step 1: Write raw data
    raw_envelope = RawEnvelope(
        source="finnhub",
        endpoint="/stock/metric",
        fetched_at=datetime(2026, 3, 6, 14, 0, 0),
        request_params={"symbol": "AAPL"},
        payload={"metric": {"eps": 6.15}},
    )
    raw_path = store.write_raw("finnhub", "aapl_2026-03-06_raw.json", raw_envelope)

    # Step 2: Write normalized canonical record
    canonical = CanonicalRecord(
        record_id="canonical-123",
        schema_version="v1",
        source="finnhub",
        source_type="fundamentals",
        symbol="AAPL",
        event_type="basic_financials",
        event_time=datetime(2026, 3, 6, 14, 0, 0),
        as_of="2026-03-06",
        ingested_at=datetime(2026, 3, 6, 14, 5, 0),
        timezone="UTC",
        payload_version="v1",
        quality_flags=[],
        payload={"eps": 6.15},
    )
    normalized_path = store.write_normalized("aapl_2026-03-06_canonical.json", canonical)

    # Verify both files exist in correct locations
    assert raw_path.exists()
    assert normalized_path.exists()
    assert "raw" in str(raw_path)
    assert "normalized" in str(normalized_path)


def test_signal_to_decision_flow(tmp_path: Path) -> None:
    """Test flow from signal generation to decision storage."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    # Step 1: Write signal
    signal_data = {
        "symbol": "AAPL",
        "strategy_id": "event_swing_v1",
        "signal": "buy",
        "strength": 0.75,
        "timestamp": datetime(2026, 3, 6, 15, 0, 0),
    }
    signal_path = store.write_signals("aapl_2026-03-06_signal.json", signal_data)

    # Step 2: Write decision
    decision = DecisionRecord(
        decision_id="decision-456",
        schema_version="v1",
        generated_at=datetime(2026, 3, 6, 15, 5, 0),
        mode="paper",
        strategy_id="event_swing_v1",
        symbol="AAPL",
        action="buy",
        confidence=0.72,
        signal_strength=0.75,
        risk_state="pass",
        deny_reasons=[],
        requires_operator_approval=False,
        time_horizon="3d",
        evidence={"signal_ref": "aapl_2026-03-06_signal.json"},
        proposed_order={"symbol": "AAPL", "side": "buy", "qty": 10},
    )
    decision_path = store.write_decisions("aapl_2026-03-06_decision.json", decision)

    # Verify stage separation
    assert signal_path.exists()
    assert decision_path.exists()
    assert "signals" in str(signal_path)
    assert "decisions" in str(decision_path)


def test_audit_trail_storage(tmp_path: Path) -> None:
    """Test audit event storage."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    audit_event = {
        "event_type": "execution_attempt",
        "timestamp": datetime(2026, 3, 6, 16, 0, 0),
        "decision_id": "decision-456",
        "symbol": "AAPL",
        "action": "buy",
        "status": "submitted",
        "broker_order_id": "broker-789",
    }

    audit_path = store.write_audit("2026-03-06_execution_audit.json", audit_event)

    assert audit_path.exists()
    assert "audits" in str(audit_path)
