"""Persistent store for exit reasons keyed by broker_order_id.

When paper_demo submits a sell order from an exit signal, it writes the
exit reason here so that reconcile_orders can look it up when the fill is
detected later (possibly in a different process run).

File: data/tracking/pending_exit_reasons.json
Schema:
{
  "<broker_order_id>": {
    "symbol": "AAPL",
    "exit_trigger": "Trailing stop triggered",
    "exit_reason": "trailing_stop",
    "signal_strength": 0.95,
    "return_pct": 0.12,
    "peak_return_pct": 0.15,
    "eff_stop_loss_pct": -0.07,
    "written_at": "2026-05-27T..."
  },
  ...
}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FILENAME = "data/tracking/pending_exit_reasons.json"


def _store_path(project_root: Path) -> Path:
    p = project_root / _FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_exit_reason(
    project_root: Path,
    broker_order_id: str,
    symbol: str,
    exit_trigger: str,
    exit_reason: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist exit reason for a submitted sell order."""
    if not broker_order_id:
        return
    path = _store_path(project_root)
    try:
        store: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        store = {}

    store[broker_order_id] = {
        "symbol": symbol,
        "exit_trigger": exit_trigger,
        "exit_reason": exit_reason,
        "written_at": datetime.now(timezone.utc).isoformat(),
        **(metadata or {}),
    }
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.debug("exit_reason_store: wrote %s → %s", broker_order_id, exit_reason)


def read_exit_reason(project_root: Path, broker_order_id: str) -> dict[str, Any] | None:
    """Look up stored exit reason for a broker order ID. Returns None if not found."""
    if not broker_order_id:
        return None
    path = _store_path(project_root)
    if not path.exists():
        return None
    try:
        store: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return store.get(broker_order_id)
    except Exception:
        return None


def delete_exit_reason(project_root: Path, broker_order_id: str) -> None:
    """Remove a fulfilled entry from the store (cleanup after fill recorded)."""
    if not broker_order_id:
        return
    path = _store_path(project_root)
    if not path.exists():
        return
    try:
        store: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if broker_order_id in store:
            del store[broker_order_id]
            path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def purge_old_entries(project_root: Path, max_age_days: int = 7) -> int:
    """Remove entries older than max_age_days. Returns count removed."""
    path = _store_path(project_root)
    if not path.exists():
        return 0
    try:
        store: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc)
        to_remove = []
        for oid, entry in store.items():
            written = entry.get("written_at", "")
            if written:
                try:
                    age = now - datetime.fromisoformat(written.replace("Z", "+00:00"))
                    if age.days >= max_age_days:
                        to_remove.append(oid)
                except Exception:
                    pass
        for oid in to_remove:
            del store[oid]
        if to_remove:
            path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
        return len(to_remove)
    except Exception:
        return 0
