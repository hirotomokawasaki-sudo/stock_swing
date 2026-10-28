"""Draft run-local order preflight; not a durable or atomic order manager.

K01/K02, 2026-10-28, production base 8909e79. Values are planned quote
notionals, never a bound on market fills. Unknown snapshots block BUY only.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from stock_swing.risk.correlation_cluster import DEFAULT_CLUSTER_CAPS, get_cluster_for_symbol


def _number(value: Any, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean_number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid_number") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError("invalid_number_range")
    return result


def _symbol(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_symbol")
    return value.strip().upper()


def buy_conflicts(decisions: list[Any]) -> dict[str, dict[str, Any]]:
    """Draft veto only: preserve original intents; never select/net strategies."""
    groups: dict[str, list[Any]] = defaultdict(list)
    for decision in decisions:
        order = decision.proposed_order
        if order is not None:
            groups[_symbol(order.symbol)].append(decision)
    held: dict[str, dict[str, Any]] = {}
    for symbol, group in groups.items():
        buys = [d for d in group if d.proposed_order.side == "buy"]
        sells = [d for d in group if d.proposed_order.side == "sell"]
        if len(buys) > 1 or (buys and sells):
            for decision in buys:
                held[decision.decision_id] = {
                    "allowed": False,
                    "reason": "same_symbol_buy_sell_conflict" if sells else "same_symbol_duplicate_buy",
                    "symbol": symbol,
                    "related_decision_ids": [d.decision_id for d in group],
                }
    return held


class OrderPreflight:
    """A single qualified snapshot plus monotone in-run BUY reservations.

    File IO/config loading remains with existing callers. No state is persisted
    as authority, and no cancel/reject is trusted to release an attempted order.
    """

    def __init__(self, positions: Any, equity: Any, orders: Any, *,
                 complete: bool, price_lookup: Callable[[str], Any],
                 cluster_caps: dict[str, float] | None = None) -> None:
        self.available = False
        self.reason = "snapshot_unavailable"
        self.values: dict[str, Decimal] = {}
        self.pending_symbols: set[str] = set()
        self.reservations: dict[str, tuple[str, Decimal]] = {}
        self.equity = Decimal(0)
        self.caps = DEFAULT_CLUSTER_CAPS if cluster_caps is None else cluster_caps
        try:
            if complete is not True or not isinstance(positions, dict) or not isinstance(orders, list):
                raise ValueError("incomplete_or_invalid_snapshot")
            self.equity = _number(equity, positive=True)
            for name, cap in self.caps.items():
                if name not in DEFAULT_CLUSTER_CAPS or _number(cap) > 1:
                    raise ValueError("invalid_cluster_cap")
            for key, row in positions.items():
                symbol = _symbol(key)
                if not isinstance(row, dict) or _symbol(row.get("symbol", key)) != symbol or symbol in self.values:
                    raise ValueError("invalid_position")
                qty = _number(row.get("qty", row.get("quantity")))
                value = _number(row.get("market_value"))
                if qty > 0 and value == 0:
                    raise ValueError("unpriced_position")
                self.values[symbol] = value
            seen: set[str] = set()
            terminal = {"filled", "canceled", "expired", "rejected", "replaced"}
            active = {"new", "accepted", "pending_new", "partially_filled", "pending_cancel", "pending_replace", "accepted_for_bidding", "held", "done_for_day"}
            for row in orders:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in seen:
                    raise ValueError("invalid_or_duplicate_order_id")
                seen.add(row["id"])
                if row.get("status") in terminal:
                    continue
                if row.get("status") not in active or row.get("side") not in {"buy", "sell"}:
                    raise ValueError("unknown_order_state")
                if row.get("order_class") not in {None, "", "simple"} or row.get("legs") or row.get("notional") is not None:
                    raise ValueError("unsupported_order_shape")
                symbol = _symbol(row.get("symbol"))
                qty = _number(row.get("qty"), positive=True)
                filled = _number(row.get("filled_qty"))
                if qty != qty.to_integral_value() or filled != filled.to_integral_value() or filled > qty:
                    raise ValueError("invalid_order_quantity")
                remaining = qty - filled
                if remaining == 0:
                    # An active/fully-filled contradiction is not confirmed terminal.
                    raise ValueError("active_order_without_remaining")
                self.pending_symbols.add(symbol)
                if row["side"] == "sell":
                    continue  # Never credit pending SELL proceeds or capacity.
                if row.get("type") not in {"market", "limit"}:
                    raise ValueError("unsupported_buy_order_type")
                price = _number(price_lookup(symbol), positive=True)
                if row["type"] == "limit":
                    price = max(price, _number(row.get("limit_price"), positive=True))
                self.values[symbol] = self.values.get(symbol, Decimal(0)) + remaining * price
            self.available = True
            self.reason = "qualified_single_snapshot"
        except Exception as exc:
            self.reason = "snapshot_unavailable:" + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__)

    def projected_positions(self) -> dict[str, dict[str, float]]:
        values = dict(self.values)
        for symbol, amount in self.reservations.values():
            values[symbol] = values.get(symbol, Decimal(0)) + amount
        return {symbol: {"market_value": float(value)} for symbol, value in values.items()}

    def reserve(self, decision_id: str, symbol: str, qty: Any, price: Any,
                symbol_cap_pct: Any, allocator: Any = None) -> dict[str, Any]:
        """Atomically within this Python call, check and reserve planned notional."""
        result: dict[str, Any] = {"allowed": False, "decision_id": decision_id, "symbol": symbol}
        try:
            if not self.available:
                raise ValueError(self.reason)
            symbol = _symbol(symbol)
            if not isinstance(decision_id, str) or not decision_id or decision_id in self.reservations:
                raise ValueError("duplicate_or_invalid_decision_id")
            if symbol in self.pending_symbols:
                raise ValueError("same_symbol_open_order")
            shares = _number(qty, positive=True)
            if shares != shares.to_integral_value():
                raise ValueError("fractional_quantity_unsupported")
            amount = shares * _number(price, positive=True)
            cap_pct = _number(symbol_cap_pct)
            if cap_pct > 1:
                raise ValueError("invalid_symbol_cap")
            # Do not round inputs to cents or use an arbitrary tolerance.
            values = dict(self.values)
            for reserved_symbol, value in self.reservations.values():
                values[reserved_symbol] = values.get(reserved_symbol, Decimal(0)) + value
            result.update(planned_notional=str(amount), current_symbol_notional=str(values.get(symbol, Decimal(0))), symbol_cap=str(self.equity * cap_pct))
            if values.get(symbol, Decimal(0)) + amount > self.equity * cap_pct:
                raise ValueError("projected_symbol_cap_exceeded")
            for name in get_cluster_for_symbol(symbol):
                if name in self.caps:
                    projected = sum((v for s, v in values.items() if name in get_cluster_for_symbol(s)), Decimal(0)) + amount
                    if projected > self.equity * _number(self.caps[name]):
                        result.update(cluster=name, projected_cluster_notional=str(projected), cluster_cap=str(self.equity * _number(self.caps[name])))
                        raise ValueError("projected_cluster_cap_exceeded")
            if allocator is not None:
                band = allocator.check_projected_band(symbol, float(amount), self.projected_positions(), float(self.equity))
                if not band.allowed:
                    raise ValueError("projected_allocation_band:" + band.reason)
            self.reservations[decision_id] = (symbol, amount)
            result.update(allowed=True, reason="reserved_before_submit")
        except Exception as exc:
            result["reason"] = str(exc) if isinstance(exc, ValueError) else "preflight_unavailable:" + type(exc).__name__
        return result

    def observe_submission(self, decision_id: str, status: str) -> None:
        """Legacy 'rejected' may be a timeout; never release on that label."""
        if decision_id not in self.reservations or status != "submitted":
            self.available = False
            self.reason = "submission_outcome_unknown"


def snapshot_from_broker(broker: Any, positions: Any, equity: Any,
                         price_lookup: Callable[[str], Any], *,
                         cluster_caps: dict[str, float] | None = None) -> OrderPreflight:
    """Isolated current-adapter contract: short open-order page, not pagination.

    Adapter qualification is not portable by assumption. No completeness claim
    at the documented 500 cap, and no claim of snapshot atomicity/freshness.
    """
    try:
        payload = broker.fetch_orders(status="open", limit=500).payload
        complete = isinstance(payload, list) and len(payload) < 500
    except Exception:
        payload, complete = None, False
    return OrderPreflight(positions, equity, payload, complete=complete,
                          price_lookup=price_lookup, cluster_caps=cluster_caps)
