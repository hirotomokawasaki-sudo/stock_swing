from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BREAKOUT_V2_INFERRED_AT = datetime.fromisoformat("2026-04-28T23:25:00+09:00")
BREAKOUT_V2_THRESHOLD_TUNED_AT = datetime.fromisoformat("2026-05-01T00:00:00+09:00")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def filename_dt(path: str | Path | None) -> datetime | None:
    if not path:
        return None
    try:
        stem = Path(path).stem
        parts = stem.split("_")
        if len(parts) < 3:
            return None
        raw = f"{parts[-2]}{parts[-1]}"
        dt = datetime.strptime(raw, "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def extract_decision_dt(decision: dict[str, Any], path: str | Path | None = None) -> datetime | None:
    return (
        parse_dt(decision.get("generated_at"))
        or parse_dt(decision.get("created_at"))
        or parse_dt(decision.get("decision_time"))
        or filename_dt(path)
    )


def normalize_strategy_id(strategy_id: str | None, occurred_at: datetime | str | None = None) -> str:
    strategy = str(strategy_id or "unknown")
    if not strategy.startswith("breakout_momentum"):
        return strategy

    if isinstance(occurred_at, str):
        occurred = parse_dt(occurred_at)
    else:
        occurred = occurred_at

    if occurred is None:
        occurred = datetime.now(timezone.utc)

    if occurred >= BREAKOUT_V2_THRESHOLD_TUNED_AT.astimezone(occurred.tzinfo or timezone.utc):
        return "breakout_momentum_v2_threshold_tuned"
    if occurred >= BREAKOUT_V2_INFERRED_AT.astimezone(occurred.tzinfo or timezone.utc):
        return "breakout_momentum_v2_inferred"
    return "breakout_momentum_v1_explicit"



def resolve_strategy_version_id(
    strategy_id: str | None,
    occurred_at: datetime | str | None = None,
    explicit_version_id: str | None = None,
) -> str:
    explicit = str(explicit_version_id or "").strip()
    if explicit:
        return explicit
    return normalize_strategy_id(strategy_id, occurred_at)



def resolve_strategy_key(
    payload: dict[str, Any],
    occurred_at: datetime | str | None = None,
    path: str | Path | None = None,
) -> str:
    inferred_at = occurred_at or extract_decision_dt(payload, path)
    return resolve_strategy_version_id(
        payload.get("strategy_id"),
        inferred_at,
        payload.get("strategy_version_id"),
    )
