"""Broker-backed inputs for an auditable equity bridge reconciliation.

The trade ledger is strategy-facing and may intentionally quarantine malformed
historical rows.  Broker order cash flows are a separate accounting source that
does not depend on FIFO matching or split-adjusted share quantities.  This
module keeps those concerns separate and provides validated inputs for the
equity bridge without rewriting ``pnl_state.json``.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1


def _parse_utc_timestamp(value: str | None) -> datetime | None:
    """Parse common ISO-8601 variants into a comparable UTC timestamp."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def compute_tracker_history_fingerprint(
    trades: Iterable[dict[str, Any]],
    *,
    cutoff: str | None,
) -> tuple[int, str]:
    """Fingerprint closed tracker history through the broker reconciliation cutoff."""
    fields = (
        "trade_id",
        "symbol",
        "qty",
        "entry_price",
        "exit_price",
        "pnl",
        "entry_time",
        "exit_time",
        "broker_order_id",
        "exit_broker_order_id",
    )
    rows = []
    cutoff_time = _parse_utc_timestamp(cutoff)
    for trade in trades:
        if trade.get("status") != "closed":
            continue
        exit_time = str(trade.get("exit_time") or "")
        parsed_exit_time = _parse_utc_timestamp(exit_time)
        if cutoff_time and parsed_exit_time and parsed_exit_time > cutoff_time:
            continue
        rows.append({field: trade.get(field) for field in fields})
    rows.sort(
        key=lambda row: (
            str(row.get("exit_time") or ""),
            str(row.get("trade_id") or ""),
        )
    )
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return len(rows), hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_order_cash_realized(
    orders: Iterable[dict[str, Any]],
    positions: Iterable[dict[str, Any]],
) -> tuple[float, dict[str, float]]:
    """Return gross realized P&L from order cash flows and open cost basis.

    ``sell proceeds - buy costs + current open cost basis`` is invariant to
    stock-split quantity changes.  That makes it safer than rebuilding FIFO
    lots when historical corporate actions are present.
    """
    cash_by_symbol: dict[str, float] = defaultdict(float)
    for order in orders:
        qty = float(order.get("filled_qty") or 0)
        price = float(order.get("filled_avg_price") or 0)
        symbol = str(order.get("symbol") or "").upper()
        side = str(order.get("side") or "").lower()
        if not symbol or qty <= 0 or price <= 0 or side not in {"buy", "sell"}:
            continue
        cash_by_symbol[symbol] += qty * price * (1 if side == "sell" else -1)

    cost_basis_by_symbol: dict[str, float] = defaultdict(float)
    for position in positions:
        symbol = str(position.get("symbol") or "").upper()
        if not symbol:
            continue
        cost_basis_by_symbol[symbol] += float(position.get("cost_basis") or 0)

    realized_by_symbol = {
        symbol: cash_by_symbol.get(symbol, 0.0) + cost_basis_by_symbol.get(symbol, 0.0)
        for symbol in set(cash_by_symbol) | set(cost_basis_by_symbol)
    }
    return sum(realized_by_symbol.values()), realized_by_symbol


def summarize_account_activities(
    activities: Iterable[dict[str, Any]],
    *,
    baseline_date: str,
) -> dict[str, Any]:
    """Summarize post-baseline fees and non-trading cash flows."""
    baseline = date.fromisoformat(baseline_date)
    fees = 0.0
    external_cash = 0.0
    counts: dict[str, int] = defaultdict(int)

    for activity in activities:
        activity_type = str(activity.get("activity_type") or "").upper()
        stamp = str(activity.get("transaction_time") or activity.get("date") or "")
        if not activity_type or not stamp:
            continue
        try:
            activity_date = date.fromisoformat(stamp[:10])
        except ValueError:
            continue
        if activity_date < baseline:
            continue

        counts[activity_type] += 1
        net_amount = float(activity.get("net_amount") or 0)
        if activity_type == "FEE":
            fees -= net_amount
        elif activity_type not in {"FILL", "SPLIT"}:
            external_cash += net_amount

    return {
        "fees": fees,
        "external_cash_adjustment": external_cash,
        "activity_counts": dict(sorted(counts.items())),
    }


def build_reconciliation_snapshot(
    *,
    generated_at: str,
    broker_account_id: str | None,
    baseline_date: str,
    baseline_equity: float,
    tracker_realized: float,
    broker_equity: float,
    broker_unrealized: float,
    broker_order_cash_realized: float,
    broker_realized_by_symbol: dict[str, float],
    tracker_realized_by_symbol: dict[str, float],
    fees: float,
    external_cash_adjustment: float,
    order_count: int,
    activity_count: int,
    last_filled_at: str | None,
    quarantined_pnl_raw: float,
    quarantine_count: int,
    tracker_trades: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build a reconciliation artifact and its independent account check."""
    realized_adjustment = broker_order_cash_realized - tracker_realized
    expected_equity = (
        baseline_equity
        + external_cash_adjustment
        + broker_order_cash_realized
        + broker_unrealized
        - fees
    )
    account_check_diff = broker_equity - expected_equity

    symbols = set(broker_realized_by_symbol) | set(tracker_realized_by_symbol)
    symbol_deltas = [
        {
            "symbol": symbol,
            "broker_cash_realized": round(broker_realized_by_symbol.get(symbol, 0.0), 2),
            "tracker_realized": round(tracker_realized_by_symbol.get(symbol, 0.0), 2),
            "delta": round(
                broker_realized_by_symbol.get(symbol, 0.0)
                - tracker_realized_by_symbol.get(symbol, 0.0),
                2,
            ),
        }
        for symbol in symbols
    ]
    symbol_deltas.sort(key=lambda row: abs(row["delta"]), reverse=True)
    closed_count, history_fingerprint = compute_tracker_history_fingerprint(
        tracker_trades,
        cutoff=last_filled_at,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "method": "filled_order_cash_flow_plus_open_cost_basis",
        "broker_account_id": broker_account_id,
        "baseline_date": baseline_date,
        "baseline_equity": round(baseline_equity, 2),
        "order_count": order_count,
        "activity_count": activity_count,
        "last_filled_at": last_filled_at,
        "tracker_closed_count_at_reconciliation": closed_count,
        "tracker_history_fingerprint": history_fingerprint,
        "tracker_realized_at_reconciliation": round(tracker_realized, 2),
        "broker_order_cash_realized": round(broker_order_cash_realized, 2),
        "realized_pnl_adjustment": round(realized_adjustment, 2),
        "fees": round(fees, 2),
        "external_cash_adjustment": round(external_cash_adjustment, 2),
        "broker_unrealized_at_reconciliation": round(broker_unrealized, 2),
        "broker_equity_at_reconciliation": round(broker_equity, 2),
        "account_check_expected_equity": round(expected_equity, 2),
        "account_check_diff": round(account_check_diff, 2),
        "quarantine_count": quarantine_count,
        "quarantined_pnl_raw": round(quarantined_pnl_raw, 2),
        "quarantined_pnl_adjustment": 0.0,
        "quarantine_policy": "unverified_reconstruction_pnl_is_observability_only",
        "symbol_deltas": symbol_deltas,
    }


def load_reconciliation_snapshot(
    path: Path,
    *,
    expected_baseline_equity: float,
    expected_account_id: str | None,
    current_trades: Iterable[dict[str, Any]] | None = None,
    max_account_check_diff: float = 25.0,
) -> dict[str, Any] | None:
    """Load a snapshot only when its identity and account check are valid."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("schema_version")) != SCHEMA_VERSION:
            return None
        if abs(float(data.get("baseline_equity")) - expected_baseline_equity) > 0.01:
            return None
        artifact_account = data.get("broker_account_id")
        if expected_account_id and artifact_account != expected_account_id:
            return None
        if abs(float(data.get("account_check_diff"))) > max_account_check_diff:
            return None
        if current_trades is not None:
            closed_count, fingerprint = compute_tracker_history_fingerprint(
                current_trades,
                cutoff=data.get("last_filled_at"),
            )
            if closed_count != int(data.get("tracker_closed_count_at_reconciliation")):
                return None
            if fingerprint != data.get("tracker_history_fingerprint"):
                return None
        for key in (
            "realized_pnl_adjustment",
            "fees",
            "external_cash_adjustment",
            "quarantined_pnl_adjustment",
        ):
            float(data.get(key))
        return data
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
