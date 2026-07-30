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
    """Backward-compat: default (require_verification=False) still goes to ok."""
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    state = store.clear(cleared_by="operator", note="verified safe to resume")
    assert state.status == "ok"
    assert state.cleared_by == "operator"


# ── R0-v2-A: recovery_pending state machine ──────────────────────────────── #

def test_clear_returns_recovery_pending_when_verification_required(tmp_path: Path) -> None:
    """clear(require_verification=True) → recovery_pending, not ok."""
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    state = store.clear(
        cleared_by="operator",
        note="verified safe to resume",
        require_verification=True,
    )
    assert state.status == "recovery_pending"
    assert state.is_recovery_pending
    assert not state.is_halted
    assert state.cleared_by == "operator"
    assert state.reason == "manual_clear"


def test_clear_force_ok_records_force_reason(tmp_path: Path) -> None:
    """clear(require_verification=False) records manual_clear_force_ok as reason."""
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    state = store.clear(
        cleared_by="operator",
        note="emergency override, root cause confirmed",
        require_verification=False,
    )
    assert state.status == "ok"
    assert state.reason == "manual_clear_force_ok"


def test_recovery_pending_is_not_ok_and_not_halted(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    state = store.clear(cleared_by="op", note="safe", require_verification=True)
    assert state.status == "recovery_pending"
    assert not state.is_halted
    assert not (state.status == "ok")


def test_recovery_pending_persists_across_reload(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    store.clear(cleared_by="op", note="safe", require_verification=True)

    store2 = CircuitBreakerStore(tmp_path / "cb.json")
    reloaded = store2.load()
    assert reloaded.status == "recovery_pending"


def test_recovery_pending_not_auto_cleared_by_allow_decision(tmp_path: Path) -> None:
    """apply_decision(allow) does NOT auto-clear recovery_pending to ok."""
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    store.clear(cleared_by="op", note="safe", require_verification=True)

    # Simulate post-run metrics_normalized path
    state = store.apply_decision(_allow_decision())
    assert state.status == "recovery_pending", (
        "recovery_pending should only exit via mark_clean_run_complete()"
    )


def test_mark_clean_run_complete_transitions_to_ok(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    store.clear(cleared_by="op", note="safe", require_verification=True)
    assert store.load().status == "recovery_pending"

    state = store.mark_clean_run_complete()
    assert state.status == "ok"
    assert state.reason == "clean_run_verified"

    # Persisted too
    reloaded = store.load()
    assert reloaded.status == "ok"


def test_mark_clean_run_complete_noop_when_already_ok(tmp_path: Path) -> None:
    """mark_clean_run_complete is a no-op when already ok."""
    store = CircuitBreakerStore(tmp_path / "cb.json")
    state = store.mark_clean_run_complete()
    assert state.status == "ok"


def test_mark_clean_run_complete_noop_when_halted(tmp_path: Path) -> None:
    """mark_clean_run_complete does NOT clear a halted state (only clear() can do that)."""
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    state = store.mark_clean_run_complete()
    assert state.is_halted


def test_halt_during_recovery_pending_sets_halted(tmp_path: Path) -> None:
    """A halt decision during recovery_pending must trigger HALT (safety takes priority)."""
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())          # initial halt
    store.clear(cleared_by="op", note="safe", require_verification=True)  # -> recovery_pending
    assert store.load().status == "recovery_pending"

    # New halt comes in (e.g. new mismatch detected)
    state = store.apply_decision(_halt_decision())
    assert state.is_halted, "halt during recovery_pending must re-halt the breaker"


def test_degraded_during_recovery_pending_sets_degraded(tmp_path: Path) -> None:
    """A non-halt, non-allow guardrail decision during recovery_pending sets degraded."""
    from stock_swing.guardrails.rule_engine import GuardAction, GuardDecision, TriggeredRule
    store = CircuitBreakerStore(tmp_path / "cb.json")
    store.apply_decision(_halt_decision())
    store.clear(cleared_by="op", note="safe", require_verification=True)
    assert store.load().status == "recovery_pending"

    degraded_decision = GuardDecision(
        action=GuardAction.block_buys,
        triggered=[
            TriggeredRule(
                name="loss", metric="daily_loss_pct", observed=-3.0,
                operator="<=", threshold=-2.0, action=GuardAction.block_buys, severity="high",
            )
        ],
    )
    state = store.apply_decision(degraded_decision)
    assert state.status == "degraded", (
        "guardrail degraded action during recovery_pending should override to degraded"
    )


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
