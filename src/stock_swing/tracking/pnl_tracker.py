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
    status: str  # "open" | "closed"
    account_id: str | None = None  # Broker account ID
    strategy_version_id: str | None = None
    broker_order_id: str | None = None
    original_strategy_id: str | None = None
    exit_strategy_id: str | None = None
    exit_reason: str | None = None


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
    ) -> str:
        """Record a new paper order submission as an open trade.

        Returns trade_id.
        
        Raises ValueError if price <= 0 (invalid entry price).
        """
        if price <= 0:
            raise ValueError(f"Invalid entry price {price} for {symbol}. Cannot record submission.")
        
        trade_id = f"{symbol}-{decision_id[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        normalized_strategy_id = strategy_version_id or normalize_strategy_id(strategy_id, now)

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
            status="open",
            account_id=account_id,
            broker_order_id=broker_order_id,
            original_strategy_id=original_strategy_id or strategy_id,
        )
        self.state.trades.append(asdict(trade))
        self.state.total_trades += 1
        self.state.last_updated = now
        self._save_state()
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
                closed_portion["status"] = "closed"
                closed_portion["exit_price"] = exit_price
                closed_portion["exit_time"] = now
                
                pnl = (exit_price - entry_price) * qty_to_close
                return_pct = (exit_price - entry_price) / entry_price if entry_price else 0.0
                closed_portion["pnl"] = round(pnl, 2)
                closed_portion["return_pct"] = round(return_pct, 4)
                if exit_strategy_id:
                    closed_portion["exit_strategy_id"] = exit_strategy_id
                if exit_reason:
                    closed_portion["exit_reason"] = exit_reason
                
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

            trade_dict.update({
                "exit_price": exit_price,
                "exit_time": now,
                "pnl": round(pnl, 2),
                "return_pct": round(return_pct, 4),
                "status": "closed",
            })
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

    def get_recent_trades(self, n: int = 10) -> list[dict[str, Any]]:
        closed = [t for t in self.state.trades if t["status"] == "closed"]
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
        self.state_path.write_text(
            json.dumps(asdict(self.state), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
