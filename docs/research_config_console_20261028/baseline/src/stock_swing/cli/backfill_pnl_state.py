#!/usr/bin/env python3
"""Backfill pnl_state.json from broker order history.

Reconstructs open/closed trades for the current broker account using filled broker
orders plus decision history to recover strategy_id / exit reason where possible.

Usage:
  python -m stock_swing.cli.backfill_pnl_state --since 2026-05-01T00:00:00+00:00 --write
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.cli.paper_demo import _load_env
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.pnl_tracker import PnLState, PnLTracker
from stock_swing.utils.strategy_versioning import extract_decision_dt, normalize_strategy_id, parse_dt, resolve_strategy_key


DEFAULT_SINCE = "2026-05-01T00:00:00+00:00"


def load_decisions(decisions_dir: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(decisions_dir.glob("decision_*.json")):
        try:
            decision = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        symbol = str(decision.get("symbol") or "").upper()
        side = "buy" if str(decision.get("action") or "").lower() == "buy" else "sell"
        generated_at = extract_decision_dt(decision, path)
        if not symbol or generated_at is None:
            continue
        sizing = decision.get("sizing") or (decision.get("evidence") or {}).get("sizing") or {}
        proposed_order = decision.get("proposed_order") or {}
        decision["_generated_at"] = generated_at
        decision["_sizing_final_shares"] = int(float(sizing.get("final_shares") or proposed_order.get("qty") or 0))
        decision["_path"] = str(path)
        index[(symbol, side)].append(decision)

    for items in index.values():
        items.sort(key=lambda d: d["_generated_at"])
    return index


def order_intent_dt(order: dict[str, Any]) -> datetime | None:
    candidates = [
        parse_dt(order.get("created_at")),
        parse_dt(order.get("submitted_at")),
        parse_dt(order.get("filled_at")),
        parse_dt(order.get("updated_at")),
    ]
    candidates = [c for c in candidates if c is not None]
    return min(candidates) if candidates else None


def order_fill_dt(order: dict[str, Any]) -> datetime | None:
    for key in ("filled_at", "submitted_at", "created_at", "updated_at"):
        dt = parse_dt(order.get(key))
        if dt is not None:
            return dt
    return None


def match_decision(
    decisions_index: dict[tuple[str, str], list[dict[str, Any]]],
    symbol: str,
    side: str,
    qty: int,
    when: datetime | None,
    max_lookback_hours: int = 72,
) -> dict[str, Any] | None:
    candidates = decisions_index.get((symbol.upper(), side.lower()), [])
    if not candidates:
        return None
    if when is None:
        return candidates[-1]

    best: tuple[float, dict[str, Any]] | None = None
    for decision in candidates:
        generated_at = decision.get("_generated_at")
        if generated_at is None:
            continue
        delta_seconds = (when - generated_at).total_seconds()
        if delta_seconds < -600:
            continue
        if delta_seconds > max_lookback_hours * 3600:
            continue
        sized_qty = int(decision.get("_sizing_final_shares") or 0)
        qty_penalty = abs(sized_qty - qty) if sized_qty > 0 else 0
        score = qty_penalty * 1_000_000 + abs(delta_seconds)
        if best is None or score < best[0]:
            best = (score, decision)
    return best[1] if best else None


def infer_exit_reason(decision: dict[str, Any] | None) -> str | None:
    if not decision:
        return None
    notes = " ".join(((decision.get("evidence") or {}).get("notes") or [])).lower()
    if "stop loss" in notes:
        return "stop_loss"
    if "take profit" in notes:
        return "take_profit"
    if "max hold" in notes:
        return "max_hold"
    return "strategy_exit"


def normalize_orders(raw_orders: list[dict[str, Any]], since: datetime) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for order in raw_orders:
        status = str(order.get("status") or "").lower()
        if status not in {"filled", "partially_filled"}:
            continue
        side = str(order.get("side") or "").lower()
        if side not in {"buy", "sell"}:
            continue
        filled_qty = int(float(order.get("filled_qty") or order.get("qty") or 0))
        filled_avg_price = float(order.get("filled_avg_price") or order.get("limit_price") or 0.0)
        fill_dt = order_fill_dt(order)
        if filled_qty <= 0 or filled_avg_price <= 0 or fill_dt is None or fill_dt < since:
            continue
        selected.append(order)
    selected.sort(key=lambda o: order_fill_dt(o) or datetime.max.replace(tzinfo=timezone.utc))
    return selected


def infer_default_strategy(decisions_index: dict[tuple[str, str], list[dict[str, Any]]], side: str) -> str | None:
    seen: set[str] = set()
    for (symbol, action), decisions in decisions_index.items():
        if action != side:
            continue
        for decision in decisions:
            strategy_id = str(decision.get("strategy_id") or "").strip()
            if strategy_id:
                seen.add(strategy_id)
    return next(iter(seen)) if len(seen) == 1 else None


def backfill_state(
    tracker: PnLTracker,
    raw_orders: list[dict[str, Any]],
    decisions_index: dict[tuple[str, str], list[dict[str, Any]]],
    since: datetime,
) -> tuple[PnLState, dict[str, Any]]:
    current_state = tracker._load_state()
    new_state = PnLState(
        created_at=current_state.created_at,
        last_updated=datetime.now(timezone.utc).isoformat(),
        trades=[],
        daily_snapshots=list(current_state.daily_snapshots),
        strategy_daily_snapshots=list(getattr(current_state, "strategy_daily_snapshots", [])),
        cumulative_realized_pnl=0.0,
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        peak_equity=current_state.peak_equity,
        max_drawdown_pct=current_state.max_drawdown_pct,
    )

    open_lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    normalized_orders = normalize_orders(raw_orders, since)
    unmatched_sells: list[dict[str, Any]] = []
    matched_decisions = 0
    unmatched_decisions = 0
    default_buy_strategy = infer_default_strategy(decisions_index, "buy")
    default_sell_strategy = infer_default_strategy(decisions_index, "sell")

    for order in normalized_orders:
        symbol = str(order.get("symbol") or "").upper()
        side = str(order.get("side") or "").lower()
        qty = int(float(order.get("filled_qty") or order.get("qty") or 0))
        price = float(order.get("filled_avg_price") or order.get("limit_price") or 0.0)
        event_dt = order_fill_dt(order)
        intent_dt = order_intent_dt(order) or event_dt
        decision = match_decision(decisions_index, symbol, side, qty, intent_dt)
        if decision is not None:
            matched_decisions += 1
        else:
            unmatched_decisions += 1

        raw_strategy_id = (decision or {}).get("strategy_id") or (default_buy_strategy if side == "buy" else default_sell_strategy) or "unknown"
        strategy_id = resolve_strategy_key(decision or {"strategy_id": raw_strategy_id}, occurred_at=event_dt)
        decision_id = (decision or {}).get("decision_id") or str(order.get("client_order_id") or order.get("id") or "unknown")
        broker_order_id = order.get("id")

        if side == "buy":
            trade = {
                "trade_id": f"{symbol}-{decision_id[:8]}",
                "symbol": symbol,
                "strategy_id": strategy_id,
                "strategy_version_id": strategy_id,
                "original_strategy_id": raw_strategy_id,
                "side": "buy",
                "qty": qty,
                "entry_price": round(price, 6),
                "exit_price": None,
                "entry_time": event_dt.isoformat(),
                "exit_time": None,
                "pnl": None,
                "return_pct": None,
                "status": "open",
                "broker_order_id": broker_order_id,
                "exit_strategy_id": None,
                "exit_reason": None,
            }
            new_state.trades.append(trade)
            open_lots[symbol].append(trade)
            new_state.total_trades += 1
            continue

        remaining = qty
        exit_strategy_id = (decision or {}).get("strategy_id") or default_sell_strategy or "unknown"
        exit_reason = infer_exit_reason(decision)
        lots = open_lots[symbol]

        while remaining > 0 and lots:
            lot = lots[0]
            lot_qty = int(lot.get("qty") or 0)
            if lot_qty <= 0:
                lots.pop(0)
                continue

            qty_to_close = min(lot_qty, remaining)
            entry_price = float(lot.get("entry_price") or 0.0)
            pnl = round((price - entry_price) * qty_to_close, 2)
            return_pct = round((price - entry_price) / entry_price, 4) if entry_price else 0.0

            if qty_to_close == lot_qty:
                lot.update({
                    "exit_price": round(price, 6),
                    "exit_time": event_dt.isoformat(),
                    "pnl": pnl,
                    "return_pct": return_pct,
                    "status": "closed",
                    "exit_strategy_id": exit_strategy_id,
                    "exit_reason": exit_reason,
                })
                lots.pop(0)
            else:
                lot["qty"] = lot_qty - qty_to_close
                closed_trade = dict(lot)
                closed_trade.update({
                    "trade_id": f"{lot.get('trade_id')}-{qty_to_close}-{event_dt.strftime('%H%M%S')}",
                    "qty": qty_to_close,
                    "exit_price": round(price, 6),
                    "exit_time": event_dt.isoformat(),
                    "pnl": pnl,
                    "return_pct": return_pct,
                    "status": "closed",
                    "exit_strategy_id": exit_strategy_id,
                    "exit_reason": exit_reason,
                })
                new_state.trades.append(closed_trade)

            new_state.cumulative_realized_pnl += pnl
            if pnl > 0:
                new_state.winning_trades += 1
            elif pnl < 0:
                new_state.losing_trades += 1
            remaining -= qty_to_close

        if remaining > 0:
            unmatched_sells.append({
                "symbol": symbol,
                "qty_unmatched": remaining,
                "broker_order_id": broker_order_id,
                "filled_at": event_dt.isoformat() if event_dt else None,
            })

    metrics = {
        "orders_considered": len(normalized_orders),
        "matched_decisions": matched_decisions,
        "unmatched_decisions": unmatched_decisions,
        "unmatched_sells": unmatched_sells,
        "open_trades": len([t for t in new_state.trades if t.get("status") == "open"]),
        "closed_trades": len([t for t in new_state.trades if t.get("status") == "closed"]),
        "winning_trades": new_state.winning_trades,
        "losing_trades": new_state.losing_trades,
        "cumulative_realized_pnl": round(new_state.cumulative_realized_pnl, 2),
    }
    return new_state, metrics


def save_state(state_path: Path, state: PnLState) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = state_path.with_name(f"{state_path.stem}.backfill_backup_{timestamp}{state_path.suffix}")
    if state_path.exists():
        shutil.copy2(state_path, backup_path)
    state_path.write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8")
    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=DEFAULT_SINCE, help="ISO timestamp; filled orders before this are ignored")
    parser.add_argument("--write", action="store_true", help="Write the reconstructed state to pnl_state.json")
    args = parser.parse_args()

    since = parse_dt(args.since)
    if since is None:
        raise SystemExit(f"Invalid --since: {args.since}")

    _load_env(project_root / ".env")
    api_key = os.environ.get("BROKER_API_KEY", "")
    api_secret = os.environ.get("BROKER_API_SECRET", "")
    if not api_key or not api_secret:
        raise SystemExit("BROKER_API_KEY / BROKER_API_SECRET missing")

    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
    tracker = PnLTracker(project_root)
    decisions_index = load_decisions(project_root / "data" / "decisions")

    orders_env = broker.fetch_orders(status="all", limit=500)
    raw_orders = orders_env.payload if hasattr(orders_env, "payload") else orders_env
    if not isinstance(raw_orders, list):
        raise SystemExit("broker.fetch_orders() did not return a list")

    state, metrics = backfill_state(tracker, raw_orders, decisions_index, since)

    result = {
        "since": since.isoformat(),
        "metrics": metrics,
        "summary": {
            "total_trade_records": len(state.trades),
            "total_entries": state.total_trades,
            "open_trades": len([t for t in state.trades if t.get("status") == "open"]),
            "closed_trades": len([t for t in state.trades if t.get("status") == "closed"]),
            "daily_snapshots": len(state.daily_snapshots),
        },
        "sample_recent_closed": [t for t in state.trades if t.get("status") == "closed"][-5:],
        "sample_open": [t for t in state.trades if t.get("status") == "open"][:5],
    }

    if args.write:
        backup_path = save_state(tracker.state_path, state)
        result["backup_path"] = str(backup_path)
        result["written_path"] = str(tracker.state_path)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
