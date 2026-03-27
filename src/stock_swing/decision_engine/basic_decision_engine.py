from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from stock_swing.core.types import DecisionRecord
from stock_swing.decision_engine.interfaces import DecisionEngine


class BasicDecisionEngine(DecisionEngine):
    def decide(self, signal: dict, risk_result: dict, mode: str) -> DecisionRecord:
        symbol = (signal.get("candidate_symbols") or ["SPY"])[0]
        deny_reasons = risk_result.get("deny_reasons", [])
        action = "deny" if deny_reasons else "review"
        now = datetime.now(timezone.utc)
        digest = hashlib.sha256(f"{symbol}|{mode}|{now.isoformat()}".encode()).hexdigest()[:16]
        return DecisionRecord(
            decision_id=digest,
            schema_version="v1",
            generated_at=now,
            mode=mode,
            strategy_id=signal.get("strategy_id", "unknown"),
            symbol=symbol,
            action=action,
            confidence=float(signal.get("signal_strength", 0.0)),
            signal_strength=float(signal.get("signal_strength", 0.0)),
            risk_state=risk_result.get("risk_state", "review"),
            deny_reasons=deny_reasons,
            requires_operator_approval=(mode == "live_guarded"),
            time_horizon="1d",
            evidence={"feature_refs": [], "raw_refs": [], "notes": signal.get("notes", [])},
            proposed_order=None if action == "deny" else {"symbol": symbol, "side": "buy", "order_type": "market", "qty": 1, "time_in_force": "day"},
        )
