"""Shadow diagnostic for adding to an already losing position."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class LosingPositionAddGuardConfig:
    mode: str = "shadow"
    max_existing_loss_pct: float = -0.03

    @classmethod
    def from_env(cls) -> "LosingPositionAddGuardConfig":
        mode = os.environ.get("LOSING_POSITION_ADD_GUARD_MODE", "shadow").lower()
        try:
            threshold = float(
                os.environ.get("LOSING_POSITION_ADD_GUARD_MAX_LOSS_PCT", -0.03)
            )
        except (TypeError, ValueError):
            threshold = -0.03
        if not math.isfinite(threshold) or threshold >= 0:
            threshold = -0.03
        return cls(mode=mode, max_existing_loss_pct=threshold)

    def is_enabled(self) -> bool:
        return self.mode == "shadow"


@dataclass(frozen=True)
class LosingPositionAddObservation:
    symbol: str
    decision_id: str | None
    existing_qty: int
    existing_return_pct: float | None
    threshold_pct: float
    would_block: bool
    data_valid: bool
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def evaluate_losing_position_adds(
    decisions: Iterable[Any],
    current_positions: dict[str, dict[str, Any]],
    *,
    config: LosingPositionAddGuardConfig,
) -> list[LosingPositionAddObservation]:
    """Evaluate only BUY decisions that would add to an existing position."""
    observations: list[LosingPositionAddObservation] = []
    for decision in decisions:
        if str(getattr(decision, "action", "") or "").lower() != "buy":
            continue
        symbol = str(getattr(decision, "symbol", "") or "").upper()
        position = current_positions.get(symbol)
        if not position:
            continue
        try:
            existing_qty = int(float(position.get("qty", 0) or 0))
        except (TypeError, ValueError):
            existing_qty = 0
        if existing_qty <= 0:
            continue

        existing_return = _finite_float(position.get("unrealized_plpc"))
        if existing_return is None:
            would_block = True
            data_valid = False
            reason = "missing_existing_position_return_fail_closed"
        else:
            would_block = existing_return <= config.max_existing_loss_pct
            data_valid = True
            reason = (
                "existing_position_loss_exceeds_add_threshold"
                if would_block
                else "existing_position_above_add_threshold"
            )
        observations.append(
            LosingPositionAddObservation(
                symbol=symbol,
                decision_id=getattr(decision, "decision_id", None),
                existing_qty=existing_qty,
                existing_return_pct=existing_return,
                threshold_pct=config.max_existing_loss_pct,
                would_block=would_block,
                data_valid=data_valid,
                reason=reason,
            )
        )
    return observations


def log_losing_position_add_shadow(
    observation: LosingPositionAddObservation,
    *,
    shadow_log_path: Path,
    run_id: str | None = None,
) -> None:
    """Append one evaluation. Callers must suppress writes in dry-run mode."""
    shadow_log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "mode": "shadow",
        "run_id": run_id,
        **observation.to_dict(),
    }
    with shadow_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
