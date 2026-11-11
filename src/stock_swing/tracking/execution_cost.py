"""Order-observation accounting; cumulative VWAP is not an incremental fill price.

No I/O or historical mutation. Values describe gross execution proceeds, not
fees or genuine individual broker executions. Cross-file atomicity is separate.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


class ExecutionCostError(ValueError):
    """Incomplete/conflicting economics must not be converted into a new fill."""


def decimal_value(value: Any, name: str, *, positive: bool = True) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ExecutionCostError(f"invalid {name}") from exc
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ExecutionCostError(f"invalid {name}")
    return number


def whole_quantity(value: Any, name: str, *, positive: bool = True) -> int:
    number = decimal_value(value, name, positive=positive)
    if number != number.to_integral_value():
        raise ExecutionCostError(f"fractional {name} unsupported by integer-share tracker")
    return int(number)


@dataclass(frozen=True)
class IncrementalFill:
    qty: int
    price: Decimal | None
    notional: Decimal
    prior_qty: int
    prior_notional: Decimal


def incremental_sell_fill(order: dict, trades: list[dict], *, consumed_qty: Any = 0) -> IncrementalFill:
    """Subtract already-recorded leg proceeds from a cumulative order snapshot.

    Quarantined legs still consume inventory but cannot be silently duplicated.
    A fill-ledger watermark ahead of the canonical trade ledger is unresolved,
    not permission to skip a missing financial transaction.
    """
    order_id, symbol = order.get('id'), order.get('symbol')
    if not order_id or not symbol or order.get('side') != 'sell':
        raise ExecutionCostError('missing/conflicting sell order identity')
    qty = whole_quantity(order.get('filled_qty'), 'filled quantity')
    price = decimal_value(order.get('filled_avg_price'), 'cumulative price')
    consumed = whole_quantity(consumed_qty, 'consumed quantity', positive=False)
    prior_qty, prior_notional, seen = 0, Decimal(0), set()
    for trade in trades:
        if trade.get('exit_broker_order_id') != order_id or trade.get('status') not in {'closed', 'quarantined'}:
            continue
        if trade.get('symbol') != symbol:
            raise ExecutionCostError('recorded leg symbol conflicts with order')
        key = (trade.get('broker_order_id'), trade.get('trade_id'), trade.get('execution_leg_id'),
               trade.get('exit_time'), trade.get('qty'), trade.get('exit_price'))
        if key in seen:
            raise ExecutionCostError('ambiguous duplicate recorded leg')
        seen.add(key)
        leg_qty = whole_quantity(trade.get('qty'), 'recorded leg quantity')
        prior_qty += leg_qty
        prior_notional += leg_qty * decimal_value(trade.get('exit_price'), 'recorded exit price')
    if qty < prior_qty or consumed > prior_qty:
        raise ExecutionCostError('quantity decrease or fill-ledger watermark ahead of recorded legs')
    notional = qty * price - prior_notional
    remaining = qty - prior_qty
    if not remaining:
        # Frozen order observations use six-decimal VWAP; do not create a zero-qty
        # execution to absorb a genuine same-quantity price correction.
        tolerance = max(Decimal('.01'), Decimal(qty) * Decimal('.0000005'))
        if abs(notional) > tolerance:
            raise ExecutionCostError('same-quantity notional revision requires explicit correction')
        return IncrementalFill(0, None, Decimal(0), prior_qty, prior_notional)
    if notional <= 0:
        raise ExecutionCostError('nonpositive incremental notional')
    return IncrementalFill(remaining, notional / remaining, notional, prior_qty, prior_notional)
