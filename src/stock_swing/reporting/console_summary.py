"""Structured console summary builder for paper_demo (P4-C)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ConsoleSummary:
    run_id: str
    timestamp: str
    equity: float
    open_position_count: int
    realized_pnl: float
    unrealized_pnl: float
    signals_total: int
    signals_buy: int
    signals_sell: int
    signals_deny: int
    orders_submitted: int
    orders_rejected: int
    cluster_blocks: list[str] = field(default_factory=list)
    risk_budget_pct: float = 0.0
    stale_symbols: list[str] = field(default_factory=list)
    price_sources: dict[str, int] = field(default_factory=dict)
    market_regime: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "equity": round(self.equity, 2),
            "open_position_count": self.open_position_count,
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "signals": {
                "total": self.signals_total,
                "buy": self.signals_buy,
                "sell": self.signals_sell,
                "deny": self.signals_deny,
            },
            "orders": {
                "submitted": self.orders_submitted,
                "rejected": self.orders_rejected,
            },
            "risk": {
                "cluster_blocks": self.cluster_blocks,
                "risk_budget_pct": round(self.risk_budget_pct, 3),
            },
            "data_quality": {
                "stale_symbols": self.stale_symbols,
                "price_sources": self.price_sources,
            },
            "market_regime": self.market_regime,
            "warnings": self.warnings,
        }

    def emit(self) -> None:
        """Print machine-readable block to stdout."""
        print("\nCONSOLE_SUMMARY_JSON " + json.dumps(self.to_dict(), ensure_ascii=False))

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        equity: float,
        open_position_count: int,
        realized_pnl: float = 0.0,
        unrealized_pnl: float = 0.0,
        decisions: list | None = None,
        submissions: list | None = None,
        cluster_blocks: list[str] | None = None,
        risk_budget_pct: float = 0.0,
        stale_symbols: list[str] | None = None,
        price_sources: dict[str, int] | None = None,
        market_regime: str = "unknown",
        warnings: list[str] | None = None,
    ) -> "ConsoleSummary":
        decisions = decisions or []
        submissions = submissions or []
        buy_dec = sum(1 for d in decisions if getattr(d, "action", "") == "buy")
        sell_dec = sum(1 for d in decisions if getattr(d, "action", "") == "sell")
        deny_dec = sum(1 for d in decisions if getattr(d, "action", "") == "deny")
        submitted = sum(1 for s in submissions if getattr(s, "status", "") == "submitted")
        rejected = sum(1 for s in submissions if getattr(s, "status", "") == "rejected")
        return cls(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            equity=equity,
            open_position_count=open_position_count,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            signals_total=len(decisions),
            signals_buy=buy_dec,
            signals_sell=sell_dec,
            signals_deny=deny_dec,
            orders_submitted=submitted,
            orders_rejected=rejected,
            cluster_blocks=cluster_blocks or [],
            risk_budget_pct=risk_budget_pct,
            stale_symbols=stale_symbols or [],
            price_sources=price_sources or {},
            market_regime=market_regime,
            warnings=warnings or [],
        )
