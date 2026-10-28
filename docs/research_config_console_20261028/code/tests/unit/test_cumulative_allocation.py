from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from stock_swing.decision_engine.decision_engine import DecisionRecord, PositionSizingSnapshot, ProposedOrder
from stock_swing.risk.portfolio_allocator import PortfolioAllocator


def _allocator(tmp_path: Path) -> PortfolioAllocator:
    config = {
        "portfolio": {
            "allocation": {"stocks": 0.85, "ETFs": 0.15},
            "allocation_band": {"stocks_min": 0.80, "stocks_max": 0.85, "etf_min": 0.08, "etf_max": 0.20},
            "use_projected_allocation": True,
        }
    }
    config_path = tmp_path / "portfolio_allocation.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    registry = {
        "AAPL": {"asset_class": "stock"},
        "MSFT": {"asset_class": "stock"},
    }
    return PortfolioAllocator(Path(config_path), registry=registry)


def _decision(symbol: str, qty: int, price: float) -> DecisionRecord:
    return DecisionRecord(
        decision_id=f"dec-{symbol.lower()}",
        schema_version="v1",
        generated_at=datetime.now(timezone.utc),
        mode="paper",
        strategy_id="breakout_momentum_v1",
        strategy_version_id="breakout_momentum_v1",
        symbol=symbol,
        action="buy",
        confidence=0.9,
        signal_strength=0.9,
        risk_state="pass",
        deny_reasons=[],
        requires_operator_approval=False,
        time_horizon="3d",
        evidence={},
        proposed_order=ProposedOrder(
            symbol=symbol,
            side="buy",
            order_type="market",
            qty=qty,
            time_in_force="day",
            limit_price=price,
        ),
        sizing=PositionSizingSnapshot(final_shares=qty, current_price=price),
    )


def test_sequential_buys_use_running_projection(tmp_path: Path) -> None:
    allocator = _allocator(tmp_path)
    current_positions = {"NVDA": {"market_value": 800_000.0}}
    decisions = [
        _decision("AAPL", qty=267, price=150.0),  # ~40k
        _decision("MSFT", qty=50, price=400.0),   # 20k
    ]

    filtered = allocator.filter_decisions_by_allocation(
        decisions=decisions,
        current_positions=current_positions,
        account_equity=1_000_000.0,
    )

    accepted = [row.proposed_order.symbol for row in filtered]
    assert accepted == ["AAPL"]


def test_rejected_first_order_does_not_pollute_second_projection(tmp_path: Path) -> None:
    allocator = _allocator(tmp_path)
    current_positions = {"NVDA": {"market_value": 910_000.0}}
    decisions = [
        _decision("AAPL", qty=100, price=150.0),
        _decision("MSFT", qty=50, price=300.0),
    ]

    filtered = allocator.filter_decisions_by_allocation(
        decisions=decisions,
        current_positions=current_positions,
        account_equity=1_000_000.0,
    )

    assert filtered == []
