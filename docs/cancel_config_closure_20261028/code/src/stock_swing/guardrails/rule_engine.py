from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable


class GuardAction(IntEnum):
    allow = 0
    reduce_size = 1
    block_buys = 2
    ai_pause = 3
    flatten_risky = 4
    halt = 5


@dataclass(frozen=True)
class GuardrailRule:
    name: str
    metric: str
    operator: str
    threshold: float
    action: GuardAction
    severity: str = "medium"
    enabled: bool = True


@dataclass(frozen=True)
class TriggeredRule:
    name: str
    metric: str
    observed: float
    operator: str
    threshold: float
    action: GuardAction
    severity: str


@dataclass(frozen=True)
class GuardDecision:
    action: GuardAction
    triggered: list[TriggeredRule] = field(default_factory=list)

    @property
    def allows_new_buys(self) -> bool:
        return self.action not in (
            GuardAction.block_buys,
            GuardAction.flatten_risky,
            GuardAction.halt,
        )

    @property
    def allows_ai_calls(self) -> bool:
        return self.action != GuardAction.ai_pause and self.action != GuardAction.halt

    @property
    def requires_halt(self) -> bool:
        return self.action == GuardAction.halt


class GuardrailEngine:
    _OPS: dict[str, Callable[[float, float], bool]] = {
        ">": lambda observed, threshold: observed > threshold,
        ">=": lambda observed, threshold: observed >= threshold,
        "<": lambda observed, threshold: observed < threshold,
        "<=": lambda observed, threshold: observed <= threshold,
        "==": lambda observed, threshold: observed == threshold,
    }

    def __init__(self, rules: list[GuardrailRule], warning_only: bool = False) -> None:
        self.rules = [rule for rule in rules if rule.enabled]
        self.warning_only = warning_only

    def evaluate(self, metrics: dict[str, Any]) -> GuardDecision:
        triggered: list[TriggeredRule] = []

        for rule in self.rules:
            if rule.metric not in metrics:
                continue
            try:
                observed = float(metrics[rule.metric])
            except (TypeError, ValueError):
                continue

            op = self._OPS.get(rule.operator)
            if op is None:
                raise ValueError(f"unsupported operator: {rule.operator}")

            if op(observed, rule.threshold):
                triggered.append(
                    TriggeredRule(
                        name=rule.name,
                        metric=rule.metric,
                        observed=observed,
                        operator=rule.operator,
                        threshold=rule.threshold,
                        action=rule.action,
                        severity=rule.severity,
                    )
                )

        action = max((item.action for item in triggered), default=GuardAction.allow)

        if self.warning_only and triggered:
            import logging as _logging

            _wl = _logging.getLogger(__name__)
            for t in triggered:
                _wl.warning(
                    "guardrail_warning_only rule=%s metric=%s observed=%s %s threshold=%s action=%s",
                    t.name,
                    t.metric,
                    t.observed,
                    t.operator,
                    t.threshold,
                    t.action.name,
                )
            return GuardDecision(action=GuardAction.allow, triggered=triggered)

        return GuardDecision(action=action, triggered=triggered)


def load_rules_from_dict(payload: dict[str, Any]) -> list[GuardrailRule]:
    rules: list[GuardrailRule] = []
    for name, raw in (payload.get("rules") or {}).items():
        rules.append(
            GuardrailRule(
                name=name,
                metric=str(raw["metric"]),
                operator=str(raw["operator"]),
                threshold=float(raw["threshold"]),
                action=GuardAction[str(raw["action"])],
                severity=str(raw.get("severity", "medium")),
                enabled=bool(raw.get("enabled", True)),
            )
        )
    return rules
