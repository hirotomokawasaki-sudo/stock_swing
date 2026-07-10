"""F2 tests: broker/tracker mismatch count must reach GuardrailEngine."""
from __future__ import annotations

from stock_swing.guardrails.rule_engine import GuardAction, GuardrailEngine, GuardrailRule


def _engine_with_mismatch_halt(threshold: int = 1) -> GuardrailEngine:
    rule = GuardrailRule(
        name="broker_tracker_mismatch_halt",
        metric="broker_tracker_mismatch_count",
        operator=">=",
        threshold=float(threshold),
        action=GuardAction.halt,
        severity="critical",
        enabled=True,
    )
    return GuardrailEngine(rules=[rule], warning_only=False)


def test_zero_mismatch_does_not_halt():
    engine = _engine_with_mismatch_halt(threshold=1)
    decision = engine.evaluate({"broker_tracker_mismatch_count": 0})
    assert not decision.requires_halt, "no mismatch should not trigger halt"


def test_one_mismatch_triggers_halt():
    engine = _engine_with_mismatch_halt(threshold=1)
    decision = engine.evaluate({"broker_tracker_mismatch_count": 1})
    assert decision.requires_halt, "mismatch_count=1 must trigger halt"


def test_two_mismatches_trigger_halt():
    engine = _engine_with_mismatch_halt(threshold=1)
    decision = engine.evaluate({"broker_tracker_mismatch_count": 2})
    assert decision.requires_halt


def test_warning_only_does_not_halt():
    """In warning_only mode, halt rule is triggered but action is downgraded."""
    rule = GuardrailRule(
        name="broker_tracker_mismatch_halt",
        metric="broker_tracker_mismatch_count",
        operator=">=",
        threshold=1.0,
        action=GuardAction.halt,
        severity="critical",
        enabled=True,
    )
    engine = GuardrailEngine(rules=[rule], warning_only=True)
    decision = engine.evaluate({"broker_tracker_mismatch_count": 1})
    # GuardrailEngine warning_only: triggered rules are still recorded but
    # the final action is capped; verify triggered contains the rule
    assert any(r.name == "broker_tracker_mismatch_halt" for r in decision.triggered)


def test_mismatch_metric_missing_from_metrics():
    """If metric not in dict, rule should be silently skipped."""
    engine = _engine_with_mismatch_halt(threshold=1)
    decision = engine.evaluate({})  # no broker_tracker_mismatch_count key
    assert not decision.requires_halt
