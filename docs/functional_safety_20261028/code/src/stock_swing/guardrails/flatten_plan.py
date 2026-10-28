from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FlattenOrderPlan:
    symbol: str
    quantity: int
    reason: str
    priority: int
    order_type: str = "market"


def build_flatten_plan(
    positions: list[dict[str, Any]],
    *,
    reason: str,
    max_orders: int = 5,
    only_losers: bool = False,
) -> list[FlattenOrderPlan]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for position in positions:
        qty = int(float(position.get("qty") or position.get("quantity") or 0))
        if qty <= 0:
            continue
        unrealized_pct = float(position.get("unrealized_pct") or 0)
        if only_losers and unrealized_pct >= 0:
            continue
        candidates.append((unrealized_pct, position))

    candidates.sort(key=lambda item: item[0])

    plans: list[FlattenOrderPlan] = []
    for priority, (_, position) in enumerate(candidates[:max_orders], start=1):
        plans.append(
            FlattenOrderPlan(
                symbol=str(position["symbol"]).upper(),
                quantity=int(float(position.get("qty") or position.get("quantity"))),
                reason=reason,
                priority=priority,
            )
        )
    return plans
