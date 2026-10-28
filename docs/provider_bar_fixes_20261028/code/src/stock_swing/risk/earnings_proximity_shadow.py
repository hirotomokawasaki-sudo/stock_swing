"""Observe BUY candidates near earnings without changing trading behavior.

This diagnostic was added after the 2026-09-03 PATH/SNOW loss cluster.  It is
deliberately shadow-only: promotion governance requires prospective evidence
before an earnings-proximity rule may block or resize an order.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_swing.core.types import CanonicalRecord


@dataclass(frozen=True)
class EarningsProximityObservation:
    symbol: str
    strategy_id: str
    phase: str
    would_block: bool
    event_time: str | None
    event_hour: str | None
    relative_hours: float | None
    reason: str
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def classify_earnings_proximity(
    symbol: str,
    strategy_id: str,
    records: list[CanonicalRecord],
    *,
    observed_at: datetime | None = None,
    pre_event_days: int = 7,
    post_event_days: int = 2,
) -> EarningsProximityObservation:
    """Classify a BUY candidate against the nearest known earnings event.

    ``would_block`` is counterfactual only.  EventSwingStrategy is explicitly
    event-seeking and is therefore logged but never labelled as a block
    candidate; ordinary breakout entries are labelled inside either window.
    """
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    candidates = [
        record
        for record in records
        if record.symbol == symbol and record.event_type == "earnings_calendar"
    ]
    if not candidates:
        return EarningsProximityObservation(
            symbol=symbol,
            strategy_id=strategy_id,
            phase="no_event_data",
            would_block=False,
            event_time=None,
            event_hour=None,
            relative_hours=None,
            reason="no earnings record in retained calendar window",
            observed_at=now.astimezone(timezone.utc).isoformat(),
        )

    nearest = min(candidates, key=lambda record: abs((record.event_time - now).total_seconds()))
    delta = nearest.event_time - now
    relative_hours = round(delta.total_seconds() / 3600.0, 2)
    event_hour = nearest.payload.get("hour") if isinstance(nearest.payload, dict) else None

    if timedelta(0) <= delta <= timedelta(days=pre_event_days):
        phase = "pre_event"
    elif -timedelta(days=post_event_days) <= delta < timedelta(0):
        phase = "post_event"
    else:
        phase = "outside_window"

    intentional_event_strategy = strategy_id == "event_swing_v1"
    would_block = phase in {"pre_event", "post_event"} and not intentional_event_strategy
    if intentional_event_strategy and phase in {"pre_event", "post_event"}:
        reason = "intentional event strategy; observe separately"
    elif would_block:
        reason = f"ordinary entry inside {phase} earnings window"
    else:
        reason = "outside configured earnings-proximity window"

    return EarningsProximityObservation(
        symbol=symbol,
        strategy_id=strategy_id,
        phase=phase,
        would_block=would_block,
        event_time=nearest.event_time.astimezone(timezone.utc).isoformat(),
        event_hour=str(event_hour) if event_hour is not None else None,
        relative_hours=relative_hours,
        reason=reason,
        observed_at=now.astimezone(timezone.utc).isoformat(),
    )


def log_observation(observation: EarningsProximityObservation, log_path: Path) -> None:
    """Append one JSONL observation; callers keep dry-run writes disabled."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(observation), ensure_ascii=False) + "\n")
