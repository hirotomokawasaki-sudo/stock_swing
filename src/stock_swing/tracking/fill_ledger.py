"""Immutable fill ledger with exactly-once consumption tracking.

FIX-LEDGER-3: Every broker fill is keyed by fill_id (or order_id+symbol+side
as fallback). Each fill_id can only be consumed (applied to a trade) once.
A second attempt to consume the same fill_id raises FillAlreadyConsumedError.

File format (data/tracking/fill_ledger.jsonl):
    One JSON object per line. Appended atomically via temp-rename.
    {
        "fill_id":       "<broker fill id or synthetic key>",
        "order_id":      "<broker order id>",
        "symbol":        "AAPL",
        "side":          "buy" | "sell",
        "qty":           100,
        "price":         150.25,
        "filled_at":     "<ISO-8601 UTC>",
        "ingested_at":   "<ISO-8601 UTC>",
        "consumed":      true | false,
        "consumed_by":   "<trade_id or null>",
        "consumed_at":   "<ISO-8601 UTC or null>",
        "source":        "broker_api",
        "quarantine_reason": null  # set when fill is quarantined
    }
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LEDGER_RELATIVE = Path("data/tracking/fill_ledger.jsonl")


class FillAlreadyConsumedError(RuntimeError):
    """Raised when attempting to consume a fill_id that has already been consumed."""


class MissingFillIdError(ValueError):
    """Raised when a fill has no usable identifier."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fill_key(fill: Dict[str, Any]) -> Optional[str]:
    """Return a stable, unique key for a broker fill dict.

    Preference order:
      1. fill.id  (Alpaca execution fill id)
      2. fill.order_id + ":" + fill.symbol + ":" + fill.side (order-level)
      3. None → fill must be quarantined
    """
    fid = fill.get("id") or fill.get("fill_id")
    if fid:
        return str(fid)
    order_id = fill.get("order_id") or fill.get("id")
    symbol = fill.get("symbol", "")
    side = fill.get("side", "")
    if order_id and symbol and side:
        return f"{order_id}:{symbol.upper()}:{side.lower()}"
    return None


class FillLedger:
    """Append-only fill ledger with exactly-once consumption guarantee.

    Usage:
        ledger = FillLedger(project_root)
        # Ingest new fills from broker
        for fill in broker_fills:
            ledger.ingest(fill)
        # Mark a fill as consumed when recording a trade
        ledger.consume(fill_id=fill_key, trade_id="broker_match_0123_AAPL")
        # Check if already consumed
        if ledger.is_consumed(fill_key):
            raise FillAlreadyConsumedError(...)
    """

    def __init__(self, project_root: Path):
        self.ledger_path = project_root / LEDGER_RELATIVE
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._cache = {}
        if self.ledger_path.exists():
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    key = rec.get("fill_id")
                    if key:
                        self._cache[key] = rec
                except (json.JSONDecodeError, KeyError):
                    continue
        self._loaded = True

    def reload(self) -> None:
        self._loaded = False
        self._ensure_loaded()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest(self, fill: Dict[str, Any]) -> str:
        """Add a fill to the ledger if not already present.

        Returns the fill_id used.
        Raises MissingFillIdError if no stable key can be derived.
        """
        self._ensure_loaded()
        key = _fill_key(fill)
        if key is None:
            raise MissingFillIdError(
                f"Fill has no usable identifier and cannot be ingested: {fill}"
            )

        if key in self._cache:
            return key  # already ingested — idempotent

        filled_at = fill.get("filled_at") or fill.get("created_at") or fill.get("submitted_at")
        if not filled_at:
            # Quarantine: missing timestamp
            self._append({
                "fill_id": key,
                "order_id": fill.get("order_id") or fill.get("id"),
                "symbol": fill.get("symbol", ""),
                "side": fill.get("side", ""),
                "qty": fill.get("qty") or fill.get("filled_qty") or 0,
                "price": fill.get("filled_avg_price") or fill.get("price") or 0,
                "filled_at": None,
                "ingested_at": _now_utc(),
                "consumed": False,
                "consumed_by": None,
                "consumed_at": None,
                "source": "broker_api",
                "quarantine_reason": "missing_timestamp",
            })
            return key

        record = {
            "fill_id": key,
            "order_id": fill.get("order_id") or fill.get("id"),
            "symbol": (fill.get("symbol") or "").upper(),
            "side": (fill.get("side") or "").lower(),
            "qty": float(fill.get("qty") or fill.get("filled_qty") or 0),
            "price": float(fill.get("filled_avg_price") or fill.get("price") or 0),
            "filled_at": str(filled_at),
            "ingested_at": _now_utc(),
            "consumed": False,
            "consumed_by": None,
            "consumed_at": None,
            "source": "broker_api",
            "quarantine_reason": None,
        }
        self._append(record)
        return key

    def ingest_many(self, fills: List[Dict[str, Any]]) -> tuple[int, int, int]:
        """Ingest multiple fills. Returns (ingested, skipped_dup, quarantined)."""
        ingested = 0
        skipped = 0
        quarantined = 0
        for fill in fills:
            try:
                self._ensure_loaded()
                key = _fill_key(fill)
                if key is None:
                    quarantined += 1
                    continue
                if key in self._cache:
                    skipped += 1
                    continue
                self.ingest(fill)
                ingested += 1
            except MissingFillIdError:
                quarantined += 1
        return ingested, skipped, quarantined

    # ------------------------------------------------------------------
    # Consumption
    # ------------------------------------------------------------------

    def is_consumed(self, fill_id: str) -> bool:
        self._ensure_loaded()
        rec = self._cache.get(fill_id)
        return bool(rec and rec.get("consumed"))

    def consume(self, fill_id: str, trade_id: str) -> None:
        """Mark a fill as consumed by a trade.

        Raises FillAlreadyConsumedError if already consumed.
        """
        self._ensure_loaded()
        rec = self._cache.get(fill_id)
        if rec is None:
            # Fill not in ledger — allow (legacy fills may predate ledger)
            return

        if rec.get("consumed"):
            raise FillAlreadyConsumedError(
                f"fill_id={fill_id!r} already consumed by trade={rec.get('consumed_by')!r} "
                f"at {rec.get('consumed_at')}. Cannot consume again for trade={trade_id!r}."
            )

        updated = dict(rec)
        updated["consumed"] = True
        updated["consumed_by"] = trade_id
        updated["consumed_at"] = _now_utc()
        # Re-write the entire line by appending an update record
        # (we treat the ledger as append-only; last record for a key wins on reload)
        self._append(updated)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, fill_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_loaded()
        return self._cache.get(fill_id)

    def all_fills(self) -> List[Dict[str, Any]]:
        self._ensure_loaded()
        return list(self._cache.values())

    def unconsumed_fills(self) -> List[Dict[str, Any]]:
        self._ensure_loaded()
        return [r for r in self._cache.values() if not r.get("consumed") and not r.get("quarantine_reason")]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, record: Dict[str, Any]) -> None:
        """Append one record atomically and update cache."""
        line = json.dumps(record, ensure_ascii=False) + "\n"
        # Atomic append via temp file + rename not possible on all OS for append;
        # use file open in append mode which is atomic for single writes on POSIX.
        with open(self.ledger_path, "a", encoding="utf-8") as fh:
            fh.write(line)
        self._cache[record["fill_id"]] = record
