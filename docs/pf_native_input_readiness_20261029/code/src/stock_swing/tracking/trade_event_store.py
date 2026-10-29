"""Append-only trade event store (P3-D)."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    ) -> "TradeEvent":
        return cls(
            event_id=str(uuid.uuid4()),
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
        self.path = project_root / rel_path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: TradeEvent) -> None:
        line = json.dumps(asdict(event), ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())

    def read_all(self) -> list[TradeEvent]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    events.append(TradeEvent(**json.loads(line)))
                except Exception:
                    pass
        return events
