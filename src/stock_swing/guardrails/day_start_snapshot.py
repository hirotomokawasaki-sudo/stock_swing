"""Day-start equity / unrealized baseline for guardrail daily-loss calculation.

FIX-GUARDRAIL-2: Replaces the implicit prev_unrealized_pnl=0 fallback with an
explicit day-start snapshot written once per trading day.

File format (data/guardrails/day_start_snapshot.json):
    {
        "market_date":          "YYYY-MM-DD",
        "captured_at":          "<ISO-8601 UTC>",
        "source":               "broker_api" | "tracker_estimate" | "unknown",
        "day_start_equity":     <float | null>,
        "day_start_unrealized": <float | null>,
        "missing_fields":       ["day_start_equity", ...]  # empty if all present
    }

Usage in paper_demo.py (pre-run):
    from stock_swing.guardrails.day_start_snapshot import (
        load_or_capture_day_start, DayStartMissingError
    )
    try:
        snapshot = load_or_capture_day_start(broker=broker, tracker=tracker)
        prev_unrealized = snapshot.day_start_unrealized
    except DayStartMissingError as exc:
        # BUY must be halted — do not fall back to 0
        raise

Safety rules:
- If the stored snapshot is from a previous trading day, it is stale and must
  not be used as today's baseline.  The caller receives an error and MUST halt
  new BUY orders.
- 0-fallback is NEVER performed automatically.  Missing values are surfaced to
  the caller as missing_metrics.
- All mutations are atomic (write-to-tmp then rename).
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

_SNAPSHOT_RELATIVE = Path("data/guardrails/day_start_snapshot.json")


class DayStartMissingError(RuntimeError):
    """Raised when day-start baseline is unavailable or stale.

    BUY orders MUST be halted until the snapshot is refreshed.
    """


@dataclass
class DayStartSnapshot:
    market_date: str
    captured_at: str
    source: str  # "broker_api" | "tracker_estimate" | "unknown"
    day_start_equity: Optional[float]
    day_start_unrealized: Optional[float]
    missing_fields: List[str] = field(default_factory=list)

    def is_valid_for_today(self) -> bool:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.market_date == today

    def to_dict(self) -> dict:
        return asdict(self)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_snapshot(project_root: Path) -> Optional[DayStartSnapshot]:
    """Load stored snapshot; return None if missing or corrupt."""
    path = project_root / _SNAPSHOT_RELATIVE
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return DayStartSnapshot(
            market_date=d.get("market_date", ""),
            captured_at=d.get("captured_at", ""),
            source=d.get("source", "unknown"),
            day_start_equity=d.get("day_start_equity"),
            day_start_unrealized=d.get("day_start_unrealized"),
            missing_fields=d.get("missing_fields", []),
        )
    except Exception:
        return None


def capture_snapshot(
    project_root: Path,
    *,
    equity: Optional[float],
    unrealized_pnl: Optional[float],
    source: str = "unknown",
) -> DayStartSnapshot:
    """Write a fresh day-start snapshot for today."""
    today = _today_utc()
    missing: List[str] = []
    if equity is None:
        missing.append("day_start_equity")
    if unrealized_pnl is None:
        missing.append("day_start_unrealized")

    snap = DayStartSnapshot(
        market_date=today,
        captured_at=datetime.now(timezone.utc).isoformat(),
        source=source,
        day_start_equity=equity,
        day_start_unrealized=unrealized_pnl,
        missing_fields=missing,
    )
    _write_atomic(project_root / _SNAPSHOT_RELATIVE, snap.to_dict())
    return snap


def load_or_capture_day_start(
    project_root: Path,
    *,
    equity: Optional[float] = None,
    unrealized_pnl: Optional[float] = None,
    source: str = "unknown",
    allow_missing: bool = False,
) -> DayStartSnapshot:
    """Load today's snapshot or capture a new one if today's is absent.

    Raises DayStartMissingError when required fields are missing AND
    allow_missing=False (the default — callers that block BUY should not pass
    allow_missing=True).

    Args:
        project_root: Repository root path.
        equity: Current broker equity to capture if no snapshot yet.
        unrealized_pnl: Current unrealized PnL to capture if no snapshot yet.
        source: Label for the capture source (e.g. "broker_api").
        allow_missing: If True, return the snapshot even when fields are None.
            Only use this in read-only reporting paths.
    """
    existing = load_snapshot(project_root)

    if existing and existing.is_valid_for_today():
        snap = existing
    else:
        # Stale or absent — write fresh snapshot with what we have.
        snap = capture_snapshot(
            project_root,
            equity=equity,
            unrealized_pnl=unrealized_pnl,
            source=source,
        )

    if not allow_missing and snap.missing_fields:
        raise DayStartMissingError(
            f"Day-start snapshot is missing required fields: {snap.missing_fields}. "
            "BUY orders must be halted until snapshot is refreshed."
        )

    return snap


def get_prev_unrealized_for_guardrail(
    project_root: Path,
    *,
    equity: Optional[float] = None,
    unrealized_pnl: Optional[float] = None,
    source: str = "unknown",
) -> tuple[float, list[str]]:
    """Return (prev_unrealized_pnl, missing_metrics) for guardrail calculation.

    Never returns 0 silently.  If the value is unknown, it is returned as None
    and 'day_start_unrealized' is added to missing_metrics.

    Returns:
        (prev_unrealized, missing_metrics) where prev_unrealized is the
        day-start unrealized PnL baseline, or None if unavailable.
    """
    try:
        snap = load_or_capture_day_start(
            project_root,
            equity=equity,
            unrealized_pnl=unrealized_pnl,
            source=source,
            allow_missing=True,  # caller handles missing
        )
    except Exception:
        return 0.0, ["day_start_unrealized", "day_start_equity"]

    missing: list[str] = list(snap.missing_fields)
    prev = snap.day_start_unrealized

    if prev is None:
        # Do not fall back to 0 — surface as missing metric
        if "day_start_unrealized" not in missing:
            missing.append("day_start_unrealized")
        return 0.0, missing  # 0 used only as a type-safe sentinel; caller checks missing

    return prev, missing
