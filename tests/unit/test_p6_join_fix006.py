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
        confidence_multiplier=1.2,
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


def test_top_level_sizing_includes_confidence_multiplier(tmp_path):
    """Regression (2026-08-27, R13-B follow-up discovery): confidence_multiplier
    was added to PositionSizingSnapshot 2026-08-14 and correctly reaches
    evidence["sizing"], but was silently missing from the top-level "sizing"
    dict written by _save_decisions -- confirmed against real data (0/2871
    persisted decision JSON files had it at the top level). This is the
    schema's more discoverable location for downstream calibration/analysis
    tooling to read from."""
    from stock_swing.cli.paper_demo import _save_decisions

    decision = _decision_stub()
    store = _make_store(tmp_path)
    _save_decisions(
        [decision],
        store,
        "20260827T000000Z",
        run_id="run-1",
        experiment_id="exp-1",
        config_hash="cfg-1",
    )

    saved = next((tmp_path / "data" / "decisions").glob("decision_*.json"))
    payload = json.loads(saved.read_text(encoding="utf-8"))

    assert "confidence_multiplier" in payload["sizing"]
    assert payload["sizing"]["confidence_multiplier"] == 1.2


def _decision_stub_variant(*, decision_id: str, action: str, symbol: str = "AAPL"):
    d = _decision_stub()
    d.decision_id = decision_id
    d.action = action
    d.symbol = symbol
    d.proposed_order = SimpleNamespace(
        symbol=symbol,
        side=action if action in ("buy", "sell") else "buy",
        order_type="market",
        qty=5,
        time_in_force="day",
        limit_price=None,
    )
    return d


def test_same_symbol_same_run_decisions_do_not_overwrite_each_other(tmp_path):
    """Regression (2026-08-01): decision files for the same symbol within the
    same run must not collide/overwrite.

    Root cause: _save_decisions() previously wrote to
    f"decision_{symbol}_{ts_tag}.json" where ts_tag is fixed for the entire
    run. Any symbol with more than one decision in a single run (e.g. a new
    BUY signal from BreakoutMomentum AND a SELL/exit signal from
    SimpleExitV2 for an existing position in the same symbol — a common,
    routine occurrence) collided on this exact filename. The later write
    silently overwrote the earlier decision's full evidence/sizing/
    confidence with no error, no warning, and no way to recover the lost
    decision short of a single audit-log line.

    Scanning the full decision audit-log history (2026-04 through 2026-07)
    found 700+ such same-symbol/same-run collision groups.

    Fix: filename now includes decision_id (unique per decision), so
    same-symbol/same-run decisions can never collide.

    KILLS mutation: reverting the filename back to
    f"decision_{symbol}_{ts_tag}.json" (dropping the decision_id suffix)
    causes this test to find only 1 saved file instead of 2, with the BUY
    decision's content silently missing.
    """
    from stock_swing.cli.paper_demo import _save_decisions

    buy_decision = _decision_stub_variant(decision_id="buy-dec-1", action="buy", symbol="MSFT")
    sell_decision = _decision_stub_variant(decision_id="sell-dec-1", action="sell", symbol="MSFT")

    store = _make_store(tmp_path)
    # Same ts_tag for both, simulating both decisions generated within one run.
    _save_decisions(
        [buy_decision, sell_decision],
        store,
        "20260801T000000Z",
        run_id="run-1",
        experiment_id="exp-1",
        config_hash="cfg-1",
    )

    saved_files = sorted((tmp_path / "data" / "decisions").glob("decision_MSFT_*.json"))
    assert len(saved_files) == 2, (
        f"Expected 2 distinct saved decision files (buy + sell for MSFT in the "
        f"same run), got {len(saved_files)}: {[f.name for f in saved_files]}. "
        f"This means same-symbol/same-run decisions are still colliding/"
        f"overwriting each other."
    )

    saved_actions = set()
    saved_decision_ids = set()
    for f in saved_files:
        payload = json.loads(f.read_text(encoding="utf-8"))
        saved_actions.add(payload["action"])
        saved_decision_ids.add(payload["decision_id"])

    assert saved_actions == {"buy", "sell"}, (
        f"Both the buy and sell decision content must survive; got actions: {saved_actions}"
    )
    assert saved_decision_ids == {"buy-dec-1", "sell-dec-1"}
