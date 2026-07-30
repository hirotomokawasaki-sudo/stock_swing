"""R0-v2-C: Typed RiskSnapshot — single source for all guardrail metrics.

Computes all 9 guardrail metrics from live state so they can be supplied
consistently at startup, pre-order, and post-run without duplication.

Metrics:
    stale_price_event_count     : int    — stale data events this run
    broker_tracker_mismatch_count: int   — unexcused position mismatches
    daily_realized_loss_pct     : float  — today's realized PnL / equity * 100
    daily_total_loss_pct        : float  — today's (realized + unrealized Δ) / equity * 100
    weekly_total_loss_pct       : float  — 5-day rolling total loss / equity * 100
    consecutive_losing_trades   : int    — tail run of losing closed trades
    api_error_rate_pct          : float  — API errors / API calls * 100
    order_rejection_rate_pct    : float  — rejected orders / submitted * 100
    token_spend_spike_pct       : float  — run tokens / daily budget - 100 (0 if within)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class RiskSnapshot:
    """All guardrail metrics in one typed object."""

    stale_price_event_count: int = 0
    broker_tracker_mismatch_count: int = 0
    daily_realized_loss_pct: float = 0.0
    daily_total_loss_pct: float = 0.0
    weekly_total_loss_pct: float = 0.0
    consecutive_losing_trades: int = 0
    api_error_rate_pct: float = 0.0
    order_rejection_rate_pct: float = 0.0
    token_spend_spike_pct: float = 0.0
    # Metadata
    missing_metrics: list[str] = field(default_factory=list)

    def to_metrics(self) -> dict[str, float | int]:
        """Return flat dict expected by GuardrailEngine.evaluate()."""
        return {
            "stale_price_event_count": self.stale_price_event_count,
            "broker_tracker_mismatch_count": self.broker_tracker_mismatch_count,
            "daily_realized_loss_pct": self.daily_realized_loss_pct,
            "daily_total_loss_pct": self.daily_total_loss_pct,
            "weekly_total_loss_pct": self.weekly_total_loss_pct,
            "consecutive_losing_trades": self.consecutive_losing_trades,
            "api_error_rate_pct": self.api_error_rate_pct,
            "order_rejection_rate_pct": self.order_rejection_rate_pct,
            "token_spend_spike_pct": self.token_spend_spike_pct,
        }


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _date_str(dt_str: str) -> str:
    """Extract YYYY-MM-DD from an ISO timestamp string."""
    try:
        return str(dt_str)[:10]
    except Exception:
        return ""


def compute_daily_realized_loss_pct(
    trades: list[dict[str, Any]],
    equity: float,
    reference_date: str | None = None,
) -> float:
    """Compute today's realized PnL as % of equity (negative = loss).

    Args:
        trades: All trades from pnl_tracker.state.trades.
        equity: Current account equity.
        reference_date: YYYY-MM-DD to compute for (default: today UTC).
    """
    if equity <= 0:
        return 0.0
    today = reference_date or _today_utc()
    closed_today = [
        t for t in trades
        if t.get("status") == "closed" and _date_str(t.get("exit_time", "")) == today
    ]
    pnl_today = sum(float(t.get("pnl", 0) or 0) for t in closed_today)
    return round(pnl_today / equity * 100, 4)


def compute_weekly_total_loss_pct(
    trades: list[dict[str, Any]],
    equity: float,
    reference_date: str | None = None,
    days: int = 5,
) -> float:
    """Compute rolling N-day total realized PnL as % of equity."""
    if equity <= 0:
        return 0.0
    today = datetime.strptime(reference_date or _today_utc(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    cutoff = today - timedelta(days=days)
    closed_week = [
        t for t in trades
        if t.get("status") == "closed"
        and _date_str(t.get("exit_time", "")) >= cutoff.strftime("%Y-%m-%d")
    ]
    pnl_week = sum(float(t.get("pnl", 0) or 0) for t in closed_week)
    return round(pnl_week / equity * 100, 4)


def compute_consecutive_losing_trades(trades: list[dict[str, Any]]) -> int:
    """Count the tail run of consecutive losing closed trades (sorted by exit_time)."""
    closed = [t for t in trades if t.get("status") == "closed" and t.get("exit_time")]
    if not closed:
        return 0
    closed_sorted = sorted(closed, key=lambda t: str(t.get("exit_time", "")))
    count = 0
    for t in reversed(closed_sorted):
        pnl = float(t.get("pnl", 0) or 0)
        if pnl < 0:
            count += 1
        else:
            break
    return count


def build_risk_snapshot(
    *,
    trades: list[dict[str, Any]],
    equity: float,
    unrealized_pnl: float = 0.0,
    prev_unrealized_pnl: float = 0.0,
    stale_price_event_count: int = 0,
    broker_tracker_mismatch_count: int = 0,
    api_error_rate_pct: float = 0.0,
    order_rejection_rate_pct: float = 0.0,
    token_spend_spike_pct: float = 0.0,
    reference_date: str | None = None,
) -> RiskSnapshot:
    """Build a RiskSnapshot from live pnl_tracker state and run metrics.

    Args:
        trades: pnl_tracker.state.trades
        equity: Current broker equity
        unrealized_pnl: Current unrealized PnL (sum of open positions)
        prev_unrealized_pnl: Unrealized at run start (for daily_total_loss_pct delta)
        stale_price_event_count: From stale price detection
        broker_tracker_mismatch_count: From broker/tracker diff (lag-adjusted)
        api_error_rate_pct: From latency_tracker
        order_rejection_rate_pct: From submissions
        token_spend_spike_pct: From AI usage vs daily budget
        reference_date: YYYY-MM-DD for date-relative metrics (default: today UTC)
    """
    missing: list[str] = []

    daily_realized = compute_daily_realized_loss_pct(trades, equity, reference_date)
    weekly_total = compute_weekly_total_loss_pct(trades, equity, reference_date)
    consecutive = compute_consecutive_losing_trades(trades)

    # daily_total includes unrealized delta since start of run
    unrealized_delta = unrealized_pnl - prev_unrealized_pnl
    daily_realized_abs = daily_realized / 100 * equity if equity else 0.0
    daily_total_pct = round((daily_realized_abs + unrealized_delta) / equity * 100, 4) if equity else 0.0

    if equity <= 0:
        missing.append("equity")

    return RiskSnapshot(
        stale_price_event_count=stale_price_event_count,
        broker_tracker_mismatch_count=broker_tracker_mismatch_count,
        daily_realized_loss_pct=daily_realized,
        daily_total_loss_pct=daily_total_pct,
        weekly_total_loss_pct=weekly_total,
        consecutive_losing_trades=consecutive,
        api_error_rate_pct=api_error_rate_pct,
        order_rejection_rate_pct=order_rejection_rate_pct,
        token_spend_spike_pct=token_spend_spike_pct,
        missing_metrics=missing,
    )


def compute_risk_snapshot(
    *,
    trades: list[dict[str, Any]],
    equity: float,
    unrealized_pnl: float = 0.0,
    prev_unrealized_pnl: float = 0.0,
    stale_price_event_count: int = 0,
    broker_tracker_mismatch_count: int = 0,
    api_error_rate_pct: float = 0.0,
    order_rejection_rate_pct: float = 0.0,
    token_spend_spike_pct: float = 0.0,
    reference_date: str | None = None,
) -> RiskSnapshot:
    """Backward-compatible alias used by regression tests and older callers."""
    return build_risk_snapshot(
        trades=trades,
        equity=equity,
        unrealized_pnl=unrealized_pnl,
        prev_unrealized_pnl=prev_unrealized_pnl,
        stale_price_event_count=stale_price_event_count,
        broker_tracker_mismatch_count=broker_tracker_mismatch_count,
        api_error_rate_pct=api_error_rate_pct,
        order_rejection_rate_pct=order_rejection_rate_pct,
        token_spend_spike_pct=token_spend_spike_pct,
        reference_date=reference_date,
    )
