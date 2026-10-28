"""Pre-trade and post-run guardrail integration helpers (P9-C)."""
from __future__ import annotations

import logging
from typing import Any

from stock_swing.guardrails.circuit_breaker import CircuitBreakerState, CircuitBreakerStore
from stock_swing.guardrails.rule_engine import GuardAction, GuardDecision

logger = logging.getLogger(__name__)


def check_startup(breaker_store: CircuitBreakerStore) -> CircuitBreakerState:
    """Load breaker state at run startup. Callers should abort buy/submit flow if is_halted."""
    state = breaker_store.load()
    if state.is_halted:
        logger.warning(
            "guardrail_startup_halted status=halted action=%s reason=%s",
            state.action,
            state.reason,
        )
    return state


def should_skip_ai(breaker_state: CircuitBreakerState, guard_decision: GuardDecision) -> bool:
    """Return True if AI calls should be skipped."""
    if breaker_state.is_halted:
        logger.warning("guardrail_ai_skipped reason=breaker_halted")
        return True
    if not guard_decision.allows_ai_calls:
        logger.warning(
            "guardrail_ai_skipped reason=%s triggered_rules=%s",
            guard_decision.action.name,
            [r.name for r in guard_decision.triggered],
        )
        return True
    return False


def apply_to_buy_candidate(
    candidate: dict[str, Any],
    guard_decision: GuardDecision,
    breaker_state: CircuitBreakerState,
) -> dict[str, Any]:
    """Apply guardrail action to a buy candidate dict. Returns updated candidate."""
    candidate = dict(candidate)

    if breaker_state.is_halted:
        candidate["action"] = "deny"
        candidate["deny_reason"] = "guardrail_halt"
        candidate["guardrail_action"] = "halt"
        logger.warning("guardrail_buy_denied symbol=%s reason=guardrail_halt", candidate.get("symbol"))
        return candidate

    if guard_decision.requires_halt:
        candidate["action"] = "deny"
        candidate["deny_reason"] = "guardrail_halt"
        candidate["guardrail_action"] = "halt"
        candidate["triggered_rules"] = [r.name for r in guard_decision.triggered]
        return candidate

    if not guard_decision.allows_new_buys and candidate.get("action") == "buy":
        candidate["action"] = "deny"
        candidate["deny_reason"] = f"guardrail_{guard_decision.action.name}"
        candidate["guardrail_action"] = guard_decision.action.name
        candidate["triggered_rules"] = [r.name for r in guard_decision.triggered]
        logger.warning(
            "guardrail_buy_blocked symbol=%s guardrail_action=%s",
            candidate.get("symbol"),
            guard_decision.action.name,
        )
        return candidate

    if guard_decision.action == GuardAction.reduce_size and candidate.get("action") == "buy":
        current_multiplier = float(candidate.get("size_multiplier", 1.0))
        candidate["size_multiplier"] = min(current_multiplier, 0.5)
        candidate["guardrail_action"] = "reduce_size"
        candidate["triggered_rules"] = [r.name for r in guard_decision.triggered]
        logger.info(
            "guardrail_size_reduced symbol=%s multiplier=%.2f",
            candidate.get("symbol"),
            candidate["size_multiplier"],
        )

    return candidate


def post_run_update(
    metrics: dict[str, Any],
    guard_engine: Any,
    breaker_store: CircuitBreakerStore,
) -> CircuitBreakerState:
    """Evaluate metrics after run and persist breaker state."""
    decision = guard_engine.evaluate(metrics)
    state = breaker_store.apply_decision(decision)
    if state.is_halted:
        logger.error(
            "guardrail_post_run_halt action=%s triggered_rules=%s",
            state.action,
            [r.get("name") for r in state.triggered_rules],
        )
    elif state.status == "degraded":
        logger.warning("guardrail_post_run_degraded action=%s", state.action)
    return state
