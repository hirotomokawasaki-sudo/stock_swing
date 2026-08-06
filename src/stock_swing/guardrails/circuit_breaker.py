from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
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
    # Heartbeat timestamp: stamped on every apply_decision() call (whether or
    # not the status changes) so freshness checks (console self-check) can
    # tell "guardrail is actively being evaluated" apart from "guardrail
    # last changed state N days ago". Without this, a long-running healthy
    # ('ok', no halts) period looks indistinguishable from a stale/dead
    # guardrail loop, since the file was previously only rewritten on state
    # transitions (see 2026-08-07 self-check false-positive investigation).
    last_evaluated_at: str | None = None

    @property
    def is_halted(self) -> bool:
        return self.status == "halted"

    @property
    def is_recovery_pending(self) -> bool:
        """True when manual clear was issued but a clean scheduled run is still required."""
        return self.status == "recovery_pending"


class CircuitBreakerStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> CircuitBreakerState:
        if not self.path.exists():
            return CircuitBreakerState()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        # Strip unknown keys (e.g. operator notes added by clear_circuit_breaker.py)
        known = {f.name for f in dataclasses.fields(CircuitBreakerState)}
        return CircuitBreakerState(**{k: v for k, v in data.items() if k in known})

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
        now = _now()
        if current.is_halted:
            stamped = replace(current, last_evaluated_at=now)
            self.save(stamped)
            return stamped

        if decision.action == GuardAction.halt:
            state = CircuitBreakerState(
                status="halted",
                action=decision.action.name,
                triggered_at=now,
                reason="guardrail_halt",
                triggered_rules=[asdict(item) for item in decision.triggered],
                last_evaluated_at=now,
            )
            self.save(state)
            return state

        if decision.action != GuardAction.allow:
            state = CircuitBreakerState(
                status="degraded",
                action=decision.action.name,
                triggered_at=now,
                reason="guardrail_degraded",
                triggered_rules=[asdict(item) for item in decision.triggered],
                last_evaluated_at=now,
            )
            self.save(state)
            return state

        # R0-v2-A: recovery_pending can only exit via mark_clean_run_complete().
        # Do NOT auto-clear to ok here; a verified clean scheduled run is required.
        if current.is_recovery_pending:
            stamped = replace(current, last_evaluated_at=now)
            self.save(stamped)
            return stamped

        if current.status != "ok":
            state = CircuitBreakerState(
                status="ok", action="allow", cleared_at=now, reason="metrics_normalized", last_evaluated_at=now
            )
            self.save(state)
            return state

        # Status stays 'ok' and unchanged: still heartbeat-stamp so freshness
        # checks can distinguish "actively evaluated, healthy" from "stale".
        stamped = replace(current, last_evaluated_at=now)
        self.save(stamped)
        return stamped

    def clear(
        self,
        *,
        cleared_by: str,
        note: str,
        require_verification: bool = False,
    ) -> CircuitBreakerState:
        """Manually clear a HALT.

        Args:
            cleared_by: Username or identifier of the operator.
            note: Explanation of why the reset is safe (min 12 chars enforced by caller).
            require_verification: If True, transition to ``recovery_pending`` instead of
                ``ok``.  The breaker returns to ``ok`` only after a clean scheduled run
                completes (via :meth:`mark_clean_run_complete`).  Pass ``False`` only for
                emergency overrides (``--force-ok``); the override is recorded in the state.
        """
        status = "recovery_pending" if require_verification else "ok"
        reason = "manual_clear" if require_verification else "manual_clear_force_ok"
        now = _now()
        state = CircuitBreakerState(
            status=status,
            action="allow",
            cleared_at=now,
            reason=reason,
            cleared_by=cleared_by,
            clear_note=note,
            last_evaluated_at=now,
        )
        self.save(state)
        return state

    def mark_clean_run_complete(self) -> CircuitBreakerState:
        """Transition ``recovery_pending`` → ``ok`` after a verified clean scheduled run.

        Called by paper_demo when post-run broker/tracker mismatch=0 and the circuit
        breaker is in ``recovery_pending``.  If status is not ``recovery_pending`` this
        is a no-op and returns the current state unchanged.
        """
        current = self.load()
        if not current.is_recovery_pending:
            return current
        now = _now()
        state = CircuitBreakerState(
            status="ok",
            action="allow",
            cleared_at=now,
            reason="clean_run_verified",
            last_evaluated_at=now,
        )
        self.save(state)
        return state
