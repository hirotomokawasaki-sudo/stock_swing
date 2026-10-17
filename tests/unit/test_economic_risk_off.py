"""Tests for the shadow-first economic risk-off state machine."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from stock_swing.guardrails.economic_risk_off import (
    EconomicRiskPolicy,
    EconomicRiskStateError,
    EconomicRiskStore,
    load_cumulative_external_cash_flow,
    load_policy_from_dict,
    trading_session_dates_ending,
)


def _as_of(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 15, 0, tzinfo=timezone.utc)


def _policy(**overrides) -> EconomicRiskPolicy:
    values = {
        "enabled": True,
        "mode": "shadow",
        "lookback_sessions": 5,
        "recovery_sessions_required": 2,
    }
    values.update(overrides)
    return EconomicRiskPolicy(**values)


def _observe_week(
    store: EconomicRiskStore,
    policy: EconomicRiskPolicy,
    equities: list[float],
) -> None:
    for day, equity in zip(range(12, 17), equities, strict=True):
        store.observe(
            policy,
            equity=equity,
            cumulative_external_cash_flow=0.0,
            as_of=_as_of(2026, 10, day),
        )


def test_load_policy_missing_section_is_disabled_shadow() -> None:
    policy = load_policy_from_dict({})
    assert not policy.enabled, "missing config must not silently enforce a new policy"
    assert policy.mode == "shadow"


def test_load_policy_reads_thresholds_and_recovery() -> None:
    policy = load_policy_from_dict(
        {
            "economic_risk_off": {
                "enabled": True,
                "mode": "shadow",
                "lookback_sessions": 5,
                "thresholds": {
                    "reduce_size_pct": -4.0,
                    "block_buys_pct": -6.0,
                    "halt_new_risk_pct": -8.0,
                },
                "recovery": {
                    "reduce_size_above_pct": -3.0,
                    "block_buys_above_pct": -4.5,
                    "halt_new_risk_above_pct": -6.5,
                    "consecutive_sessions": 2,
                },
            }
        }
    )
    assert policy.enabled
    assert policy.block_buys_threshold_pct == pytest.approx(-6.0)
    assert policy.recovery_sessions_required == 2


def test_ac_production_config_starts_shadow_only() -> None:
    """Acceptance: initial rollout must not alter order behavior."""
    project_root = Path(__file__).resolve().parents[2]
    payload = yaml.safe_load(
        (project_root / "config" / "guardrails" / "autonomous_stop.yaml").read_text(
            encoding="utf-8"
        )
    )
    policy = load_policy_from_dict(payload)
    assert policy.enabled
    assert policy.mode == "shadow"
    assert not policy.enforced


def test_load_policy_rejects_reversed_thresholds() -> None:
    with pytest.raises(ValueError, match="halt < block < reduce"):
        load_policy_from_dict(
            {
                "economic_risk_off": {
                    "enabled": True,
                    "thresholds": {
                        "reduce_size_pct": -6.0,
                        "block_buys_pct": -4.0,
                        "halt_new_risk_pct": -8.0,
                    },
                }
            }
        )


def test_external_cash_flow_loader_requires_valid_evidence(tmp_path: Path) -> None:
    path = tmp_path / "equity_bridge_reconciliation.json"
    with pytest.raises(EconomicRiskStateError, match="unavailable"):
        load_cumulative_external_cash_flow(path)

    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(EconomicRiskStateError, match="unavailable"):
        load_cumulative_external_cash_flow(path)

    path.write_text(
        json.dumps(
            {
                "broker_account_id": "paper-account",
                "external_cash_adjustment": 1250.0,
            }
        ),
        encoding="utf-8",
    )
    assert load_cumulative_external_cash_flow(path) == pytest.approx(1250.0)
    assert load_cumulative_external_cash_flow(
        path,
        expected_account_id="paper-account",
    ) == pytest.approx(1250.0)
    with pytest.raises(EconomicRiskStateError, match="unavailable"):
        load_cumulative_external_cash_flow(path, expected_account_id="wrong-account")


def test_trading_session_dates_skip_weekend_and_holiday() -> None:
    dates = trading_session_dates_ending(_as_of(2026, 12, 28).date(), 5)
    assert dates == ["2026-12-21", "2026-12-22", "2026-12-23", "2026-12-24", "2026-12-28"]


def test_same_session_update_preserves_start_equity(tmp_path: Path) -> None:
    store = EconomicRiskStore(tmp_path / "risk.json")
    policy = _policy()
    store.observe(
        policy,
        equity=1_000_000,
        cumulative_external_cash_flow=0,
        as_of=_as_of(2026, 10, 12),
    )
    state = store.observe(
        policy,
        equity=980_000,
        cumulative_external_cash_flow=0,
        as_of=_as_of(2026, 10, 12),
    )
    assert len(state.history) == 1
    assert state.history[0].start_equity == pytest.approx(1_000_000)
    assert state.history[0].latest_equity == pytest.approx(980_000)


def test_metric_waits_for_five_consecutive_sessions(tmp_path: Path) -> None:
    store = EconomicRiskStore(tmp_path / "risk.json")
    policy = _policy()
    for day in range(12, 16):
        state = store.observe(
            policy,
            equity=1_000_000,
            cumulative_external_cash_flow=0,
            as_of=_as_of(2026, 10, day),
        )
    assert state.observed_pct is None
    assert state.data_status == "insufficient_history"


def test_metric_rejects_missing_session_in_window(tmp_path: Path) -> None:
    store = EconomicRiskStore(tmp_path / "risk.json")
    policy = _policy()
    for day in (12, 13, 15, 16, 19):
        state = store.observe(
            policy,
            equity=1_000_000,
            cumulative_external_cash_flow=0,
            as_of=_as_of(2026, 10, day),
        )
    assert state.observed_pct is None
    assert state.data_status == "incomplete_sessions"


def test_cash_flow_adjustment_excludes_deposit_from_return(tmp_path: Path) -> None:
    store = EconomicRiskStore(tmp_path / "risk.json")
    policy = _policy()
    for day in range(12, 16):
        store.observe(
            policy,
            equity=1_000_000,
            cumulative_external_cash_flow=0,
            as_of=_as_of(2026, 10, day),
        )
    state = store.observe(
        policy,
        equity=1_010_000,
        cumulative_external_cash_flow=10_000,
        as_of=_as_of(2026, 10, 16),
    )
    assert state.observed_pct == pytest.approx(0.0)
    assert state.status == "normal"


def test_20261016_weekly_loss_becomes_block_buys_not_operational_halt(tmp_path: Path) -> None:
    """Regression: 2026-10-16 weekly-loss re-HALT at -6.1043%.

    Economic drawdown must live in the recoverable risk-off state machine and
    must never mutate the manually latched operational circuit breaker.
    """
    store = EconomicRiskStore(tmp_path / "risk.json")
    policy = _policy()
    _observe_week(store, policy, [1_000_000, 990_000, 980_000, 970_000, 938_957])
    state = store.load()
    assert state.observed_pct == pytest.approx(-6.1043)
    assert state.status == "block_buys"
    assert state.action == "block_buys"
    assert state.blocks_new_buys


def test_20261012_to_20261016_broker_equity_replay_is_block_buys(tmp_path: Path) -> None:
    """Historical replay from the first/last broker account snapshots."""
    store = EconomicRiskStore(tmp_path / "risk.json")
    policy = _policy()
    observations = [
        (12, 1_006_668.06, 984_866.26),
        (13, 977_025.23, 981_091.72),
        (14, 974_256.89, 943_575.76),
        (15, 939_698.50, 937_279.96),
        (16, 938_206.37, 930_072.28),
    ]
    for day, start, end in observations:
        store.observe(
            policy,
            equity=start,
            cumulative_external_cash_flow=0,
            as_of=_as_of(2026, 10, day),
        )
        state = store.observe(
            policy,
            equity=end,
            cumulative_external_cash_flow=0,
            as_of=_as_of(2026, 10, day),
        )

    assert state.observed_pct == pytest.approx(-7.6088)
    assert state.status == "block_buys"


def test_deep_drawdown_enters_halt_new_risk_without_manual_latch(tmp_path: Path) -> None:
    store = EconomicRiskStore(tmp_path / "risk.json")
    policy = _policy()
    _observe_week(store, policy, [1_000_000, 990_000, 970_000, 950_000, 919_000])
    state = store.load()
    assert state.observed_pct == pytest.approx(-8.1)
    assert state.status == "halt_new_risk"
    assert state.blocks_new_buys
    assert state.effective_size_multiplier(policy) == pytest.approx(0.0)


def test_reduce_size_level_returns_configured_multiplier(tmp_path: Path) -> None:
    store = EconomicRiskStore(tmp_path / "risk.json")
    policy = _policy(size_multiplier=0.4)
    _observe_week(store, policy, [1_000_000, 995_000, 985_000, 975_000, 959_000])
    state = store.load()
    assert state.status == "reduce_size"
    assert state.effective_size_multiplier(policy) == pytest.approx(0.4)


def test_recovery_requires_distinct_sessions_and_steps_down_once(tmp_path: Path) -> None:
    store = EconomicRiskStore(tmp_path / "risk.json")
    policy = _policy()
    _observe_week(store, policy, [1_000_000, 990_000, 980_000, 970_000, 938_957])
    assert store.load().status == "block_buys"

    monday = _as_of(2026, 10, 19)
    first = store.observe(policy, equity=960_000, cumulative_external_cash_flow=0, as_of=monday)
    assert first.status == "block_buys"
    assert first.recovery_sessions == 1

    same_session = store.observe(policy, equity=965_000, cumulative_external_cash_flow=0, as_of=monday)
    assert same_session.status == "block_buys"
    assert same_session.recovery_sessions == 1, "same session must not count twice"

    second = store.observe(
        policy,
        equity=955_000,
        cumulative_external_cash_flow=0,
        as_of=_as_of(2026, 10, 20),
    )
    assert second.status == "reduce_size", "recovery must step down exactly one level"
    assert second.recovery_sessions == 0


def test_recovery_resets_when_metric_deteriorates(tmp_path: Path) -> None:
    store = EconomicRiskStore(tmp_path / "risk.json")
    policy = _policy()
    _observe_week(store, policy, [1_000_000, 990_000, 980_000, 970_000, 938_957])
    improving = store.observe(
        policy,
        equity=960_000,
        cumulative_external_cash_flow=0,
        as_of=_as_of(2026, 10, 19),
    )
    assert improving.recovery_sessions == 1
    deteriorating = store.observe(
        policy,
        equity=895_000,
        cumulative_external_cash_flow=0,
        as_of=_as_of(2026, 10, 20),
    )
    assert deteriorating.status == "halt_new_risk"
    assert deteriorating.recovery_sessions == 0


def test_state_persists_across_reload(tmp_path: Path) -> None:
    path = tmp_path / "risk.json"
    store = EconomicRiskStore(path)
    policy = _policy()
    _observe_week(store, policy, [1_000_000, 990_000, 980_000, 970_000, 938_957])

    reloaded = EconomicRiskStore(path).load()
    assert reloaded.status == "block_buys"
    assert len(reloaded.history) == 5


def test_corrupt_state_fails_closed_instead_of_resetting(tmp_path: Path) -> None:
    path = tmp_path / "risk.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(EconomicRiskStateError, match="state is invalid"):
        EconomicRiskStore(path).load()


def test_non_trading_session_does_not_add_history(tmp_path: Path) -> None:
    store = EconomicRiskStore(tmp_path / "risk.json")
    state = store.observe(
        _policy(),
        equity=1_000_000,
        cumulative_external_cash_flow=0,
        as_of=_as_of(2026, 10, 17),
    )
    assert state.history == []
    assert state.data_status == "non_trading_session"


def test_dry_run_preview_does_not_persist_state(tmp_path: Path) -> None:
    path = tmp_path / "risk.json"
    state = EconomicRiskStore(path).observe(
        _policy(),
        equity=1_000_000,
        cumulative_external_cash_flow=0,
        as_of=_as_of(2026, 10, 12),
        persist=False,
    )
    assert len(state.history) == 1
    assert not path.exists(), "dry-run preview must not mutate operational evidence"
