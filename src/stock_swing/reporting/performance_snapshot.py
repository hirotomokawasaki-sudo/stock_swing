"""Unified performance snapshot builder for reports and dashboards.

Consolidates broker positions, tracker summary, and derived metrics
to prevent drift between daily_report and dashboard_service.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.pnl_tracker import PnLTracker


@dataclass
class PerformanceSnapshot:
    """Unified snapshot of current trading performance."""

    # Account
    equity: float
    buying_power: float
    account_status: str
    baseline_equity: float
    
    # P&L
    cumulative_realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    
    # Performance summary
    closed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_return_per_trade: float | None
    avg_pnl_per_trade: float
    max_drawdown_pct: float
    trading_days: int
    
    # Positions
    open_positions: list[dict[str, Any]]
    positions_source: str
    current_prices: dict[str, float]
    
    # Recent activity
    recent_trades: list[dict[str, Any]]
    
    # Tracking context
    tracking_context: dict[str, Any]
    
    # Alerts
    alerts: list[dict[str, Any]]

    # R2-B: ETF vs Stock breakdown
    asset_class_breakdown: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


def build_snapshot(
    project_root: Path,
    recent_trade_limit: int = 5,
    alert_unrealized_threshold: float = -5000.0,
    alert_total_pnl_pct_threshold: float = -0.02,
) -> PerformanceSnapshot:
    """Build unified performance snapshot from broker and tracker.
    
    Args:
        project_root: Project root directory
        recent_trade_limit: Number of recent trades to include
        alert_unrealized_threshold: Unrealized P&L threshold for alert (negative USD)
        alert_total_pnl_pct_threshold: Total P&L percentage threshold for alert (negative ratio)
    
    Returns:
        PerformanceSnapshot with all current data
    """
    tracker = PnLTracker(project_root)
    tracker_open_positions = tracker.get_open_positions()

    # Fetch broker data
    equity = 100_000.0
    buying_power = 100_000.0
    account_status = "UNKNOWN"
    current_prices: dict[str, float] = {}
    open_positions: list[dict[str, Any]] = [dict(pos) for pos in tracker_open_positions]
    unrealized_pnl = 0.0
    positions_source = "tracker"

    try:
        broker = BrokerClient(
            api_key=os.environ["BROKER_API_KEY"],
            api_secret=os.environ["BROKER_API_SECRET"],
            paper_mode=True,
            base_url=os.environ["BROKER_BASE_URL"],
        )
        acct = broker.fetch_account().payload
        equity = float(acct.get("equity", equity))
        buying_power = float(acct.get("buying_power", buying_power))
        account_status = acct.get("status", "UNKNOWN")

        broker_positions = broker.fetch_positions().payload
        normalized_positions: list[dict[str, Any]] = []
        for pos in broker_positions or []:
            symbol = str(pos.get("symbol") or "").strip()
            if not symbol:
                continue
            qty = float(pos.get("qty") or 0.0)
            entry_price = float(pos.get("avg_entry_price") or 0.0)
            current_price = float(pos.get("current_price") or 0.0)
            position_unrealized = float(pos.get("unrealized_pl") or 0.0)
            current_prices[symbol] = current_price
            unrealized_pnl += position_unrealized
            normalized_positions.append(
                {
                    "symbol": symbol,
                    "qty": int(qty) if qty.is_integer() else qty,
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "unrealized_pnl": position_unrealized,
                    "unrealized_pnl_pct": float(pos.get("unrealized_plpc") or 0.0),
                    "side": pos.get("side") or "long",
                    "market_value": float(pos.get("market_value") or 0.0),
                    "cost_basis": float(pos.get("cost_basis") or 0.0),
                }
            )

        if normalized_positions:
            open_positions = normalized_positions
            positions_source = "broker"
        else:
            # Fallback to quote-based pricing
            for pos in open_positions:
                sym = pos.get("symbol")
                if not sym:
                    continue
                try:
                    q = broker.fetch_latest_quote(sym).payload
                    quote = q.get("quote", q)
                    bid = quote.get("bp", 0) or 0
                    ask = quote.get("ap", 0) or 0
                    if bid and ask:
                        current_prices[sym] = round((bid + ask) / 2, 4)
                except Exception:
                    pass

        # Record daily snapshot
        today_audit = project_root / "data" / "audits"
        today_audit.mkdir(parents=True, exist_ok=True)
        tracker.record_daily_snapshot(
            equity=equity,
            current_prices=current_prices,
        )
    except Exception:
        current_prices = {}

    # Reload tracker state after snapshot
    tracker.state = tracker._load_state()
    summary = tracker.get_summary()
    recent_trades = tracker.get_recent_trades(recent_trade_limit)

    # Fallback unrealized P&L calculation if broker unavailable
    if positions_source != "broker":
        unrealized_pnl = round(
            sum(
                (
                    (float(current_prices.get(pos.get("symbol"), 0.0)) - float(pos.get("entry_price") or 0.0))
                    * float(pos.get("qty") or 0.0)
                )
                for pos in open_positions
                if pos.get("symbol") in current_prices and float(pos.get("entry_price") or 0.0) > 0
            ),
            2,
        )

    cumulative_realized_pnl = float(summary.get("cumulative_realized_pnl") or 0.0)
    total_pnl = round(cumulative_realized_pnl + unrealized_pnl, 2)
    baseline_equity = float(summary.get("tracking_context", {}).get("baseline_equity") or 100_000.0)

    # Generate alerts
    alerts: list[dict[str, Any]] = []
    
    if unrealized_pnl < alert_unrealized_threshold:
        alerts.append({
            "level": "warning",
            "type": "unrealized_pnl",
            "message": f"含み損益が {unrealized_pnl:+,.2f} USD に達しています",
            "value": unrealized_pnl,
            "threshold": alert_unrealized_threshold,
        })
    
    total_pnl_pct = (total_pnl / baseline_equity) if baseline_equity > 0 else 0.0
    if total_pnl_pct < alert_total_pnl_pct_threshold:
        alerts.append({
            "level": "warning",
            "type": "total_pnl_pct",
            "message": f"合計損益が baseline から {total_pnl_pct:.2%} に達しています",
            "value": total_pnl_pct,
            "threshold": alert_total_pnl_pct_threshold,
        })

    # R2-B: ETF vs Stock breakdown
    asset_class_breakdown = tracker.get_asset_class_breakdown()

    return PerformanceSnapshot(
        equity=equity,
        buying_power=buying_power,
        account_status=account_status,
        baseline_equity=baseline_equity,
        cumulative_realized_pnl=cumulative_realized_pnl,
        unrealized_pnl=round(unrealized_pnl, 2),
        total_pnl=total_pnl,
        closed_trades=int(summary.get("closed_trades") or 0),
        winning_trades=int(summary.get("winning_trades") or 0),
        losing_trades=int(summary.get("losing_trades") or 0),
        win_rate=float(summary.get("win_rate") or 0.0),
        avg_return_per_trade=summary.get("avg_return_per_trade"),
        avg_pnl_per_trade=float(summary.get("avg_pnl_per_trade") or 0.0),
        max_drawdown_pct=float(summary.get("max_drawdown_pct") or 0.0),
        trading_days=int(summary.get("trading_days") or 0),
        open_positions=open_positions,
        positions_source=positions_source,
        current_prices=current_prices,
        recent_trades=recent_trades,
        tracking_context=dict(summary.get("tracking_context") or {}),
        alerts=alerts,
        asset_class_breakdown=asset_class_breakdown,
    )
