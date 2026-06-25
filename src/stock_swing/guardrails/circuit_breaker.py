from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_swing.guardrails.rule_engine import GuardAction, GuardDecision


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CircuitBreakerState:
    status: str = "ok"
    action: str = "allow"
    triggered_at: str | None = None
    cleared_at: str | None = None
    reason: str = ""
    triggered_rules: list[dict[str, Any]] = field(default_factory=list)
    cleared_by: str | None = None
    clear_note: str | None = None

    @property
    def is_halted(self) -> bool:
        return self.status == "halted"


class CircuitBreakerStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> CircuitBreakerState:
        if not self.path.exists():
            return CircuitBreakerState()
        return CircuitBreakerState(**json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, state: CircuitBreakerState) -> None:
        payload = asdict(state)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(payload, fh, ensure_ascii=False, sort_keys=True, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def apply_decision(self, decision: GuardDecision) -> CircuitBreakerState:
        current = self.load()
        if current.is_halted:
            return current

        if decision.action == GuardAction.halt:
            state = CircuitBreakerState(
                status="halted",
                action=decision.action.name,
                triggered_at=_now(),
                reason="guardrail_halt",
                triggered_rules=[asdict(item) for item in decision.triggered],
            )
            self.save(state)
            return state

        if decision.action != GuardAction.allow:
            state = CircuitBreakerState(
                status="degraded",
                action=decision.action.name,
                triggered_at=_now(),
                reason="guardrail_degraded",
                triggered_rules=[asdict(item) for item in decision.triggered],
            )
            self.save(state)
            return state

        if current.status != "ok":
            state = CircuitBreakerState(status="ok", action="allow", cleared_at=_now(), reason="metrics_normalized")
            self.save(state)
            return state

        return current

    def clear(self, *, cleared_by: str, note: str) -> CircuitBreakerState:
        state = CircuitBreakerState(
            status="ok",
            action="allow",
            cleared_at=_now(),
            reason="manual_clear",
            cleared_by=cleared_by,
            clear_note=note,
        )
        self.save(state)
        return state
