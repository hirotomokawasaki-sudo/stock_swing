"""Run context with run_id and correlation_id (P3-C)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RunContext:
    run_id: str
    started_at: str
    command: str

    @classmethod
    def create(cls, command: str) -> "RunContext":
        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        return cls(
            run_id=f"{command}-{stamp}-{uuid.uuid4().hex[:8]}",
            started_at=now.isoformat(),
            command=command,
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "command": self.command,
        }


def attach_run_context(decisions: list, run_context: RunContext) -> None:
    """Attach run_id to all decision evidence dicts (in-place)."""
    for decision in decisions:
        evidence = getattr(decision, "evidence", None)
        if isinstance(evidence, dict):
            evidence.setdefault("run_id", run_context.run_id)
            evidence.setdefault("run_started_at", run_context.started_at)
