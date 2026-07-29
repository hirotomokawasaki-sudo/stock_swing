"""FIX-002: Allocation enforcement after sizing regression tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from stock_swing.decision_engine.decision_engine import ProposedOrder
from stock_swing.risk.portfolio_allocator import PortfolioAllocator


class _DecisionStub:
    def __init__(self, symbol: str, qty: int, *, price=None, asset_class: str = "stock"):
        self.proposed_order = ProposedOrder(
            symbol=symbol,
            side="buy",
            order_type="market",
            qty=qty,
            time_in_force="day",
            limit_price=price,
        )
        self.proposed_order.quantity = None
        self.proposed_order.price = price
        self.proposed_order.asset_class = asset_class


def _allocator(tmp_path) -> PortfolioAllocator:
    config = {
        "portfolio": {
            "allocation": {"stocks": 0.85, "ETFs": 0.15},
            "allocation_band": {"stocks_min": 0.70, "stocks_max": 0.85, "etfs_min": 0.08, "etfs_max": 0.20},
            "use_projected_allocation": True,
        }
    }
    config_path = tmp_path / "portfolio_allocation.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return PortfolioAllocator(Path(config_path), registry={})


def test_allocation_price_unavailable_blocks_buy(tmp_path):
    """When price is unavailable, pre-allocation filtering must block the buy."""
    allocator = _allocator(tmp_path)
    decision = _DecisionStub("TEST", 10, price=0.0)

    filtered = allocator.filter_decisions_by_allocation(
        decisions=[decision],
        current_positions={},
        account_equity=1_000_000.0,
    )

    assert filtered == []


def test_allocation_uses_qty_not_quantity_attribute(tmp_path):
    """Allocation should use ProposedOrder.qty when quantity is absent."""
    allocator = _allocator(tmp_path)
    decision = _DecisionStub("TEST", 100, price=850.0)

    filtered = allocator.filter_decisions_by_allocation(
        decisions=[decision],
        current_positions={},
        account_equity=1_000_000.0,
    )

    assert filtered == [decision]


def test_allocation_sequential_adds_block_at_cap(tmp_path):
    """Sequential BUYs should block once the projected stock band exceeds band_max."""
    allocator = _allocator(tmp_path)
    equity = 1_000_000.0
    current = {"AAPL": {"market_value": 840_000.0}}

    result1 = allocator.check_projected_band("MSFT", 10_000.0, current, equity)
    current2 = {
        "AAPL": {"market_value": 840_000.0},
        "MSFT": {"market_value": 10_000.0},
    }
    result2 = allocator.check_projected_band("GOOGL", 10_000.0, current2, equity)

    assert result1.allowed is True
    assert result2.allowed is False, "Should block when sequential adds exceed band_max"
