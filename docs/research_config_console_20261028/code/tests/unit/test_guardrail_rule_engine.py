from stock_swing.guardrails import GuardAction, GuardrailEngine, GuardrailRule
from stock_swing.guardrails.rule_engine import load_rules_from_dict


def test_guardrail_engine_returns_most_severe_action() -> None:
    engine = GuardrailEngine(
        [
            GuardrailRule("loss", "daily_loss", "<=", -2, GuardAction.block_buys),
            GuardrailRule("mismatch", "mismatch_count", ">=", 1, GuardAction.halt),
        ]
    )
    decision = engine.evaluate({"daily_loss": -5, "mismatch_count": 1})
    assert decision.action == GuardAction.halt
    assert decision.requires_halt


def test_guardrail_engine_allows_when_no_rules_trigger() -> None:
    engine = GuardrailEngine([GuardrailRule("loss", "daily_loss", "<=", -2, GuardAction.block_buys)])
    decision = engine.evaluate({"daily_loss": -0.1})
    assert decision.action == GuardAction.allow
    assert decision.allows_new_buys


def test_guardrail_engine_missing_metric_does_not_halt() -> None:
    engine = GuardrailEngine([GuardrailRule("loss", "daily_loss", "<=", -2, GuardAction.halt)])
    decision = engine.evaluate({})
    assert decision.action == GuardAction.allow


def test_guardrail_engine_ai_pause_blocks_ai_not_buys() -> None:
    engine = GuardrailEngine([GuardrailRule("api", "api_error_rate_pct", ">=", 20, GuardAction.ai_pause)])
    decision = engine.evaluate({"api_error_rate_pct": 25})
    assert not decision.allows_ai_calls
    assert decision.allows_new_buys


def test_load_rules_from_dict() -> None:
    payload = {
        "rules": {
            "test_rule": {
                "metric": "daily_loss",
                "operator": "<=",
                "threshold": -2.0,
                "action": "block_buys",
                "severity": "high",
            }
        }
    }
    rules = load_rules_from_dict(payload)
    assert len(rules) == 1
    assert rules[0].name == "test_rule"
    assert rules[0].action == GuardAction.block_buys
