"""10/14 regression cases for the shadow-only staged-exit treatment."""
from __future__ import annotations

import json

import pytest

from stock_swing.risk.shock_aware_staged_exit import (
    ShockAwareStagedExitConfig,
    build_shock_aware_staged_exit_plan,
    log_staged_exit_shadow,
    replay_staged_exit_counterfactual,
)
from stock_swing.strategy_engine.sector_shock_hold import ExitClassification


def _classification(name: str, action: str = "exit") -> ExitClassification:
    return ExitClassification(
        symbol="TEST",
        classification=name,
        confidence="medium",
        recommended_action=action,
    )


def test_1014_amat_broad_shock_would_reduce_one_third():
    plan = build_shock_aware_staged_exit_plan(
        symbol="AMAT",
        exit_trigger="Stop loss triggered",
        baseline_qty=144,
        classification=_classification("sector_shock_hold", "hold"),
        current_return_pct=-0.1272,
        config=ShockAwareStagedExitConfig(),
    )
    assert plan.would_stage
    assert plan.treatment_exit_qty == 48
    assert plan.treatment_hold_qty == 96
    assert plan.confirmation_sessions == 1


def test_1014_amat_asof_open_soft_stop_would_reduce_one_third():
    """At 09:30 ET the later full-day sector shock was not yet observable."""
    plan = build_shock_aware_staged_exit_plan(
        symbol="AMAT",
        exit_trigger="Stop loss triggered",
        baseline_qty=144,
        classification=_classification("soft_stop", "monitor"),
        current_return_pct=-0.1282,
        config=ShockAwareStagedExitConfig(),
    )
    assert plan.would_stage
    assert plan.treatment_exit_qty == 48
    assert plan.reason == "unconfirmed_soft_stop_partial_de_risk"


def test_1014_crdo_relative_weakness_keeps_full_exit():
    plan = build_shock_aware_staged_exit_plan(
        symbol="CRDO",
        exit_trigger="Stop loss triggered",
        baseline_qty=194,
        classification=_classification("relative_weakness_exit"),
        current_return_pct=-0.1806,
        config=ShockAwareStagedExitConfig(),
    )
    assert not plan.would_stage
    assert plan.treatment_exit_qty == 194


def test_1014_cien_emergency_stop_keeps_full_exit():
    plan = build_shock_aware_staged_exit_plan(
        symbol="CIEN",
        exit_trigger="Emergency stop triggered (min_hold bypass)",
        baseline_qty=189,
        classification=_classification("hard_stop"),
        current_return_pct=-0.1673,
        config=ShockAwareStagedExitConfig(),
    )
    assert not plan.would_stage
    assert plan.treatment_exit_qty == 189


def test_insufficient_data_keeps_baseline_exit():
    plan = build_shock_aware_staged_exit_plan(
        symbol="MDB",
        exit_trigger="Stop loss triggered",
        baseline_qty=10,
        classification=_classification("insufficient_data"),
        current_return_pct=-0.08,
        config=ShockAwareStagedExitConfig(),
    )
    assert not plan.would_stage
    assert plan.treatment_exit_qty == 10


def test_missing_current_return_keeps_baseline_exit():
    plan = build_shock_aware_staged_exit_plan(
        symbol="MDB",
        exit_trigger="Stop loss triggered",
        baseline_qty=10,
        classification=_classification("soft_stop", "monitor"),
        current_return_pct=None,
        config=ShockAwareStagedExitConfig(),
    )
    assert not plan.would_stage
    assert plan.reason == "invalid_current_return_requires_full_exit"


def test_one_share_position_cannot_stage():
    plan = build_shock_aware_staged_exit_plan(
        symbol="FICO",
        exit_trigger="Stop loss triggered",
        baseline_qty=1,
        classification=_classification("sector_shock_hold", "hold"),
        current_return_pct=-0.08,
        config=ShockAwareStagedExitConfig(),
    )
    assert not plan.would_stage
    assert plan.treatment_exit_qty == 1


def test_invalid_environment_values_use_safe_defaults(monkeypatch):
    monkeypatch.setenv("SHOCK_AWARE_STAGED_EXIT_PARTIAL_FRACTION", "2")
    monkeypatch.setenv("SHOCK_AWARE_STAGED_EXIT_CONFIRMATION_SESSIONS", "bad")
    monkeypatch.setenv("SHOCK_AWARE_STAGED_EXIT_HARD_CAP_PCT", "2")
    config = ShockAwareStagedExitConfig.from_env()
    assert config.partial_fraction == 1.0 / 3.0
    assert config.confirmation_sessions == 1
    assert config.treatment_hard_cap_pct == -0.15


def test_12pct_hard_cap_sensitivity_keeps_amat_full_exit():
    plan = build_shock_aware_staged_exit_plan(
        symbol="AMAT",
        exit_trigger="Stop loss triggered",
        baseline_qty=144,
        classification=_classification("soft_stop", "monitor"),
        current_return_pct=-0.1282,
        config=ShockAwareStagedExitConfig(treatment_hard_cap_pct=-0.12),
    )
    assert not plan.would_stage
    assert plan.treatment_exit_qty == 144
    assert plan.reason == "treatment_hard_cap_requires_full_exit"


def test_shadow_log_is_structured_jsonl(tmp_path):
    path = tmp_path / "staged.jsonl"
    plan = build_shock_aware_staged_exit_plan(
        symbol="AMAT",
        exit_trigger="Stop loss triggered",
        baseline_qty=144,
        classification=_classification("sector_shock_hold", "hold"),
        current_return_pct=-0.1272,
        config=ShockAwareStagedExitConfig(),
    )
    log_staged_exit_shadow(plan, shadow_log_path=path, run_id="run-1")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["run_id"] == "run-1"
    assert record["baseline_exit_qty"] == 144
    assert record["treatment_exit_qty"] == 48


def test_1014_amat_next_session_path_makes_staged_treatment_worse():
    plan = build_shock_aware_staged_exit_plan(
        symbol="AMAT",
        exit_trigger="Stop loss triggered",
        baseline_qty=144,
        classification=_classification("soft_stop", "monitor"),
        current_return_pct=-0.1282,
        config=ShockAwareStagedExitConfig(),
    )
    result = replay_staged_exit_counterfactual(
        plan=plan,
        average_entry_price=519.99,
        baseline_exit_price=453.2329,
        future_session_closes=[("2026-10-15", 430.01)],
        max_sessions=1,
    )
    assert result.remainder_exit_reason == "treatment_hard_cap"
    assert result.pnl_delta == pytest.approx(-2229.4, abs=1.0)


def test_counterfactual_stops_at_first_hard_cap_without_future_lookahead():
    plan = build_shock_aware_staged_exit_plan(
        symbol="AMAT",
        exit_trigger="Stop loss triggered",
        baseline_qty=144,
        classification=_classification("soft_stop", "monitor"),
        current_return_pct=-0.1282,
        config=ShockAwareStagedExitConfig(),
    )
    first = replay_staged_exit_counterfactual(
        plan=plan,
        average_entry_price=519.99,
        baseline_exit_price=453.2329,
        future_session_closes=[("d1", 430.01), ("d2", 600.0)],
        max_sessions=2,
    )
    second = replay_staged_exit_counterfactual(
        plan=plan,
        average_entry_price=519.99,
        baseline_exit_price=453.2329,
        future_session_closes=[("d1", 430.01), ("d2", 100.0)],
        max_sessions=2,
    )
    assert first.treatment_pnl == second.treatment_pnl
    assert first.sessions_observed == second.sessions_observed == 1


def test_counterfactual_skips_invalid_future_prices():
    plan = build_shock_aware_staged_exit_plan(
        symbol="AMAT",
        exit_trigger="Stop loss triggered",
        baseline_qty=144,
        classification=_classification("soft_stop", "monitor"),
        current_return_pct=-0.1282,
        config=ShockAwareStagedExitConfig(),
    )
    result = replay_staged_exit_counterfactual(
        plan=plan,
        average_entry_price=519.99,
        baseline_exit_price=453.2329,
        future_session_closes=[("bad", "not-a-price"), ("2026-10-15", 430.01)],
        max_sessions=2,
    )
    assert result.remainder_exit_session == "2026-10-15"
    assert result.sessions_observed == 1
