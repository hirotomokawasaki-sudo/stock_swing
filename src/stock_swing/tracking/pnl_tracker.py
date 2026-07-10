"""P&L tracker for paper trading performance measurement.

Tracks:
- Open positions (entries from paper orders)
- Closed trades (exits via sell orders or EOD reconciliation)
- Daily / cumulative P&L
- Win rate, average return, max drawdown

State is persisted to data/tracking/pnl_state.json
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_swing.tracking.trade_event_store import TradeEvent, TradeEventStore
from stock_swing.utils.strategy_versioning import normalize_strategy_id

logger = logging.getLogger(__name__)


@dataclass
class TradeEntry:
    """A single completed trade (round trip: buy → sell)."""
    trade_id: str
    symbol: str
    strategy_id: str
    side: str  # "buy" (long trade)
    qty: int
    entry_price: float
    exit_price: float | None
    entry_time: str  # ISO8601
    exit_time: str | None
    pnl: float | None  # realized P&L in USD
    return_pct: float | None  # return %
    status: str  # "open" | "closed" | "quarantined"
    peak_price: float | None = None
    entry_signal_strength: float | None = None  # 0.0–1.0; used for dynamic exit thresholds
    account_id: str | None = None  # Broker account ID
    strategy_version_id: str | None = None
    broker_order_id: str | None = None
    exit_broker_order_id: str | None = None
    original_strategy_id: str | None = None
    exit_strategy_id: str | None = None
    exit_reason: str | None = None
    asset_class: str | None = None  # "etf" | "stock" | None
    # F4: Durable decision metadata
    decision_id: str | None = None
    run_id: str | None = None
    experiment_id: str | None = None
    prompt_version: str | None = None
    config_hash: str | None = None
    # F1: Holding-period integrity
    holding_days: float | None = None  # computed from entry_time/exit_time; None if open
    quarantine_reason: str | None = None  # set when status="quarantined"


@dataclass
class DailySnapshot:
    """End-of-day performance snapshot."""
    date: str  # YYYY-MM-DD
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    signals_generated: int
    orders_submitted: int
    # Cumulative metrics up to and including this date
    cumulative_profit_factor: float | None = None
    cumulative_win_rate: float | None = None
    cumulative_closed_trades: int | None = None


@dataclass
class StrategyDailySnapshot:
    """End-of-day performance snapshot by strategy_version_id."""
    date: str  # YYYY-MM-DD
    strategy_version_id: str
    equity_index: float
    day_return_pct: float
    realized_pnl: float
    cumulative_realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    gross_exposure: float
    traded_notional: float
    trade_count: int
    win_count: int
    loss_count: int
    open_positions: int
    approximation: str = "normalized_strategy_sleeve"


@dataclass
class PnLState:
    """Full persistent P&L state."""
    created_at: str
    last_updated: str
    trades: list[dict[str, Any]] = field(default_factory=list)
    quarantined_trades: list[dict[str, Any]] = field(default_factory=list)  # F1: invalid holding-period trades
    daily_snapshots: list[dict[str, Any]] = field(default_factory=list)
    strategy_daily_snapshots: list[dict[str, Any]] = field(default_factory=list)
    cumulative_realized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    peak_equity: float = 100_000.0
    max_drawdown_pct: float = 0.0
    broker_account_id: str | None = None
    baseline_date: str | None = None
    baseline_equity: float | None = None
    tracking_label: str | None = None
    performance_scope: str = "current_account_since_baseline"
    archived_from_account_id: str | None = None
    archive_path: str | None = None
    migration_note_path: str | None = None


def _compute_holding_days(entry_time: str | None, exit_time: str | None) -> float | None:
    """Return calendar days between entry and exit; None if either is missing."""
    if not entry_time or not exit_time:
        return None
    try:
        et = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
        xt = datetime.fromisoformat(str(exit_time).replace("Z", "+00:00"))
        return round((xt - et).total_seconds() / 86400.0, 4)
    except (TypeError, ValueError):
        return None


def _compute_cumulative_pf_wr(
    trades: list[dict],
    as_of_date: str,
) -> tuple[float | None, float | None, int]:
    """Compute cumulative PF and WR for all closed trades up to as_of_date (YYYY-MM-DD).

    Returns:
        (profit_factor, win_rate, closed_count)
        profit_factor is None when there are no losing trades (infinite PF).
        win_rate is None when there are no closed trades.
    """
    closed = [
        t for t in trades
        if t.get("status") == "closed"
        and (t.get("exit_time") or "")[:10] <= as_of_date
        and t.get("pnl") is not None
    ]
    if not closed:
        return None, None, 0

    wins = [t for t in closed if (t.get("pnl") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl") or 0) < 0]
    gross_profit = sum(float(t["pnl"]) for t in wins)
    gross_loss = abs(sum(float(t["pnl"]) for t in losses))

    pf = round(gross_profit / gross_loss, 4) if gross_loss > 0 else None
    wr = round(len(wins) / len(closed), 4)
    return pf, wr, len(closed)


class PnLTracker:
    """Paper trading P&L tracker.

    Records entries/exits from paper executor submissions and
    computes performance metrics.
    """

    STATE_FILE = "data/tracking/pnl_state.json"

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.state_path = project_root / self.STATE_FILE
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_store = TradeEventStore(project_root)
        self.state = self._load_state()

    # ── Public API ────────────────────────────────────────────────────────────

    def record_submission(
        self,
        symbol: str,
        strategy_id: str,
        side: str,
        qty: int,
        price: float,
        broker_order_id: str | None,
        decision_id: str,
        original_strategy_id: str | None = None,
        strategy_version_id: str | None = None,
        account_id: str | None = None,
        signal_strength: float | None = None,
        asset_class: str | None = None,
        # F4: durable decision metadata
        run_id: str | None = None,
        experiment_id: str | None = None,
        prompt_version: str | None = None,
        config_hash: str | None = None,
    ) -> str:
        """Record a new buy submission as an open trade.

        Returns trade_id for buy entries.
        Non-buy submissions are ignored because exits must be recorded via
        ``record_exit`` after broker fill confirmation.

        Raises ValueError if price <= 0 (invalid entry price).
        """
        if side.lower() != "buy":
            logger.warning("Skipping non-buy submission in PnL tracker: %s %s qty=%s", side, symbol, qty)
            return ""

        if price <= 0:
            raise ValueError(f"Invalid entry price {price} for {symbol}. Cannot record submission.")
        
        trade_id = f"{symbol}-{decision_id[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        normalized_strategy_id = strategy_version_id or normalize_strategy_id(strategy_id, now)

        from stock_swing.risk.position_sizing import classify_asset_class
        resolved_asset_class = classify_asset_class(symbol, asset_class)

        trade = TradeEntry(
            trade_id=trade_id,
            symbol=symbol,
            strategy_id=normalized_strategy_id,
            strategy_version_id=normalized_strategy_id,
            side=side,
            qty=qty,
            entry_price=price,
            exit_price=None,
            entry_time=now,
            exit_time=None,
            pnl=None,
            return_pct=None,
            peak_price=price,
            entry_signal_strength=round(float(signal_strength), 4) if signal_strength is not None else None,
            status="open",
            account_id=account_id,
            broker_order_id=broker_order_id,
            original_strategy_id=original_strategy_id or strategy_id,
            asset_class=resolved_asset_class,
            # F4: durable decision metadata
            decision_id=decision_id,
            run_id=run_id,
            experiment_id=experiment_id,
            prompt_version=prompt_version,
            config_hash=config_hash,
        )
        self.state.trades.append(asdict(trade))
        self.state.total_trades += 1
        self.state.last_updated = now
        self._save_state()
        self.event_store.append(TradeEvent.create(
            "trade_opened",
            symbol=symbol,
            trade_id=trade_id,
            broker_order_id=broker_order_id,
            payload={"entry_price": price, "qty": qty, "strategy_id": strategy_id},
        ))
        return trade_id

    def record_exit(
        self,
        symbol: str,
        exit_price: float,
        exit_qty: int | None = None,
        broker_order_id: str | None = None,
        exit_strategy_id: str | None = None,
        exit_reason: str | None = None,
    ) -> TradeEntry | None:
        """Mark open trades for a symbol as closed (supports partial fills).
        
        Args:
            symbol: Symbol to exit
            exit_price: Exit price
            exit_qty: Quantity to exit (None = close all open positions)
            broker_order_id: Broker order ID for tracking
            
        Returns:
            The closed trade (or last partially closed trade if multiple)
        """
        now = datetime.now(timezone.utc).isoformat()

        # Find all open trades for symbol (FIFO order)
        open_trades = [
            t for t in self.state.trades
            if t["symbol"] == symbol and t["status"] == "open"
        ]
        if not open_trades:
            return None

        # If no exit_qty specified, close all open positions
        if exit_qty is None:
            total_open_qty = sum(t["qty"] for t in open_trades)
            exit_qty = total_open_qty
        
        remaining_to_exit = exit_qty
        closed_trade = None
        
        # Close trades in FIFO order
        for trade_dict in open_trades:
            if remaining_to_exit <= 0:
                break
            
            entry_price = trade_dict["entry_price"]
            trade_qty = trade_dict["qty"]
            
            if remaining_to_exit >= trade_qty:
                # Close this trade completely
                qty_to_close = trade_qty
                trade_dict["status"] = "closed"
                remaining_to_exit -= trade_qty
            else:
                # Partial close: reduce qty, keep trade open
                qty_to_close = remaining_to_exit
                trade_dict["qty"] -= remaining_to_exit
                # Create a new closed trade for the exited portion
                closed_portion = dict(trade_dict)
                closed_portion["qty"] = qty_to_close
                closed_portion["exit_price"] = exit_price
                closed_portion["exit_time"] = now
                
                pnl = (exit_price - entry_price) * qty_to_close
                return_pct = (exit_price - entry_price) / entry_price if entry_price else 0.0
                closed_portion["pnl"] = round(pnl, 2)
                closed_portion["return_pct"] = round(return_pct, 4)
                if broker_order_id:
                    closed_portion["exit_broker_order_id"] = broker_order_id
                if exit_strategy_id:
                    closed_portion["exit_strategy_id"] = exit_strategy_id
                if exit_reason:
                    closed_portion["exit_reason"] = exit_reason

                # F1: Validate holding period; quarantine if entry_time > exit_time
                hd = _compute_holding_days(closed_portion.get("entry_time"), now)
                closed_portion["holding_days"] = hd
                if hd is not None and hd < 0:
                    closed_portion["status"] = "quarantined"
                    closed_portion["quarantine_reason"] = (
                        f"negative_holding_days: entry_time={closed_portion.get('entry_time')} "
                        f"exit_time={now} holding_days={hd:.4f}"
                    )
                    self.state.quarantined_trades.append(closed_portion)
                    logger.warning(
                        "F1: quarantined partial trade %s %s holding_days=%.4f",
                        closed_portion.get("symbol"), closed_portion.get("trade_id"), hd,
                    )
                    closed_trade = TradeEntry(**closed_portion)
                    remaining_to_exit = 0
                    continue
                else:
                    closed_portion["status"] = "closed"
                
                # Add closed portion as new trade
                self.state.trades.append(closed_portion)
                self.state.cumulative_realized_pnl += pnl
                if pnl >= 0:
                    self.state.winning_trades += 1
                else:
                    self.state.losing_trades += 1
                
                closed_trade = TradeEntry(**closed_portion)
                remaining_to_exit = 0
                continue
            
            # Full close of this trade
            pnl = (exit_price - entry_price) * qty_to_close
            return_pct = (exit_price - entry_price) / entry_price if entry_price else 0.0

            # F1: Validate holding period; quarantine if entry_time > exit_time
            hd = _compute_holding_days(trade_dict.get("entry_time"), now)
            if hd is not None and hd < 0:
                # Quarantine this trade instead of closing it normally
                quarantine_dict = dict(trade_dict)
                quarantine_dict.update({
                    "exit_price": exit_price,
                    "exit_time": now,
                    "pnl": round(pnl, 2),
                    "return_pct": round(return_pct, 4),
                    "status": "quarantined",
                    "holding_days": hd,
                    "quarantine_reason": (
                        f"negative_holding_days: entry_time={trade_dict.get('entry_time')} "
                        f"exit_time={now} holding_days={hd:.4f}"
                    ),
                })
                if broker_order_id:
                    quarantine_dict["exit_broker_order_id"] = broker_order_id
                if exit_strategy_id:
                    quarantine_dict["exit_strategy_id"] = exit_strategy_id
                if exit_reason:
                    quarantine_dict["exit_reason"] = exit_reason
                trade_dict["status"] = "quarantined"  # mark in trades list too
                self.state.quarantined_trades.append(quarantine_dict)
                logger.warning(
                    "F1: quarantined trade %s %s holding_days=%.4f",
                    trade_dict.get("symbol"), trade_dict.get("trade_id"), hd,
                )
                closed_trade = TradeEntry(**quarantine_dict)
                continue

            trade_dict.update({
                "exit_price": exit_price,
                "exit_time": now,
                "pnl": round(pnl, 2),
                "return_pct": round(return_pct, 4),
                "status": "closed",
                "holding_days": hd,
            })
            if broker_order_id:
                trade_dict["exit_broker_order_id"] = broker_order_id
            if exit_strategy_id:
                trade_dict["exit_strategy_id"] = exit_strategy_id
            if exit_reason:
                trade_dict["exit_reason"] = exit_reason

            self.state.cumulative_realized_pnl += pnl
            if pnl >= 0:
                self.state.winning_trades += 1
            else:
                self.state.losing_trades += 1
            
            closed_trade = TradeEntry(**trade_dict)

        self.state.last_updated = now
        self._save_state()
        if closed_trade:
            self.event_store.append(TradeEvent.create(
                "trade_closed",
                symbol=symbol,
                trade_id=closed_trade.trade_id,
                broker_order_id=broker_order_id,
                payload={
                    "exit_price": exit_price,
                    "exit_qty": exit_qty,
                    "exit_reason": exit_reason,
                    "pnl": closed_trade.pnl,
                },
            ))
        return closed_trade

    def record_daily_snapshot(
        self,
        equity: float,
        signals_generated: int = 0,
        orders_submitted: int = 0,
        current_prices: dict[str, float] | None = None,
    ) -> DailySnapshot:
        """Record end-of-day snapshot."""
        today = datetime.now(timezone.utc).date().isoformat()
        current_prices = current_prices or {}

        # Today's closed trades
        today_closed = [
            t for t in self.state.trades
            if t["status"] == "closed" and (t.get("exit_time") or "")[:10] == today
        ]
        realized_pnl = sum(t.get("pnl", 0) or 0 for t in today_closed)
        win_count = sum(1 for t in today_closed if (t.get("pnl") or 0) >= 0)
        loss_count = len(today_closed) - win_count

        # Unrealized P&L from open positions
        open_trades = [t for t in self.state.trades if t["status"] == "open"]
        unrealized_pnl = 0.0
        for t in open_trades:
            curr = current_prices.get(t["symbol"])
            if curr:
                unrealized_pnl += (curr - t["entry_price"]) * t["qty"]

        # Max drawdown update
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity
        if self.state.peak_equity > 0:
            dd = (self.state.peak_equity - equity) / self.state.peak_equity
            if dd > self.state.max_drawdown_pct:
                self.state.max_drawdown_pct = round(dd, 4)

        # Cumulative PF / WR — all closed trades up to and including today
        cum_pf, cum_wr, cum_closed = _compute_cumulative_pf_wr(
            self.state.trades, as_of_date=today
        )

        snap = DailySnapshot(
            date=today,
            equity=equity,
            realized_pnl=round(realized_pnl, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
            total_pnl=round(realized_pnl + unrealized_pnl, 2),
            trade_count=len(today_closed),
            win_count=win_count,
            loss_count=loss_count,
            signals_generated=signals_generated,
            orders_submitted=orders_submitted,
            cumulative_profit_factor=cum_pf,
            cumulative_win_rate=cum_wr,
            cumulative_closed_trades=cum_closed,
        )
        self.state.daily_snapshots.append(asdict(snap))
        self._record_strategy_daily_snapshots(today=today, current_prices=current_prices)
        self.state.last_updated = datetime.now(timezone.utc).isoformat()
        self._save_state()
        return snap

    def get_summary(self) -> dict[str, Any]:
        """Return overall performance summary."""
        closed = [t for t in self.state.trades if t["status"] == "closed"]
        open_trades = [t for t in self.state.trades if t["status"] == "open"]
        removed_trades = [t for t in self.state.trades if t["status"] == "reconciled_removed"]
        wins = [t for t in closed if (t.get("pnl") or 0) > 0]
        losses = [t for t in closed if (t.get("pnl") or 0) < 0]
        flat = [t for t in closed if (t.get("pnl") or 0) == 0]
        closed_with_valid_return = [t for t in closed if (t.get("entry_price") or 0) > 0 and t.get("return_pct") is not None]

        win_rate = len(wins) / len(closed) if closed else 0.0
        avg_return = (
            sum(t.get("return_pct", 0) or 0 for t in closed_with_valid_return) / len(closed_with_valid_return)
            if closed_with_valid_return else None
        )
        avg_pnl = (
            sum(t.get("pnl", 0) or 0 for t in closed) / len(closed)
            if closed else 0.0
        )

        trading_day_count = len({str((snap.get("date") or "")).strip() for snap in self.state.daily_snapshots if str((snap.get("date") or "")).strip()})

        return {
            "total_trades": len(closed) + len(open_trades),
            "all_trade_records": self.state.total_trades,
            "closed_trades": len(closed),
            "open_trades": len(open_trades),
            "reconciled_removed_trades": len(removed_trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "flat_trades": len(flat),
            "win_rate": round(win_rate, 4),
            "cumulative_realized_pnl": round(self.state.cumulative_realized_pnl, 2),
            "avg_return_per_trade": round(avg_return, 4) if avg_return is not None else None,
            "avg_pnl_per_trade": round(avg_pnl, 2),
            "valid_return_trade_count": len(closed_with_valid_return),
            "max_drawdown_pct": self.state.max_drawdown_pct,
            "peak_equity": self.state.peak_equity,
            "trading_days": trading_day_count,
            "tracking_context": {
                "broker_account_id": self.state.broker_account_id,
                "baseline_date": self.state.baseline_date,
                "baseline_equity": self.state.baseline_equity,
                "tracking_label": self.state.tracking_label,
                "performance_scope": self.state.performance_scope,
                "archived_from_account_id": self.state.archived_from_account_id,
                "archive_path": self.state.archive_path,
                "migration_note_path": self.state.migration_note_path,
            },
        }

    def get_asset_class_breakdown(self) -> dict[str, dict[str, Any]]:
        """Return ETF vs Stock performance breakdown.

        Returns a dict with keys 'etf', 'stock', 'all', each containing:
          count, wins, losses, win_rate, profit_factor (None=inf),
          net_pnl, gross_profit, gross_loss.
        """
        from stock_swing.risk.position_sizing import classify_asset_class

        closed = [t for t in self.state.trades if t["status"] == "closed"]

        def _metrics(trades: list) -> dict[str, Any]:
            wins = [t for t in trades if (t.get("pnl") or 0) > 0]
            losses = [t for t in trades if (t.get("pnl") or 0) < 0]
            gross_profit = sum(t["pnl"] for t in wins)
            gross_loss = abs(sum(t["pnl"] for t in losses))
            pf: float | None
            if gross_loss > 0:
                pf = round(gross_profit / gross_loss, 3)
            elif gross_profit > 0:
                pf = None  # infinity
            else:
                pf = 0.0
            net_pnl = sum(t.get("pnl") or 0 for t in trades)
            win_rate = len(wins) / len(trades) if trades else 0.0
            return {
                "count": len(trades),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(win_rate, 4),
                "profit_factor": pf,
                "net_pnl": round(net_pnl, 2),
                "gross_profit": round(gross_profit, 2),
                "gross_loss": round(gross_loss, 2),
            }

        etf_trades: list = []
        stock_trades: list = []
        for t in closed:
            ac = t.get("asset_class") or classify_asset_class(t.get("symbol") or "")
            if ac == "etf":
                etf_trades.append(t)
            else:
                stock_trades.append(t)

        return {
            "etf": _metrics(etf_trades),
            "stock": _metrics(stock_trades),
            "all": _metrics(closed),
        }

    def get_exit_attribution_breakdown(self) -> dict[str, Any]:
        """Return performance grouped by exit reason.

        Returns:
          {
            "by_reason": {
              "trailing_stop": {count, wins, losses, win_rate, profit_factor, net_pnl, ...},
              ...
            },
            "unknown_count": int,
          }
        """
        closed = [t for t in self.state.trades if t["status"] == "closed"]

        def _metrics(trades: list) -> dict[str, Any]:
            wins = [t for t in trades if (t.get("pnl") or 0) > 0]
            losses = [t for t in trades if (t.get("pnl") or 0) < 0]
            gross_profit = sum(t.get("pnl") or 0 for t in wins)
            gross_loss = abs(sum(t.get("pnl") or 0 for t in losses))
            if gross_loss > 0:
                pf: float | None = round(gross_profit / gross_loss, 3)
            elif gross_profit > 0:
                pf = None
            else:
                pf = 0.0
            net_pnl = sum(t.get("pnl") or 0 for t in trades)
            win_rate = len(wins) / len(trades) if trades else 0.0
            return {
                "count": len(trades),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(win_rate, 4),
                "profit_factor": pf,
                "net_pnl": round(net_pnl, 2),
                "gross_profit": round(gross_profit, 2),
                "gross_loss": round(gross_loss, 2),
            }

        grouped: dict[str, list] = {}
        unknown_count = 0
        for trade in closed:
            reason = str(trade.get("exit_reason") or "unknown")
            if reason in {"", "None"}:
                reason = "unknown"
            if reason in {"unknown", "broker_fill", "broker_fill_unknown"}:
                unknown_count += 1
            grouped.setdefault(reason, []).append(trade)

        return {
            "by_reason": {
                reason: _metrics(trades)
                for reason, trades in sorted(
                    grouped.items(),
                    key=lambda item: sum(t.get("pnl") or 0 for t in item[1]),
                    reverse=True,
                )
            },
            "unknown_count": unknown_count,
        }

    def get_summary_by_account(self, account_id: str | None = None) -> dict[str, Any]:
        """Return performance summary for a specific account.
        
        If account_id is None, returns combined summary across all accounts.
        """
        if account_id is None:
            return self.get_summary()
        
        account_trades = [t for t in self.state.trades if t.get("account_id") == account_id]
        closed = [t for t in account_trades if t["status"] == "closed"]
        open_trades = [t for t in account_trades if t["status"] == "open"]
        removed_trades = [t for t in account_trades if t["status"] == "reconciled_removed"]
        wins = [t for t in closed if (t.get("pnl") or 0) > 0]
        losses = [t for t in closed if (t.get("pnl") or 0) < 0]
        flat = [t for t in closed if (t.get("pnl") or 0) == 0]
        closed_with_valid_return = [t for t in closed if (t.get("entry_price") or 0) > 0 and t.get("return_pct") is not None]

        win_rate = len(wins) / len(closed) if closed else 0.0
        avg_return = (
            sum(t.get("return_pct", 0) or 0 for t in closed_with_valid_return) / len(closed_with_valid_return)
            if closed_with_valid_return else None
        )
        avg_pnl = (
            sum(t.get("pnl", 0) or 0 for t in closed) / len(closed)
            if closed else 0.0
        )
        cumulative_realized_pnl = sum(t.get("pnl", 0) or 0 for t in closed)

        # Max drawdown for this account (simplified)
        max_dd = 0.0
        peak = 100_000.0
        running = 100_000.0
        for t in sorted(closed, key=lambda x: x.get("exit_time") or ""):
            running += t.get("pnl", 0) or 0
            if running > peak:
                peak = running
            if peak > 0:
                dd = (peak - running) / peak
                if dd > max_dd:
                    max_dd = dd

        return {
            "account_id": account_id,
            "total_trades": len(closed) + len(open_trades),
            "closed_trades": len(closed),
            "open_trades": len(open_trades),
            "reconciled_removed_trades": len(removed_trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "flat_trades": len(flat),
            "win_rate": round(win_rate, 4),
            "cumulative_realized_pnl": round(cumulative_realized_pnl, 2),
            "avg_return_per_trade": round(avg_return, 4) if avg_return is not None else None,
            "avg_pnl_per_trade": round(avg_pnl, 2),
            "valid_return_trade_count": len(closed_with_valid_return),
            "max_drawdown_pct": round(max_dd, 4),
        }

    def list_accounts(self) -> list[str]:
        """Return list of unique account IDs in trades."""
        accounts = set()
        for t in self.state.trades:
            acc_id = t.get("account_id")
            if acc_id:
                accounts.add(acc_id)
        return sorted(accounts)

    def get_open_positions(self) -> list[dict[str, Any]]:
        return [t for t in self.state.trades if t["status"] == "open"]

    def get_clean_closed_trades(self) -> list[dict[str, Any]]:
        """F1: Return closed trades with valid holding period (holding_days >= 0 or None)."""
        return [
            t for t in self.state.trades
            if t.get("status") == "closed"
            and (t.get("holding_days") is None or float(t.get("holding_days") or 0) >= 0)
        ]

    def get_quarantined_trades(self) -> list[dict[str, Any]]:
        """F1: Return quarantined trades (negative holding_days / invalid reconstruction).

        Primary source: state.quarantined_trades (atomically written).
        Legacy migration: also picks up status=quarantined in state.trades that
        are NOT already in state.quarantined_trades (identified by trade_id).
        """
        primary_ids = {t.get("trade_id") for t in self.state.quarantined_trades}
        legacy = [
            t for t in self.state.trades
            if t.get("status") == "quarantined" and t.get("trade_id") not in primary_ids
        ]
        return list(self.state.quarantined_trades) + legacy

    def get_ledger_quality_report(self) -> dict[str, Any]:
        """F1: Return data-quality summary for the closed-trade ledger."""
        closed = [t for t in self.state.trades if t.get("status") == "closed"]
        quarantined = self.get_quarantined_trades()
        neg_hd = [
            t for t in closed
            if t.get("holding_days") is not None and float(t.get("holding_days") or 0) < 0
        ]
        no_exit_reason = [
            t for t in closed
            if t.get("exit_reason") in (None, "", "broker_fill", "broker_fill_unknown")
        ]
        no_metadata = [
            t for t in closed
            if not t.get("decision_id") and not t.get("run_id")
        ]
        return {
            "clean_closed": len(closed) - len(neg_hd),
            "quarantined": len(quarantined),
            "negative_holding_days_in_clean": len(neg_hd),
            "no_exit_attribution": len(no_exit_reason),
            "no_metadata": len(no_metadata),
            "total_closed": len(closed),
            "attribution_coverage_pct": (
                round((len(closed) - len(no_exit_reason)) / len(closed) * 100, 1)
                if closed else None
            ),
        }

    def update_open_trade_peaks(self, current_prices: dict[str, float]) -> int:
        """Update persisted peak_price for open trades using latest market prices.

        Anomaly guard: if the incoming price is more than 3x the entry_price
        (or more than 3x the stored peak), the value is likely a data artifact
        from a split-event feed glitch and is skipped rather than written.
        This prevents a single bad data point from permanently poisoning
        peak_price and triggering an immediate trailing-stop exit.
        """
        if not current_prices:
            return 0

        updates = 0
        skipped_anomalies = 0
        for trade in self.get_open_positions():
            symbol = str(trade.get("symbol") or "")
            if not symbol or symbol not in current_prices:
                continue

            try:
                current_price = float(current_prices[symbol])
                if current_price <= 0:
                    continue
                entry_price = float(trade.get("entry_price") or 0)
                stored_peak = trade.get("peak_price")
                peak_price = float(stored_peak) if stored_peak is not None else entry_price
            except (TypeError, ValueError):
                continue

            new_peak = max(peak_price, current_price)

            # --- Anomaly guard ---
            # A price > 2x entry AND > 2x stored peak almost certainly indicates
            # a split-related feed error (e.g. Alpaca paper returning 10x price).
            # Skip the update rather than locking in an impossible peak.
            reference = max(entry_price, peak_price) if entry_price > 0 else peak_price
            if reference > 0 and new_peak > reference * 2.5:
                import logging
                logging.getLogger(__name__).warning(
                    f"update_open_trade_peaks: SKIPPED anomalous price for {symbol}: "
                    f"new_peak=${new_peak:.2f} vs reference=${reference:.2f} "
                    f"(entry=${entry_price:.2f}, stored_peak=${peak_price:.2f}) — "
                    f"likely split-feed glitch, not persisted"
                )
                skipped_anomalies += 1
                continue

            if stored_peak is None or abs(new_peak - peak_price) > 1e-9:
                trade["peak_price"] = new_peak
                updates += 1

        if updates:
            self.state.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_state()
        return updates

    def get_open_position_context_by_symbol(self) -> dict[str, dict[str, Any]]:
        """Return symbol-level exit context derived from open tracker trades."""
        grouped: dict[str, dict[str, Any]] = {}

        for trade in self.get_open_positions():
            symbol = str(trade.get("symbol") or "")
            if not symbol:
                continue

            entry_time = trade.get("entry_time")
            try:
                peak_price = float(trade.get("peak_price") or trade.get("entry_price") or 0)
            except (TypeError, ValueError):
                peak_price = 0.0

            row = grouped.setdefault(symbol, {
                "created_at": None,
                "peak_price": None,
                "entry_signal_strength": None,
            })

            if entry_time:
                existing = row.get("created_at")
                if existing is None:
                    row["created_at"] = entry_time
                else:
                    try:
                        existing_dt = datetime.fromisoformat(str(existing).replace("Z", "+00:00"))
                        entry_dt = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
                        if entry_dt < existing_dt:
                            row["created_at"] = entry_time
                    except (TypeError, ValueError):
                        if str(entry_time) < str(existing):
                            row["created_at"] = entry_time

            existing_peak = row.get("peak_price")
            if existing_peak is None or peak_price > float(existing_peak):
                row["peak_price"] = peak_price

            # Aggregate entry_signal_strength: use max across lots (most bullish conviction)
            ess = trade.get("entry_signal_strength")
            if ess is not None:
                try:
                    ess_f = float(ess)
                    existing_ess = row.get("entry_signal_strength")
                    if existing_ess is None or ess_f > float(existing_ess):
                        row["entry_signal_strength"] = ess_f
                except (TypeError, ValueError):
                    pass

        return grouped

    def get_recent_trades(self, n: int = 10) -> list[dict[str, Any]]:
        closed = [t for t in self.state.trades if t["status"] == "closed"]
        closed.sort(key=lambda t: t.get("exit_time") or t.get("entry_time") or "")
        return closed[-n:]

    def _record_strategy_daily_snapshots(self, today: str, current_prices: dict[str, float]) -> None:
        """Upsert strategy-level end-of-day snapshots for the current day."""
        current_prices = current_prices or {}

        closed_by_strategy: dict[str, dict[str, float | int]] = defaultdict(lambda: {
            "realized_pnl": 0.0,
            "traded_notional": 0.0,
            "trade_count": 0,
            "win_count": 0,
            "loss_count": 0,
        })
        cumulative_realized_by_strategy: dict[str, float] = defaultdict(float)
        open_by_strategy: dict[str, dict[str, float | int]] = defaultdict(lambda: {
            "unrealized_pnl": 0.0,
            "gross_exposure": 0.0,
            "open_positions": 0,
        })

        for trade in self.state.trades:
            strategy_id = str(trade.get("strategy_version_id") or trade.get("strategy_id") or "unknown")
            if trade.get("status") == "closed":
                pnl = float(trade.get("pnl") or 0.0)
                cumulative_realized_by_strategy[strategy_id] += pnl
                exit_time = str(trade.get("exit_time") or "")
                if exit_time[:10] == today:
                    row = closed_by_strategy[strategy_id]
                    row["realized_pnl"] += pnl
                    row["traded_notional"] += abs(float(trade.get("entry_price") or 0.0) * float(trade.get("qty") or 0.0))
                    row["trade_count"] += 1
                    if pnl > 0:
                        row["win_count"] += 1
                    elif pnl < 0:
                        row["loss_count"] += 1
            elif trade.get("status") == "open":
                curr = current_prices.get(str(trade.get("symbol") or ""))
                qty = float(trade.get("qty") or 0.0)
                entry_price = float(trade.get("entry_price") or 0.0)
                market_price = float(curr if curr is not None else entry_price)
                row = open_by_strategy[strategy_id]
                row["gross_exposure"] += market_price * qty
                row["open_positions"] += 1
                if curr is not None:
                    row["unrealized_pnl"] += (market_price - entry_price) * qty

        latest_prior_by_strategy: dict[str, dict[str, Any]] = {}
        for row in self.state.strategy_daily_snapshots:
            if str(row.get("date") or "") == today:
                continue
            strategy_id = str(row.get("strategy_version_id") or "unknown")
            prev = latest_prior_by_strategy.get(strategy_id)
            if prev is None or str(row.get("date") or "") > str(prev.get("date") or ""):
                latest_prior_by_strategy[strategy_id] = row

        new_rows: list[dict[str, Any]] = []
        all_strategy_ids = set(cumulative_realized_by_strategy) | set(closed_by_strategy) | set(open_by_strategy)
        for strategy_id in sorted(all_strategy_ids):
            prev = latest_prior_by_strategy.get(strategy_id)
            realized = float((closed_by_strategy.get(strategy_id) or {}).get("realized_pnl") or 0.0)
            cumulative_realized = float(cumulative_realized_by_strategy.get(strategy_id) or 0.0)
            unrealized = float((open_by_strategy.get(strategy_id) or {}).get("unrealized_pnl") or 0.0)
            gross_exposure = float((open_by_strategy.get(strategy_id) or {}).get("gross_exposure") or 0.0)
            traded_notional = float((closed_by_strategy.get(strategy_id) or {}).get("traded_notional") or 0.0)
            prev_unrealized = float((prev or {}).get("unrealized_pnl") or 0.0)
            prev_gross = float((prev or {}).get("gross_exposure") or 0.0)
            prev_equity_index = float((prev or {}).get("equity_index") or 100.0)

            day_pnl = realized + (unrealized - prev_unrealized)
            capital_base = max(traded_notional, gross_exposure, prev_gross, 1.0)
            day_return_pct = round(day_pnl / capital_base, 6)
            equity_index = round(prev_equity_index * (1.0 + day_return_pct), 6)

            row = StrategyDailySnapshot(
                date=today,
                strategy_version_id=strategy_id,
                equity_index=equity_index,
                day_return_pct=day_return_pct,
                realized_pnl=round(realized, 2),
                cumulative_realized_pnl=round(cumulative_realized, 2),
                unrealized_pnl=round(unrealized, 2),
                total_pnl=round(cumulative_realized + unrealized, 2),
                gross_exposure=round(gross_exposure, 2),
                traded_notional=round(traded_notional, 2),
                trade_count=int((closed_by_strategy.get(strategy_id) or {}).get("trade_count") or 0),
                win_count=int((closed_by_strategy.get(strategy_id) or {}).get("win_count") or 0),
                loss_count=int((closed_by_strategy.get(strategy_id) or {}).get("loss_count") or 0),
                open_positions=int((open_by_strategy.get(strategy_id) or {}).get("open_positions") or 0),
            )
            new_rows.append(asdict(row))

        self.state.strategy_daily_snapshots = [
            row for row in self.state.strategy_daily_snapshots if str(row.get("date") or "") != today
        ] + new_rows

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_state(self) -> PnLState:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                
                # FIX: Map closed_trades to trades if trades is empty (for restored data)
                if "closed_trades" in data and not data.get("trades"):
                    data["trades"] = data["closed_trades"]
                    logger.info(f"Mapped {len(data['trades'])} closed_trades to trades field")
                
                # Remove closed_trades key (not part of PnLState dataclass)
                data.pop("closed_trades", None)

                # F1: Ensure quarantined_trades exists in older state files
                if "quarantined_trades" not in data:
                    data["quarantined_trades"] = []
                
                # Ensure required fields exist
                if "created_at" not in data:
                    data["created_at"] = data.get("last_updated", datetime.now(timezone.utc).isoformat())

                default_account_id = os.environ.get("BROKER_ACCOUNT_ID", "legacy_account")
                if "broker_account_id" not in data:
                    data["broker_account_id"] = default_account_id
                if "baseline_date" not in data:
                    data["baseline_date"] = str(data.get("created_at") or "")[:10] or None
                if "baseline_equity" not in data:
                    data["baseline_equity"] = data.get("peak_equity", 100_000.0)
                if "tracking_label" not in data:
                    baseline_date = data.get("baseline_date") or str(data.get("created_at") or "")[:10]
                    data["tracking_label"] = f"alpaca_account_epoch_{baseline_date}" if baseline_date else None
                if "performance_scope" not in data:
                    data["performance_scope"] = "current_account_since_baseline"
                if "archived_from_account_id" not in data:
                    data["archived_from_account_id"] = None
                if "archive_path" not in data:
                    data["archive_path"] = None
                if "migration_note_path" not in data:
                    data["migration_note_path"] = None

                # Migration: Add account_id to existing trades if missing
                migrated_count = 0
                for trade in data.get("trades", []):
                    if "account_id" not in trade or trade["account_id"] is None:
                        trade["account_id"] = default_account_id
                        migrated_count += 1
                
                if migrated_count > 0:
                    logger.info(f"Migrated {migrated_count} trades with default account_id: {default_account_id}")

                allowed = {f.name for f in fields(PnLState)}
                unknown_keys = sorted(set(data.keys()) - allowed)
                if unknown_keys:
                    logger.warning(f"Ignoring unknown PnL state keys: {unknown_keys}")
                    data = {k: v for k, v in data.items() if k in allowed}

                return PnLState(**data)
            except Exception as e:
                logger.error(f"Failed to load state: {e}")
                pass
        now = datetime.now(timezone.utc).isoformat()
        default_account_id = os.environ.get("BROKER_ACCOUNT_ID")
        return PnLState(
            created_at=now,
            last_updated=now,
            broker_account_id=default_account_id,
            baseline_date=now[:10],
            baseline_equity=100_000.0,
            tracking_label=f"alpaca_account_epoch_{now[:10]}",
        )

    def _save_state(self) -> None:
        import tempfile

        content = json.dumps(asdict(self.state), indent=2, ensure_ascii=False)
        dir_path = self.state_path.parent
        fd, tmp_path_str = tempfile.mkstemp(
            dir=str(dir_path), prefix=".pnl_state.", suffix=".tmp"
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            tmp_path.replace(self.state_path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise
