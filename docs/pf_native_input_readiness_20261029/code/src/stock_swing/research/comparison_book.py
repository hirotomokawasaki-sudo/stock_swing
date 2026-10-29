"""Research-only accounting for independent comparison arms.

This is NOT an execution simulator, C00 reproduction, or broker adapter.
Callers supply causally timed marks and bounded fills, and own the exit
policy, calendar, corporate actions, and candidate provenance. No imports
from broker/runtime writers and no implicit reads of production files.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping


def _number(value: Any, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("finite numeric value required")
    value = float(value)
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError("positive/nonnegative finite value required")
    return value


def _quantity(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("positive integer shares required")
    return value


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("aware ISO timestamp required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("naive timestamp forbidden")
    return result.astimezone(timezone.utc)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: str
    strategy_id: str
    semiconductor_fraction: float | None

    def __post_init__(self) -> None:
        if (not isinstance(self.symbol, str) or not self.symbol.strip()
                or self.asset_class not in {"stock", "etf"}
                or not isinstance(self.strategy_id, str) or not self.strategy_id.strip()):
            raise ValueError("explicit symbol, class and strategy required")
        if self.semiconductor_fraction is not None:
            if _number(self.semiconductor_fraction, positive=False) > 1:
                raise ValueError("look-through exposure must be within [0,1]")


@dataclass(frozen=True)
class BookPolicy:
    arm_id: str
    baseline_equity: float
    quantity_scale: float = 1.0
    atr_sizing: bool = False
    semiconductor_cap: float | None = None
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    max_quote_age_seconds: float = 300.0
    max_atr_age_seconds: float = 7 * 86400.0

    def __post_init__(self) -> None:
        if not isinstance(self.arm_id, str) or not self.arm_id.strip() or not isinstance(self.atr_sizing, bool):
            raise ValueError("arm identity and explicit ATR flag required")
        _number(self.baseline_equity)
        if _number(self.quantity_scale) > 1:
            raise ValueError("scale must be reduce-only")
        if self.semiconductor_cap is not None and _number(self.semiconductor_cap) > 1:
            raise ValueError("cap outside (0,1]")
        for cost in (self.fee_bps, self.slippage_bps):
            if _number(cost, positive=False) >= 10000:
                raise ValueError("invalid costs")
        _number(self.max_quote_age_seconds)
        _number(self.max_atr_age_seconds)


class ComparisonBook:
    """A single arm's cash, reservations, lots, costs and replayable events.

    BUY reservations are bounded by max_fill_price (raw), not a promise
    that a market order will fill at a cap. A gap beyond the bound requires
    rejection/cancellation and a separately priced event. All pending BUYs
    share cash and projected semiconductor capacity. SELL never depends on
    a concentration check. Methods deliberately do not generate signals.
    """

    _FIELDS = {
        "mark": set(),
        "reserve": {"order_id", "symbol", "qty", "max_fill_price", "atr", "atr_available_at", "strategy_id"},
        "fill": {"order_id", "qty", "raw_price"},
        "cancel": {"order_id"},
        "sell": {"lot_id", "qty", "raw_price"},
    }

    def __init__(self, policy: BookPolicy, instruments: list[Instrument]) -> None:
        self.policy = policy
        self.instruments = {x.symbol: x for x in instruments}
        if len(self.instruments) != len(instruments):
            raise ValueError("duplicate instrument")
        self.cash = float(policy.baseline_equity)
        self.realized_pnl = 0.0
        self.fees = 0.0
        self.slippage = 0.0
        self.pending: dict[str, dict] = {}
        self.lots: dict[str, dict] = {}
        self.quotes: dict[str, dict] = {}
        self.last_at: str | None = None
        self._receipts: dict[str, dict] = {}
        self._events: list[dict] = []
        self._used_orders: set[str] = set()

    def _buy_unit(self, raw: float) -> tuple[float, float, float]:
        execution = raw * (1 + self.policy.slippage_bps / 10000)
        fee = execution * self.policy.fee_bps / 10000
        return execution + fee, fee, execution - raw

    def _refresh(self, quotes: Mapping[str, Any], now: datetime) -> None:
        if not isinstance(quotes, dict):
            raise ValueError("quotes must be a mapping")
        for symbol, quote in quotes.items():
            if symbol not in self.instruments or not isinstance(quote, dict) or set(quote) != {"price", "as_of"}:
                raise ValueError("invalid quote or unknown symbol")
            age = (now - _time(quote["as_of"])).total_seconds()
            if age < 0 or age > self.policy.max_quote_age_seconds:
                raise ValueError("future or stale quote")
            _number(quote["price"])
            if symbol in self.quotes and _time(quote["as_of"]) < _time(self.quotes[symbol]["as_of"]):
                raise ValueError("quote timestamp regressed")
            self.quotes[symbol] = deepcopy(quote)

    def _mark(self, symbol: str, now: datetime, *, fresh: bool) -> float:
        quote = self.quotes.get(symbol)
        if quote is None:
            raise ValueError("missing mark")
        age = (now - _time(quote["as_of"])).total_seconds()
        if age < 0 or (fresh and age > self.policy.max_quote_age_seconds):
            raise ValueError("unusable mark")
        return _number(quote["price"])

    def _equity(self, now: datetime, *, fresh: bool) -> float:
        value = self.cash + sum(x["qty"] * self._mark(x["symbol"], now, fresh=fresh) for x in self.lots.values())
        if not math.isfinite(value):
            raise ValueError("nonfinite valuation")
        return value

    def _reserved_cash(self) -> float:
        return sum(x["qty"] * self._buy_unit(x["max_fill_price"])[0] for x in self.pending.values())

    def _capacity(self, now: datetime, candidate: dict | None = None) -> None:
        equity = self._equity(now, fresh=True)
        if equity <= 0:
            raise ValueError("nonpositive equity blocks new risk")
        if self.policy.semiconductor_cap is None:
            return
        exposure = 0.0
        for lot in self.lots.values():
            fraction = self.instruments[lot["symbol"]].semiconductor_fraction
            if fraction is None:
                raise ValueError("unknown look-through exposure")
            exposure += lot["qty"] * self._mark(lot["symbol"], now, fresh=True) * fraction
        orders = list(self.pending.values()) + ([candidate] if candidate else [])
        expected_cost = 0.0
        for order in orders:
            fraction = self.instruments[order["symbol"]].semiconductor_fraction
            if fraction is None:
                raise ValueError("unknown look-through exposure")
            unit, fee, slip = self._buy_unit(order["max_fill_price"])
            current_mark = self._mark(order["symbol"], now, fresh=True)
            exposure += order["qty"] * max(unit - fee, current_mark) * fraction
            expected_cost += order["qty"] * (fee + slip)
        # Conservative bound: value pending shares at their adverse fill
        # budget and reduce equity by their adverse execution costs.
        projected_equity = equity - expected_cost
        if projected_equity <= 0 or exposure > projected_equity * self.policy.semiconductor_cap + 1e-8:
            raise ValueError("projected semiconductor cap")

    def apply(self, event: Mapping[str, Any]) -> dict:
        """Atomically apply one event; exact retry is no-op, conflict fails.

        Invalid input, timing, cash, cap, fill or quantity leaves every
        byte of the exported book unchanged (including the event clock).
        """
        if not isinstance(event, dict):
            raise ValueError("event must be a mapping")
        try:
            encoded = _canonical(event)
        except (ValueError, TypeError) as exc:
            raise ValueError("event must be finite JSON") from exc
        event = json.loads(encoded)
        kind, event_id = event.get("kind"), event.get("event_id")
        if not isinstance(kind, str) or kind not in self._FIELDS or not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("valid kind and event_id required")
        allowed = self._FIELDS[kind] | {"kind", "event_id", "at", "quotes"}
        if set(event) - allowed:
            raise ValueError("unrecognized event fields")
        digest = sha256(encoded.encode()).hexdigest()
        if event_id in self._receipts:
            receipt = self._receipts[event_id]
            if receipt["digest"] != digest:
                raise ValueError("conflicting event retry")
            return deepcopy(receipt["result"])
        work = deepcopy(self)
        now = _time(event.get("at"))
        if work.last_at is not None and now < _time(work.last_at):
            raise ValueError("event chronology regressed")
        work._refresh(event.get("quotes", {}), now)
        try:
            result = work._execute(kind, event, now)
        except (OverflowError, ZeroDivisionError) as exc:
            raise ValueError("invalid monetary arithmetic") from exc
        if not all(math.isfinite(x) for x in (work.cash, work.realized_pnl, work.fees, work.slippage, work._reserved_cash())):
            raise ValueError("nonfinite monetary state")
        if work.cash < -1e-8 or work.cash - work._reserved_cash() < -1e-8:
            raise ValueError("cash conservation/reservation violation")
        work.last_at = now.isoformat()
        work._events.append(event)
        work._receipts[event_id] = {"digest": digest, "result": deepcopy(result)}
        self.__dict__.clear()
        self.__dict__.update(work.__dict__)
        return deepcopy(result)

    def _execute(self, kind: str, e: dict, now: datetime) -> dict:
        if kind == "mark":
            self._equity(now, fresh=True)
            return {"status": "marked"}
        if kind == "reserve":
            symbol, order_id = e.get("symbol"), e.get("order_id")
            if not isinstance(symbol, str) or symbol not in self.instruments or not isinstance(order_id, str) or not order_id.strip():
                raise ValueError("known symbol/order required")
            if order_id in self._used_orders:
                raise ValueError("order ID reused")
            if self.instruments[symbol].semiconductor_fraction is None:
                raise ValueError("unknown look-through exposure blocks BUY")
            requested = _quantity(e.get("qty"))
            price = self._mark(symbol, now, fresh=True)
            upper = _number(e.get("max_fill_price"))
            qty = math.floor(requested * self.policy.quantity_scale)
            if self.policy.atr_sizing:
                age = (now - _time(e.get("atr_available_at"))).total_seconds()
                if age < 0 or age > self.policy.max_atr_age_seconds:
                    raise ValueError("future or stale ATR")
                # Upper-bound reservation price avoids under-budgeting the
                # 5% floor across a gap. This is a technical sizing bound,
                # not a claim to reproduce P0's actual-entry-price path.
                width = max(2 * _number(e.get("atr")), max(price, upper) * .05)
                qty = min(qty, math.floor(self.policy.baseline_equity * .003 / width))
            unit = self._buy_unit(upper)[0]
            qty = min(qty, max(0, math.floor((self.cash - self._reserved_cash()) / unit)))
            if qty < 1:
                raise ValueError("no affordable reduce-only shares")
            strategy = e.get("strategy_id", self.instruments[symbol].strategy_id)
            if not isinstance(strategy, str) or not strategy.strip():
                raise ValueError("explicit strategy origin required")
            order = {"symbol": symbol, "strategy_id": strategy, "qty": qty, "max_fill_price": upper}
            self._capacity(now, order)
            self.pending[order_id] = order
            self._used_orders.add(order_id)
            return {"status": "reserved", "order_id": order_id, "qty": qty, "requested_qty": requested}
        if kind == "cancel":
            order_id = e.get("order_id")
            if not isinstance(order_id, str) or order_id not in self.pending:
                raise ValueError("unknown pending order")
            del self.pending[order_id]
            return {"status": "cancelled", "order_id": order_id}
        if kind == "fill":
            order_id = e.get("order_id")
            if not isinstance(order_id, str) or order_id not in self.pending:
                raise ValueError("unknown pending order")
            order = self.pending[order_id]
            qty, raw = _quantity(e.get("qty")), _number(e.get("raw_price"))
            if qty > order["qty"] or raw > order["max_fill_price"]:
                raise ValueError("fill exceeds reserved quantity/price; explicit repricing required")
            self._mark(order["symbol"], now, fresh=True)
            self._capacity(now)
            unit, fee, slip = self._buy_unit(raw)
            lot_id = "lot:" + sha256(_canonical([order_id, e["event_id"]]).encode()).hexdigest()
            self.cash -= unit * qty
            self.fees += fee * qty
            self.slippage += slip * qty
            if lot_id in self.lots:
                raise ValueError("duplicate lot identity")
            self.lots[lot_id] = {"symbol": order["symbol"], "strategy_id": order["strategy_id"],
                                 "order_id": order_id, "entry_event_id": e["event_id"],
                                 "qty": qty, "unit_basis": unit, "bought_at": now.isoformat()}
            order["qty"] -= qty
            if order["qty"] == 0:
                del self.pending[order_id]
            return {"status": "filled", "lot_id": lot_id, "qty": qty}
        if kind == "sell":
            lot_id = e.get("lot_id")
            if not isinstance(lot_id, str) or lot_id not in self.lots:
                raise ValueError("unknown lot")
            lot = self.lots[lot_id]
            qty, raw = _quantity(e.get("qty")), _number(e.get("raw_price"))
            if qty > lot["qty"]:
                raise ValueError("cannot oversell lot")
            execution = raw * (1 - self.policy.slippage_bps / 10000)
            fee = execution * self.policy.fee_bps / 10000
            proceeds = (execution - fee) * qty
            pnl = proceeds - lot["unit_basis"] * qty
            self.cash += proceeds
            self.realized_pnl += pnl
            self.fees += fee * qty
            self.slippage += (raw - execution) * qty
            lot["qty"] -= qty
            if not lot["qty"]:
                del self.lots[lot_id]
            return {"status": "sold", "qty": qty, "realized_pnl": pnl}
        raise ValueError("unsupported event")

    def snapshot(self) -> dict:
        """Mark-to-market bridge; stale SELL-side marks remain qualified.

        A SELL can proceed even when a different holding's mark is stale,
        but the resulting NAV is explicitly unqualified until fresh marks.
        """
        now = _time(self.last_at) if self.last_at else datetime.min.replace(tzinfo=timezone.utc)
        equity = self._equity(now, fresh=False)
        unrealized = sum(x["qty"] * (self._mark(x["symbol"], now, fresh=False) - x["unit_basis"]) for x in self.lots.values())
        if not math.isfinite(equity) or not math.isfinite(unrealized):
            raise ValueError("nonfinite valuation")
        qualified = all(0 <= (now - _time(self.quotes[x["symbol"]]["as_of"])).total_seconds() <= self.policy.max_quote_age_seconds for x in self.lots.values())
        by_class = {c: sum(x["qty"] * self._mark(x["symbol"], now, fresh=False) for x in self.lots.values() if self.instruments[x["symbol"]].asset_class == c) for c in ("stock", "etf")}
        strategies = {x.strategy_id for x in self.instruments.values()} | {x["strategy_id"] for x in self.lots.values()}
        by_strategy = {s: sum(x["qty"] * self._mark(x["symbol"], now, fresh=False) for x in self.lots.values() if x["strategy_id"] == s) for s in sorted(strategies)}
        return {"arm_id": self.policy.arm_id, "as_of": self.last_at, "cash": self.cash,
                "reserved_cash": self._reserved_cash(), "available_cash": self.cash-self._reserved_cash(),
                "equity": equity, "valuation_qualified": qualified, "realized_pnl": self.realized_pnl,
                "unrealized_pnl": unrealized, "fees": self.fees, "slippage": self.slippage,
                "bridge_residual": equity-self.policy.baseline_equity-self.realized_pnl-unrealized,
                "market_value_by_asset_class": by_class, "market_value_by_strategy": by_strategy,
                "lots": deepcopy(self.lots), "pending": deepcopy(self.pending)}

    def dumps(self) -> str:
        """Serialize the event source, not a trusted cash/position snapshot."""
        payload = {"version": 1, "policy": asdict(self.policy),
                   "instruments": [asdict(self.instruments[s]) for s in sorted(self.instruments)],
                   "events": deepcopy(self._events)}
        return _canonical({"payload": payload, "sha256": sha256(_canonical(payload).encode()).hexdigest()})

    @classmethod
    def loads(cls, text: str) -> ComparisonBook:
        """Rebuild validated events; missing/corrupt/unknown versions fail."""
        try:
            outer = json.loads(text)
            if set(outer) != {"payload", "sha256"}:
                raise ValueError("invalid book envelope")
            p = outer["payload"]
            if sha256(_canonical(p).encode()).hexdigest() != outer["sha256"]:
                raise ValueError("book checksum mismatch")
            if set(p) != {"version", "policy", "instruments", "events"} or type(p["version"]) is not int or p["version"] != 1 or not isinstance(p["events"], list):
                raise ValueError("invalid schema/version")
            book = cls(BookPolicy(**p["policy"]), [Instrument(**x) for x in p["instruments"]])
            for event in p["events"]:
                if event.get("event_id") in book._receipts:
                    raise ValueError("duplicate persisted event")
                book.apply(event)
            return book
        except (TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
            raise ValueError("corrupt comparison book") from exc

    def save(self, path: Path) -> None:
        """Atomic single-writer research file save; no production defaults."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self.dumps())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @classmethod
    def load(cls, path: Path) -> ComparisonBook:
        """Load an explicit study file; no fallback to live financial state."""
        try:
            return cls.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise ValueError("missing/unreadable comparison book") from exc
