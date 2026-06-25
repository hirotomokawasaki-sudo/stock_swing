from pathlib import Path

from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore
from stock_swing.guardrails.rule_engine import GuardAction, GuardDecision, TriggeredRule


def _halt_decision() -> GuardDecision:
    return GuardDecision(
        action=GuardAction.halt,
        triggered=[
            TriggeredRule(
                name="mismatch",
                metric="mismatch_count",
                observed=1,
                operator=">=",
                threshold=1,
                action=GuardAction.halt,
                severity="critical",
            )
        ],
    )


def _allow_decision() -> GuardDecision:
    return GuardDecision(action=GuardAction.allow, triggered=[])


def test_circuit_breaker_halt_persists_across_reload(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.json")
    state = store.apply_decision(_halt_decision())
    assert state.is_halted

    store2 = CircuitBreakerStore(tmp_path / "cb.json")
    reloaded = store2.load()
    assert reloaded.is_halted


def test_circuit_breaker_halt_cannot_be_overridden_by_allow(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    state = store.apply_decision(_allow_decision())
    assert state.is_halted


def test_circuit_breaker_manual_clear_resets_to_ok(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    state = store.clear(cleared_by="operator", note="verified safe to resume")
    assert state.status == "ok"
    assert state.cleared_by == "operator"


def test_circuit_breaker_default_state_is_ok(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.json")
    state = store.load()
    assert state.status == "ok"
    assert not state.is_halted


def test_circuit_breaker_degraded_state(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.json")
    decision = GuardDecision(
        action=GuardAction.block_buys,
        triggered=[
            TriggeredRule(
                name="loss",
                metric="daily_loss_pct",
                observed=-3.0,
                operator="<=",
                threshold=-2.0,
                action=GuardAction.block_buys,
                severity="high",
            )
        ],
    )
    state = store.apply_decision(decision)
    assert state.status == "degraded"
    assert not state.is_halted
