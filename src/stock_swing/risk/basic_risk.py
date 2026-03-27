from __future__ import annotations

from stock_swing.risk.interfaces import RiskEngine


class BasicRiskEngine(RiskEngine):
    def evaluate(self, signal: dict, mode: str) -> dict:
        deny_reasons: list[str] = []
        if mode not in {"research", "paper", "live_guarded", "live"}:
            deny_reasons.append("invalid_runtime_mode")
        return {
            "risk_state": "deny" if deny_reasons else "pass",
            "deny_reasons": deny_reasons,
        }
