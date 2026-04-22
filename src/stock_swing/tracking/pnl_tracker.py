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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    broker_order_id: str | None = None


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
class PnLState:
    """Full persistent P&L state."""
    created_at: str
    last_updated: str
    trades: list[dict[str, Any]] = field(default_factory=list)
    daily_snapshots: list[dict[str, Any]] = field(default_factory=list)
    cumulative_realized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    peak_equity: float = 100_000.0
    max_drawdown_pct: float = 0.0


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
    ) -> str:
        """Record a new paper order submission as an open trade.

        Returns trade_id.
        """
        trade_id = f"{symbol}-{decision_id[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        trade = TradeEntry(
            trade_id=trade_id,
            symbol=symbol,
            strategy_id=strategy_id,
            side=side,
            qty=qty,
            entry_price=price,
            exit_price=None,
            entry_time=now,
            exit_time=None,
            pnl=None,
            return_pct=None,
            status="open",
            broker_order_id=broker_order_id,
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
        broker_order_id: str | None = None,
    ) -> TradeEntry | None:
        """Mark the most recent open trade for a symbol as closed."""
        now = datetime.now(timezone.utc).isoformat()

        # Find most recent open trade for symbol
        open_trades = [
            t for t in self.state.trades
            if t["symbol"] == symbol and t["status"] == "open"
        ]
        if not open_trades:
            return None

        trade_dict = open_trades[-1]
        entry_price = trade_dict["entry_price"]
        qty = trade_dict["qty"]

        pnl = (exit_price - entry_price) * qty
        return_pct = (exit_price - entry_price) / entry_price if entry_price else 0.0

        trade_dict.update({
            "exit_price": exit_price,
            "exit_time": now,
            "pnl": round(pnl, 2),
            "return_pct": round(return_pct, 4),
            "status": "closed",
        })

        self.state.cumulative_realized_pnl += pnl
        if pnl >= 0:
            self.state.winning_trades += 1
        else:
            self.state.losing_trades += 1
        self.state.last_updated = now
        self._save_state()
        return TradeEntry(**trade_dict)

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
        }

    def get_open_positions(self) -> list[dict[str, Any]]:
        return [t for t in self.state.trades if t["status"] == "open"]

    def get_recent_trades(self, n: int = 10) -> list[dict[str, Any]]:
        closed = [t for t in self.state.trades if t["status"] == "closed"]
        return closed[-n:]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_state(self) -> PnLState:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                return PnLState(**data)
            except Exception:
                pass
        now = datetime.now(timezone.utc).isoformat()
        return PnLState(created_at=now, last_updated=now)

    def _save_state(self) -> None:
        self.state_path.write_text(
            json.dumps(asdict(self.state), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
