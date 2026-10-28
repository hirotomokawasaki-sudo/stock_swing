from pathlib import Path

from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore
from stock_swing.guardrails.pre_trade_check import apply_to_buy_candidate, check_startup, should_skip_ai
from stock_swing.guardrails.rule_engine import GuardAction, GuardDecision, TriggeredRule


def _halt_state(tmp_path: Path):
    store = CircuitBreakerStore(tmp_path / "cb.json")
    decision = GuardDecision(
        action=GuardAction.halt,
        triggered=[
            TriggeredRule("r", "m", 1, ">=", 1, GuardAction.halt, "critical")
        ],
    )
    store.apply_decision(decision)
    return store.load()


def _ok_state(tmp_path: Path):
    store = CircuitBreakerStore(tmp_path / "cb.json")
    return store.load()


def test_check_startup_halted(tmp_path: Path) -> None:
    store = CircuitBreakerStore(tmp_path / "cb.json")
    decision = GuardDecision(
        action=GuardAction.halt,
        triggered=[TriggeredRule("r", "m", 1, ">=", 1, GuardAction.halt, "critical")],
    )
    store.apply_decision(decision)
    state = check_startup(store)
    assert state.is_halted


def test_should_skip_ai_when_halted(tmp_path: Path) -> None:
    state = _halt_state(tmp_path)
    allow = GuardDecision(action=GuardAction.allow, triggered=[])
    assert should_skip_ai(state, allow) is True


def test_should_skip_ai_when_ai_pause(tmp_path: Path) -> None:
    state = _ok_state(tmp_path)
    decision = GuardDecision(action=GuardAction.ai_pause, triggered=[])
    assert should_skip_ai(state, decision) is True


def test_apply_to_buy_candidate_blocks_when_halted(tmp_path: Path) -> None:
    state = _halt_state(tmp_path)
    allow = GuardDecision(action=GuardAction.allow, triggered=[])
    candidate = {"symbol": "KLAC", "action": "buy"}
    result = apply_to_buy_candidate(candidate, allow, state)
    assert result["action"] == "deny"
    assert result["deny_reason"] == "guardrail_halt"


def test_apply_to_buy_candidate_blocks_when_block_buys(tmp_path: Path) -> None:
    state = _ok_state(tmp_path)
    decision = GuardDecision(
        action=GuardAction.block_buys,
        triggered=[TriggeredRule("loss", "daily_loss", -3, "<=", -2, GuardAction.block_buys, "high")],
    )
    candidate = {"symbol": "MRVL", "action": "buy"}
    result = apply_to_buy_candidate(candidate, decision, state)
    assert result["action"] == "deny"


def test_apply_to_buy_candidate_reduces_size(tmp_path: Path) -> None:
    state = _ok_state(tmp_path)
    decision = GuardDecision(
        action=GuardAction.reduce_size,
        triggered=[TriggeredRule("cons", "consecutive_losing", 5, ">=", 5, GuardAction.reduce_size, "medium")],
    )
    candidate = {"symbol": "PLTR", "action": "buy", "size_multiplier": 1.0}
    result = apply_to_buy_candidate(candidate, decision, state)
    assert result["size_multiplier"] == 0.5
    assert result["action"] == "buy"
