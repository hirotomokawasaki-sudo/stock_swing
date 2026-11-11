"""Append-only trade event store (P3-D)."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from .ledger_transaction import ledger_operation, read_bytes, stage_bytes


@dataclass(frozen=True)
class TradeEvent:
    event_id: str
    event_type: str
    created_at: str
    symbol: str | None = None
    trade_id: str | None = None
    broker_order_id: str | None = None
    run_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        event_type: str,
        *,
        symbol: str | None = None,
        trade_id: str | None = None,
        broker_order_id: str | None = None,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> "TradeEvent":
        return cls(
            event_id=(str(uuid.uuid5(uuid.NAMESPACE_URL, "stock_swing:event:v2:" + idempotency_key))
                      if idempotency_key else str(uuid.uuid4())),
            event_type=event_type,
            created_at=datetime.now(timezone.utc).isoformat(),
            symbol=symbol,
            trade_id=trade_id,
            broker_order_id=broker_order_id,
            run_id=run_id,
            payload=payload or {},
        )


class TradeEventStore:
    """Append-only JSONL event store. Never mutates prior events."""

    def __init__(
        self,
        project_root: Path,
        rel_path: str = "data/tracking/trade_events.jsonl",
    ) -> None:
        self.project_root = project_root
        self.path = project_root / rel_path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: TradeEvent) -> None:
        if self.path != self.project_root / "data/tracking/trade_events.jsonl":
            # Submission/cancellation intents and config receipts are independent
            # durable journals, not members of the four-file financial epoch.
            # In particular a prepared intent must survive a financial rollback.
            line = json.dumps(asdict(event), ensure_ascii=False, sort_keys=True, allow_nan=False)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return
        self._append_financial(event)

    @ledger_operation()
    def _append_financial(self, event: TradeEvent) -> None:
        """Stage identity-checked append in the shared recoverable transaction."""
        record = asdict(event)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
        economic = {k: v for k, v in record.items() if k not in {"created_at", "run_id"}}
        before = read_bytes(self.project_root, self.path) or b""
        from .history_migration import parse_events, validate_history_pair
        state_raw = read_bytes(self.project_root, self.project_root / "data/tracking/pnl_state.json")
        state = json.loads(state_raw) if state_raw else {}
        validate_history_pair(state, parse_events(before))
        seen = False
        for number, previous in enumerate(before.decode().splitlines(), 1):
            if not previous.strip():
                continue
            try:
                prior = asdict(TradeEvent(**json.loads(previous)))
                if not prior["event_id"] or not isinstance(prior["payload"], dict):
                    raise ValueError("invalid event shape")
            except (ValueError, TypeError) as exc:
                raise ValueError(f"corrupt trade event store at line {number}") from exc
            if prior["event_id"] == event.event_id:
                prior_economic = {k: v for k, v in prior.items() if k not in {"created_at", "run_id"}}
                if prior_economic != economic:
                    raise ValueError(f"conflicting trade event identity: {event.event_id}")
                seen = True
        if seen:
            return
        if before and not before.endswith(b"\n"):
            before += b"\n"
        after = before + (line + "\n").encode()
        validate_history_pair(state, parse_events(after))
        stage_bytes(self.project_root, self.path, after)

    def read_raw(self) -> list[TradeEvent]:
        """Audit view including superseded evidence; NEVER sum as active PnL."""
        if self.path != self.project_root / "data/tracking/trade_events.jsonl":
            from .history_migration import parse_events
            raw = self.path.read_bytes() if self.path.exists() else None
            return [TradeEvent(**e) for e in parse_events(raw)]
        return self._read_financial(raw=True)

    @ledger_operation()
    def _read_financial(self, *, raw=False) -> list[TradeEvent]:
        from .history_migration import parse_events
        if raw:
            return [TradeEvent(**e) for e in parse_events(read_bytes(self.project_root, self.path))]
        return self._read_active_financial()

    def read_all(self) -> list[TradeEvent]:
        """Economic view: explicit historical supersessions applied once."""
        if self.path != self.project_root / "data/tracking/trade_events.jsonl":
            return self.read_raw()
        return self._read_financial()

    def _read_active_financial(self) -> list[TradeEvent]:
        from .history_migration import parse_events, active_events, validate_history_pair
        events = parse_events(read_bytes(self.project_root, self.path))
        state_raw = read_bytes(self.project_root, self.project_root / "data/tracking/pnl_state.json")
        validate_history_pair(json.loads(state_raw) if state_raw else {}, events)
        return [TradeEvent(**e) for e in active_events(events)]
