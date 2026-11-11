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
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FILENAME = "data/tracking/pending_exit_reasons.json"

EXIT_LINEAGE_FIELDS = (
    "exit_decision_id", "exit_run_id", "exit_experiment_id", "exit_config_hash",
    "exit_decision_time", "exit_submission_id", "exit_submitted_at",
)


def validate_exit_lineage(context: Any, broker_order_id: str, symbol: str) -> dict[str, str]:
    """Return only complete exact-order provenance; never infer it from entry IDs."""
    if not isinstance(context, dict) or set(context) != {*EXIT_LINEAGE_FIELDS, "symbol", "broker_order_id"}:
        return {}
    if context["symbol"] != symbol or context["broker_order_id"] != broker_order_id or not broker_order_id:
        return {}
    if any(not isinstance(v, str) or not v.strip() or len(v) > 256 or any(ord(c) < 32 for c in v) for v in context.values()):
        return {}
    # ExperimentContext currently emits a 16-hex configuration-version token;
    # full SHA-256 tokens are also accepted. Do not relabel the short token as
    # a full-byte configuration capture or cryptographic integrity receipt.
    if re.fullmatch(r"(?:[0-9a-fA-F]{16}|[0-9a-fA-F]{64})", context["exit_config_hash"]) is None:
        return {}
    try:
        decision = datetime.fromisoformat(context["exit_decision_time"].replace("Z", "+00:00"))
        submitted = datetime.fromisoformat(context["exit_submitted_at"].replace("Z", "+00:00"))
        if decision.utcoffset() is None or submitted.utcoffset() is None or decision > submitted:
            return {}
    except (ValueError, TypeError, OverflowError):
        return {}
    return {name: context[name] for name in EXIT_LINEAGE_FIELDS}


def build_exit_lineage(decision: Any, submission: Any) -> dict[str, str]:
    """Bind an accepted SELL only; no fill identity is manufactured here."""
    if (getattr(decision, "action", None) != "sell" or submission.side != "sell"
            or submission.status != "submitted" or decision.decision_id != submission.decision_id
            or decision.symbol != submission.symbol):
        return {}
    if not isinstance(submission.submitted_at, datetime):
        return {}
    context = dict(symbol=submission.symbol, broker_order_id=submission.broker_order_id,
        exit_decision_id=decision.decision_id, exit_run_id=decision.run_id,
        exit_experiment_id=decision.experiment_id, exit_config_hash=decision.config_hash,
        exit_decision_time=decision.decision_time, exit_submission_id=submission.submission_id,
        exit_submitted_at=submission.submitted_at.isoformat())
    return context if validate_exit_lineage(context, submission.broker_order_id, submission.symbol) else {}


def resolve_exit_lineage(project_root: Path, broker_order_id: str | None, symbol: str,
                         trades: list[dict[str, Any]]) -> dict[str, str]:
    """Pending context or unanimous complete closed legs for this exact order.

    This labels the existing reconciliation result. It does not certify or change
    the reconciler's economic lot-matching policy. Missing/conflicting legs withhold.
    """
    if not broker_order_id:
        return {}
    # One coherent read: an unreadable store is not an absent order, and a
    # second read could mix two concurrent pending-store revisions.
    try:
        raw_store = json.loads((project_root / _FILENAME).read_text(encoding="utf-8"))
        if not isinstance(raw_store, dict):
            return {}
    except FileNotFoundError:
        raw_store = {}
    except (OSError, ValueError, TypeError):
        return {}
    pending = raw_store.get(broker_order_id)
    if broker_order_id in raw_store and pending is None:
        return {}
    contexts = []
    if pending is not None:
        if not isinstance(pending, dict) or pending.get("symbol") != symbol:
            return {}
        validated = validate_exit_lineage(pending.get("exit_lineage"), broker_order_id, symbol)
        if not validated:
            return {}
        contexts.append(validated)
    for trade in trades:
        if trade.get("status") == "closed" and trade.get("symbol") == symbol and trade.get("exit_broker_order_id") == broker_order_id:
            context = {name: trade.get(name) for name in EXIT_LINEAGE_FIELDS}
            context.update(symbol=symbol, broker_order_id=broker_order_id)
            validated = validate_exit_lineage(context, broker_order_id, symbol)
            if not validated:
                return {}
            contexts.append(validated)
    return contexts[0] if contexts and all(c == contexts[0] for c in contexts) else {}


def _store_path(project_root: Path) -> Path:
    p = project_root / _FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _atomic_write(path: Path, store: dict[str, Any]) -> None:
    """Write store dict to path atomically using temp-file + os.replace."""
    content = json.dumps(store, indent=2, ensure_ascii=False)
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(dir=str(dir_path), prefix=".exit_reasons.", suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def write_exit_reason(
    project_root: Path,
    broker_order_id: str,
    symbol: str,
    exit_trigger: str,
    exit_reason: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist exit reason for a submitted sell order (atomic write)."""
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
    _atomic_write(path, store)
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


def read_recent_pending_exit_symbols(
    project_root: Path,
    max_age_seconds: int = 30 * 60,
    *,
    now: datetime | None = None,
) -> set[str]:
    """Return symbols with a recently submitted, not-yet-consumed SELL.

    The pending-exit store survives across ``paper_demo`` runs, unlike the
    current run's in-memory submission list.  A short, strict TTL lets the
    post-run mismatch guard excuse the known fill-ingestion window without
    hiding a persistent broker/tracker discrepancy.

    Missing, corrupt, malformed, stale, or future-dated entries are ignored
    (fail closed).  An entry exactly on the TTL boundary remains valid.
    """
    if max_age_seconds < 0:
        return set()

    path = _store_path(project_root)
    if not path.exists():
        return set()

    try:
        store: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()

    reference_time = now or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    symbols: set[str] = set()
    for entry in store.values():
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol")
        written_at = entry.get("written_at")
        if not isinstance(symbol, str) or not symbol.strip() or not isinstance(written_at, str):
            continue
        try:
            written = datetime.fromisoformat(written_at.replace("Z", "+00:00"))
            if written.tzinfo is None:
                written = written.replace(tzinfo=timezone.utc)
            age_seconds = (reference_time - written).total_seconds()
        except (TypeError, ValueError):
            continue
        if 0 <= age_seconds <= max_age_seconds:
            symbols.add(symbol.strip().upper())

    return symbols


def delete_exit_reason(project_root: Path, broker_order_id: str) -> None:
    """Remove a fulfilled entry from the store atomically (cleanup after fill recorded)."""
    if not broker_order_id:
        return
    path = _store_path(project_root)
    if not path.exists():
        return
    try:
        store: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if broker_order_id in store:
            del store[broker_order_id]
            _atomic_write(path, store)
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
            _atomic_write(path, store)
        return len(to_remove)
    except Exception:
        return 0
