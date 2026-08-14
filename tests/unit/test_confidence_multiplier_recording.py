"""2026-08-14 (roadmap gap #3): tests for confidence_multiplier visibility.

Roadmap gap analysis found PositionSizingPolicy.size() computed a
confidence_multiplier (1.2 for confidence>=0.80, 0.7 for confidence<0.60,
1.0 otherwise) that affected actual position sizing, but never recorded it
anywhere -- not in PositionSizingResult, not in DecisionRecord.evidence, not
in the persisted sizing snapshot. This meant R4-v2's planned "confidence
calibration" work had no historical record of confidence's actual sizing
impact to calibrate against. These tests confirm confidence_multiplier is
now recorded end-to-end: PositionSizingPolicy.size() ->
PositionSizingResult -> PaperExecutor's evidence["sizing"] dict and
DecisionRecord.sizing snapshot.
"""
from __future__ import annotations

import pytest

from stock_swing.risk.position_sizing import PositionSizingInputs, PositionSizingPolicy


class TestConfidenceMultiplierComputedAndRecorded:
    def test_high_confidence_records_multiplier_1_2(self):
        policy = PositionSizingPolicy()
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000, current_price=100, current_total_exposure=0,
            symbol="AVGO", risk_per_share=1, confidence=0.85,
        ))
        assert result.confidence_multiplier == 1.2

    def test_low_confidence_records_multiplier_0_7(self):
        policy = PositionSizingPolicy()
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000, current_price=100, current_total_exposure=0,
            symbol="AVGO", risk_per_share=1, confidence=0.55,
        ))
        assert result.confidence_multiplier == 0.7

    def test_mid_confidence_records_multiplier_1_0(self):
        policy = PositionSizingPolicy()
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000, current_price=100, current_total_exposure=0,
            symbol="AVGO", risk_per_share=1, confidence=0.70,
        ))
        assert result.confidence_multiplier == 1.0

    def test_boundary_at_0_80_uses_high_tier(self):
        policy = PositionSizingPolicy()
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000, current_price=100, current_total_exposure=0,
            symbol="AVGO", risk_per_share=1, confidence=0.80,
        ))
        assert result.confidence_multiplier == 1.2

    def test_boundary_just_below_0_60_uses_low_tier(self):
        policy = PositionSizingPolicy()
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000, current_price=100, current_total_exposure=0,
            symbol="AVGO", risk_per_share=1, confidence=0.599,
        ))
        assert result.confidence_multiplier == 0.7

    def test_none_confidence_records_neutral_multiplier_1_0(self):
        """Missing confidence resolves to the neutral multiplier (1.0),
        matching PositionSizingPolicy.size()'s existing pre-2026-08-14
        sizing logic (confidence_multiplier starts at 1.0 and is only
        adjusted when confidence is not None). This test intentionally
        documents that behavior rather than changing it -- this change's
        scope is purely to make the already-computed value *visible*, not
        to alter sizing semantics for missing-confidence positions.
        Caveat for future calibration work: this means 'no confidence data'
        and 'confidence was in the mid-tier (0.60<=x<0.80)' are
        indistinguishable from confidence_multiplier=1.0 alone -- the
        separate `confidence` field (also recorded) must be checked
        alongside confidence_multiplier to tell them apart."""
        policy = PositionSizingPolicy()
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000, current_price=100, current_total_exposure=0,
            symbol="AVGO", risk_per_share=1, confidence=None,
        ))
        assert result.confidence_multiplier == 1.0


class TestConfidenceMultiplierWiredIntoPaperExecutorEvidence:
    def test_sizing_evidence_dict_includes_confidence_multiplier(self):
        from unittest.mock import MagicMock
        from datetime import datetime, timezone

        from stock_swing.core.runtime import RuntimeMode
        from stock_swing.decision_engine.decision_engine import (
            DecisionRecord, ProposedOrder, PositionSizingSnapshot,
        )
        from stock_swing.execution import PaperExecutor

        broker = MagicMock()
        broker.fetch_account.return_value = MagicMock(payload={"equity": 1_000_000.0})
        broker.fetch_positions.return_value = MagicMock(payload=[])

        executor = PaperExecutor(runtime_mode=RuntimeMode.PAPER, broker_client=broker)

        decision = DecisionRecord(
            decision_id="test-decision-1",
            schema_version="v1",
            generated_at=datetime.now(timezone.utc),
            mode="paper",
            strategy_id="test_strategy",
            strategy_version_id="test_strategy",
            symbol="AVGO",
            action="buy",
            confidence=0.85,  # high conviction -> confidence_multiplier should be 1.2
            signal_strength=0.9,
            risk_state="pass",
            deny_reasons=[],
            requires_operator_approval=False,
            time_horizon="2d",
            evidence={"feature_refs": [], "raw_refs": [], "notes": []},
            proposed_order=ProposedOrder(
                symbol="AVGO", side="buy", order_type="market", qty=0, time_in_force="day",
            ),
            sizing=PositionSizingSnapshot(),
        )

        # Patch the price resolver so a real current_price is available
        # without needing a full broker quote round-trip.
        import stock_swing.execution.paper_executor as pe_module
        original_resolver = pe_module.PriceResolver

        class _StubResolution:
            price = 100.0
            source = "test"
            timestamp = None
            warnings: list = []

        class _StubResolver:
            def __init__(self, *a, **kw):
                pass

            def resolve_entry_sizing_price(self, *a, **kw):
                return _StubResolution()

        pe_module.PriceResolver = _StubResolver
        try:
            qty, details = executor._calculate_position_size(decision=decision)
        finally:
            pe_module.PriceResolver = original_resolver

        assert "confidence_multiplier" in details
        assert details["confidence_multiplier"] == 1.2
        assert decision.sizing.confidence_multiplier == 1.2
