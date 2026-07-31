"""Day-start equity / unrealized baseline for fail-closed guardrails."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_SNAPSHOT_RELATIVE = Path("data/guardrails/day_start_snapshot.json")


class DayStartMissingError(RuntimeError):
    """Raised when day-start baseline is unavailable or stale."""


def current_market_date() -> str:
    """Return the current runtime date used by guardrail snapshots."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class DayStartSnapshot:
    market_date: str
    captured_at: str
    source: str
    day_start_equity: Optional[float]
    day_start_unrealized: Optional[float]
    missing_fields: list[str] = field(default_factory=list)

    def is_valid_for_market_date(self, market_date: str | None = None) -> bool:
        return self.market_date == (market_date or current_market_date())

    def validation_errors(self, market_date: str | None = None) -> list[str]:
        errors = list(self.missing_fields)
        expected_market_date = market_date or current_market_date()
        if self.market_date != expected_market_date:
            errors.append("market_date")
        if not self.captured_at:
            errors.append("captured_at")
        if not self.source:
            errors.append("source")
        if self.day_start_equity is None and "day_start_equity" not in errors:
            errors.append("day_start_equity")
        if self.day_start_unrealized is None and "day_start_unrealized" not in errors:
            errors.append("day_start_unrealized")
        return errors

    def to_dict(self) -> dict:
        return asdict(self)


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_snapshot(project_root: Path) -> Optional[DayStartSnapshot]:
    path = project_root / _SNAPSHOT_RELATIVE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return DayStartSnapshot(
        market_date=str(data.get("market_date") or ""),
        captured_at=str(data.get("captured_at") or ""),
        source=str(data.get("source") or ""),
        day_start_equity=data.get("day_start_equity"),
        day_start_unrealized=data.get("day_start_unrealized"),
        missing_fields=list(data.get("missing_fields") or []),
    )


def capture_snapshot(
    project_root: Path,
    *,
    equity: Optional[float],
    unrealized_pnl: Optional[float],
    source: str = "unknown",
    market_date: str | None = None,
) -> DayStartSnapshot:
    missing: list[str] = []
    if equity is None:
        missing.append("day_start_equity")
    if unrealized_pnl is None:
        missing.append("day_start_unrealized")
    if not source:
        missing.append("source")

    snapshot = DayStartSnapshot(
        market_date=market_date or current_market_date(),
        captured_at=datetime.now(timezone.utc).isoformat(),
        source=source or "unknown",
        day_start_equity=equity,
        day_start_unrealized=unrealized_pnl,
        missing_fields=missing,
    )
    _write_atomic(project_root / _SNAPSHOT_RELATIVE, snapshot.to_dict())
    return snapshot


def load_or_capture_day_start(
    project_root: Path,
    *,
    equity: Optional[float] = None,
    unrealized_pnl: Optional[float] = None,
    source: str = "unknown",
    allow_missing: bool = False,
    market_date: str | None = None,
) -> DayStartSnapshot:
    expected_market_date = market_date or current_market_date()
    existing = load_snapshot(project_root)

    _existing_has_missing = existing is not None and bool(existing.missing_fields)
    _incoming_has_equity = equity is not None
    _incoming_has_unrealized = unrealized_pnl is not None

    # Use existing snapshot only when:
    #  1. It is for today, AND
    #  2. It has no missing fields OR the incoming call cannot improve it
    # If existing is missing fields and incoming call has better data, re-capture.
    _can_improve = _existing_has_missing and (_incoming_has_equity or _incoming_has_unrealized)
    if (
        existing is not None
        and existing.is_valid_for_market_date(expected_market_date)
        and not _can_improve
    ):
        snapshot = existing
    else:
        # Prefer existing partial values when incoming values are None
        _equity = equity
        _unrealized = unrealized_pnl
        if existing is not None and existing.is_valid_for_market_date(expected_market_date):
            if _equity is None and existing.day_start_equity is not None:
                _equity = existing.day_start_equity
            if _unrealized is None and existing.day_start_unrealized is not None:
                _unrealized = existing.day_start_unrealized
        snapshot = capture_snapshot(
            project_root,
            equity=_equity,
            unrealized_pnl=_unrealized,
            source=source,
            market_date=expected_market_date,
        )

    errors = snapshot.validation_errors(expected_market_date)
    if errors:
        snapshot.missing_fields = sorted(set(errors))
        if not allow_missing:
            raise DayStartMissingError(
                f"day-start snapshot invalid: {snapshot.missing_fields}. "
                "BUY orders must remain halted until a fresh baseline is captured."
            )
    return snapshot


def get_prev_unrealized_for_guardrail(
    project_root: Path,
    *,
    equity: Optional[float] = None,
    unrealized_pnl: Optional[float] = None,
    source: str = "unknown",
    market_date: str | None = None,
) -> tuple[float | None, list[str]]:
    try:
        snapshot = load_or_capture_day_start(
            project_root,
            equity=equity,
            unrealized_pnl=unrealized_pnl,
            source=source,
            allow_missing=True,
            market_date=market_date,
        )
    except Exception:
        return None, ["day_start_equity", "day_start_unrealized", "captured_at", "source"]

    missing = sorted(set(snapshot.validation_errors(market_date)))
    return snapshot.day_start_unrealized, missing
