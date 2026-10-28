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
        "consumed_qty":  0.0..qty,
        "consumed_by":   "<latest consumer id or null>",
        "consumption_events": [{"trade_id": "...", "qty": 12.0, "consumed_at": "..."}],
        "consumed_at":   "<ISO-8601 UTC or null>",
        "source":        "broker_api",
        "quarantine_reason": null  # set when fill is quarantined
    }
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LEDGER_RELATIVE = Path("data/tracking/fill_ledger.jsonl")
CONSUMED_LEDGER_RELATIVE = Path("data/tracking/fill_consumed_ledger.json")


class FillAlreadyConsumedError(RuntimeError):
    """Raised when attempting to consume a fill_id that has already been consumed."""


class MissingFillIdError(ValueError):
    """Raised when a fill has no usable identifier."""


class FillQuarantinedError(RuntimeError):
    """Raised when a quarantined fill is used for consumption."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_qty(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


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
        self.consumed_path = project_root / CONSUMED_LEDGER_RELATIVE
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.consumed_path.parent.mkdir(parents=True, exist_ok=True)
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
                        qty = _normalize_qty(rec.get("qty"))
                        consumed_qty = rec.get("consumed_qty")
                        if consumed_qty is None:
                            consumed_qty = qty if rec.get("consumed") else 0.0
                        rec["qty"] = qty
                        rec["consumed_qty"] = _normalize_qty(consumed_qty)
                        if "consumption_events" not in rec:
                            if rec.get("consumed_by") and rec["consumed_qty"] > 0:
                                rec["consumption_events"] = [{
                                    "trade_id": rec.get("consumed_by"),
                                    "qty": rec["consumed_qty"],
                                    "consumed_at": rec.get("consumed_at"),
                                }]
                            else:
                                rec["consumption_events"] = []
                        rec["consumed"] = (
                            rec["qty"] > 0
                            and rec["consumed_qty"] >= rec["qty"]
                            and not rec.get("quarantine_reason")
                        )
                        self._cache[key] = rec
                except (json.JSONDecodeError, KeyError):
                    continue
        self._loaded = True
        if self._cache and not self.consumed_path.exists():
            self._write_consumed_snapshot()

    def reload(self) -> None:
        self._loaded = False
        self._ensure_loaded()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest(self, fill: Dict[str, Any], *, quarantine_on_missing: bool = False) -> str:
        """Add a fill to the ledger if not already present.

        Returns the fill_id used.
        Raises MissingFillIdError if no stable key can be derived.
        """
        self._ensure_loaded()
        key = _fill_key(fill)
        if key is None:
            if quarantine_on_missing:
                return self._quarantine(fill, "missing_fill_id")
            raise MissingFillIdError(
                f"Fill has no usable identifier and cannot be ingested: {fill}"
            )

        existing = self._cache.get(key)

        filled_at = (
            fill.get("filled_at")
            or fill.get("updated_at")
            or fill.get("created_at")
            or fill.get("submitted_at")
        )
        if not filled_at:
            if existing:
                return key
            self._append(self._build_record(fill, key=key, filled_at=None, quarantine_reason="missing_timestamp"))
            return key

        record = self._build_record(fill, key=key, filled_at=str(filled_at))
        if existing is None:
            self._append(record)
            return key

        updated = dict(existing)
        changed = False
        observed_qty = _normalize_qty(record.get("qty"))
        if observed_qty > _normalize_qty(existing.get("qty")):
            updated["qty"] = observed_qty
            changed = True
        if record.get("price") and record.get("price") != existing.get("price"):
            updated["price"] = record["price"]
            changed = True
        if record.get("filled_at") and record.get("filled_at") != existing.get("filled_at"):
            updated["filled_at"] = record["filled_at"]
            changed = True
        if existing.get("quarantine_reason") and not record.get("quarantine_reason"):
            updated["quarantine_reason"] = None
            changed = True
        if changed:
            updated["ingested_at"] = _now_utc()
            updated["consumed"] = (
                _normalize_qty(updated.get("consumed_qty")) >= _normalize_qty(updated.get("qty"))
                and not updated.get("quarantine_reason")
            )
            self._append(updated)
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
                    self.ingest(fill, quarantine_on_missing=True)
                    quarantined += 1
                    continue
                before = self._cache.get(key)
                before_qty = _normalize_qty((before or {}).get("qty"))
                ingested_key = self.ingest(fill, quarantine_on_missing=True)
                after = self._cache.get(ingested_key) or {}
                if after.get("quarantine_reason"):
                    quarantined += 1
                elif before is not None and before_qty >= _normalize_qty(after.get("qty")):
                    skipped += 1
                else:
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

    def consume(self, fill_id: str, trade_id: str, qty: float | None = None) -> None:
        """Mark a fill as consumed by a trade.

        Raises FillAlreadyConsumedError if already consumed.
        """
        self._ensure_loaded()
        rec = self._cache.get(fill_id)
        if rec is None:
            # Fill not in ledger — allow (legacy fills may predate ledger)
            return
        if rec.get("quarantine_reason"):
            raise FillQuarantinedError(
                f"fill_id={fill_id!r} is quarantined: {rec.get('quarantine_reason')}"
            )

        total_qty = _normalize_qty(rec.get("qty"))
        consumed_qty = _normalize_qty(rec.get("consumed_qty"))
        remaining_qty = max(0.0, total_qty - consumed_qty)
        qty_to_consume = remaining_qty if qty is None else _normalize_qty(qty)

        if qty_to_consume <= 0:
            raise FillAlreadyConsumedError(
                f"fill_id={fill_id!r} has no remaining quantity to consume. "
                f"observed_qty={total_qty} consumed_qty={consumed_qty} trade_id={trade_id!r}."
            )
        if qty_to_consume > remaining_qty + 1e-9:
            raise FillAlreadyConsumedError(
                f"fill_id={fill_id!r} over-consumption attempted. "
                f"observed_qty={total_qty} consumed_qty={consumed_qty} "
                f"requested_qty={qty_to_consume} trade_id={trade_id!r}."
            )

        updated = dict(rec)
        updated["consumed_qty"] = round(consumed_qty + qty_to_consume, 8)
        updated["consumed"] = updated["consumed_qty"] >= total_qty - 1e-9
        updated["consumed_by"] = trade_id
        updated["consumed_at"] = _now_utc()
        events = list(rec.get("consumption_events") or [])
        events.append({
            "trade_id": trade_id,
            "qty": round(qty_to_consume, 8),
            "consumed_at": updated["consumed_at"],
        })
        updated["consumption_events"] = events
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

    def available_qty(self, fill_id: str) -> float:
        self._ensure_loaded()
        rec = self._cache.get(fill_id) or {}
        return max(0.0, _normalize_qty(rec.get("qty")) - _normalize_qty(rec.get("consumed_qty")))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_record(
        self,
        fill: Dict[str, Any],
        *,
        key: str,
        filled_at: str | None,
        quarantine_reason: str | None = None,
    ) -> Dict[str, Any]:
        return {
            "fill_id": key,
            "order_id": fill.get("order_id") or fill.get("id"),
            "symbol": (fill.get("symbol") or "").upper(),
            "side": (fill.get("side") or "").lower(),
            "qty": _normalize_qty(fill.get("qty") or fill.get("filled_qty")),
            "price": _normalize_qty(fill.get("filled_avg_price") or fill.get("price")),
            "filled_at": filled_at,
            "ingested_at": _now_utc(),
            "consumed": False,
            "consumed_qty": 0.0,
            "consumed_by": None,
            "consumption_events": [],
            "consumed_at": None,
            "source": "broker_api",
            "quarantine_reason": quarantine_reason,
        }

    def _quarantine(self, fill: Dict[str, Any], reason: str) -> str:
        raw = json.dumps(fill, ensure_ascii=False, sort_keys=True, default=str)
        fallback = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        key = str(fill.get("order_id") or fill.get("id") or f"quarantine:{fallback}")
        if key in self._cache:
            return key
        self._append(self._build_record(fill, key=key, filled_at=None, quarantine_reason=reason))
        return key

    def _append(self, record: Dict[str, Any]) -> None:
        """Append one record atomically and update cache."""
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(self.ledger_path, "a", encoding="utf-8") as fh:
            fh.write(line)
        self._cache[record["fill_id"]] = record
        self._write_consumed_snapshot()

    def _write_consumed_snapshot(self) -> None:
        snapshot = {
            "generated_at": _now_utc(),
            "fills": [
                {
                    "fill_id": rec.get("fill_id"),
                    "order_id": rec.get("order_id"),
                    "symbol": rec.get("symbol"),
                    "side": rec.get("side"),
                    "qty": rec.get("qty"),
                    "consumed_qty": rec.get("consumed_qty"),
                    "consumed": rec.get("consumed"),
                    "consumed_by": rec.get("consumed_by"),
                    "consumption_events": rec.get("consumption_events") or [],
                    "quarantine_reason": rec.get("quarantine_reason"),
                }
                for rec in sorted(self._cache.values(), key=lambda row: str(row.get("fill_id") or ""))
            ],
        }
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.consumed_path.parent),
            prefix=".fill_consumed_ledger.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self.consumed_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
