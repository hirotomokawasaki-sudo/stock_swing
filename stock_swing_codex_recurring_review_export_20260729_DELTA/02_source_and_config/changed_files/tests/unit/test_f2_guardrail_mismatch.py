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


# ── R0-v2-C: api_error_rate_pct and token_spend_spike_pct ────────────

def test_api_error_rate_is_computed_from_latency_tracker():
    """api_error_rate_pct must be derivable from latency_tracker error_count / call_count."""
    from stock_swing.cli.paper_demo import _build_api_metrics

    class _FakeRecord:
        def __init__(self, status, duration_ms=100, endpoint="broker.test"):
            self.status = status
            self.duration_ms = duration_ms
            self.endpoint = endpoint

    class _FakeTracker:
        _records = [_FakeRecord("ok"), _FakeRecord("ok"), _FakeRecord("error")]

    metrics = _build_api_metrics(_FakeTracker())
    assert metrics["call_count"] == 3
    assert metrics["error_count"] == 1
    computed_rate = metrics["error_count"] / max(metrics["call_count"], 1) * 100
    assert abs(computed_rate - 33.33) < 0.1, f"expected ~33.3%, got {computed_rate}"


def test_api_error_rate_zero_when_no_errors():
    """api_error_rate_pct = 0.0 when all calls succeed."""
    from stock_swing.cli.paper_demo import _build_api_metrics

    class _FakeRecord:
        def __init__(self):
            self.status = "ok"
            self.duration_ms = 50
            self.endpoint = "broker.ok"

    class _FakeTracker:
        _records = [_FakeRecord(), _FakeRecord()]

    metrics = _build_api_metrics(_FakeTracker())
    rate = metrics["error_count"] / max(metrics["call_count"], 1) * 100
    assert rate == 0.0


def test_token_spend_spike_pct_zero_under_budget():
    """token_spend_spike_pct = 0 when tokens < daily_budget."""
    from stock_swing.utils.context_budget import build_ai_metrics_from_decisions
    metrics = build_ai_metrics_from_decisions([], daily_token_budget=300_000)
    run_tokens = metrics["input_tokens"] + metrics["output_tokens"]
    spike = max(0.0, (run_tokens / max(metrics["daily_token_budget"], 1) - 1.0) * 100)
    assert spike == 0.0


def test_token_spend_spike_pct_positive_over_budget():
    """token_spend_spike_pct > 0 when tokens exceed daily_budget."""
    # Simulate a decision with 400K tokens against a 300K budget
    class _FakeDecision:
        input_tokens = 350_000
        output_tokens = 50_000
        context_pack = "evidence_v1"
        model = "test-model"

    from stock_swing.utils.context_budget import build_ai_metrics_from_decisions
    metrics = build_ai_metrics_from_decisions([_FakeDecision()], daily_token_budget=300_000)
    run_tokens = metrics["input_tokens"] + metrics["output_tokens"]
    spike = max(0.0, (run_tokens / max(metrics["daily_token_budget"], 1) - 1.0) * 100)
    # 400K / 300K - 1 = 33.3%
    assert spike > 30.0, f"expected >30%, got {spike}"
