"""FIX-006 / FIX-010: Decision export metadata regression tests."""

from __future__ import annotations

import json
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

from stock_swing.core.path_manager import PathManager
from stock_swing.storage.stage_store import StageStore


def _make_store(tmp_path):
    return StageStore(PathManager(tmp_path))


def _decision_stub():
    order = SimpleNamespace(
        symbol="AAPL",
        side="buy",
        order_type="market",
        qty=5,
        time_in_force="day",
        limit_price=None,
    )
    sizing = SimpleNamespace(
        final_shares=5,
        shares_by_risk=5,
        shares_by_notional=5,
        shares_by_exposure=5,
        regime_used="neutral",
        asset_class_used="stock",
        risk_per_share=1.0,
        stop_price=99.0,
        latest_close=100.0,
        atr=1.0,
        max_loss_usd=100.0,
        max_position_notional_usd=500.0,
        remaining_exposure_capacity_usd=10_000.0,
        account_equity=1_000_000.0,
        current_price=100.0,
        current_total_exposure=100_000.0,
        current_sector_exposure=10_000.0,
        sector_used="tech",
        max_sector_exposure_usd=200_000.0,
        remaining_sector_capacity_usd=190_000.0,
        confidence=0.9,
        applied_constraint="risk",
        skip_reason=None,
    )
    return SimpleNamespace(
        decision_id="dec-1",
        schema_version="v1",
        generated_at=datetime.now(timezone.utc),
        mode="paper",
        strategy_id="rule-based",
        strategy_version_id="rule-based-v1",
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        signal_strength=0.8,
        risk_state="pass",
        deny_reasons=[],
        requires_operator_approval=False,
        time_horizon="1d",
        evidence={},
        model="rule-based",
        input_tokens=10,
        output_tokens=5,
        context_pack="evidence_v1",
        prompt_version="rule-based-v1",
        run_id=None,
        experiment_id=None,
        config_hash=None,
        decision_time=None,
        skip_reason=None,
        deny_reason=None,
        block_reason=None,
        usage_source="rule_based_zero",
        input_tokens_actual=0,
        output_tokens_actual=0,
        input_tokens_estimated=None,
        output_tokens_estimated=None,
        proposed_order=order,
        sizing=sizing,
    )


def test_decision_record_has_run_id_top_level():
    """_save_decisions should accept run/experiment/config metadata parameters."""
    from stock_swing.cli.paper_demo import _save_decisions

    params = list(inspect.signature(_save_decisions).parameters.keys())
    assert "run_id" in params
    assert "experiment_id" in params
    assert "config_hash" in params


def test_join_coverage_all_fields_present(tmp_path):
    """Saved decision JSON must include top-level join and token-accounting fields."""
    from stock_swing.cli.paper_demo import _save_decisions

    decision = _decision_stub()
    store = _make_store(tmp_path)
    _save_decisions(
        [decision],
        store,
        "20260729T000000Z",
        run_id="run-1",
        experiment_id="exp-1",
        config_hash="cfg-1",
    )

    saved = next((tmp_path / "data" / "decisions").glob("decision_*.json"))
    payload = json.loads(saved.read_text(encoding="utf-8"))

    for field in ["run_id", "experiment_id", "config_hash", "decision_time", "usage_source"]:
        assert payload.get(field), f"Missing top-level field: {field}"
