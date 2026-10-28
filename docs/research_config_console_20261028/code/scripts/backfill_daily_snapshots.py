#!/usr/bin/env python3
"""Backfill missing daily snapshots from broker daily bars and tracker trades."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.cli.paper_demo import _load_env
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.pnl_tracker import DailySnapshot, PnLTracker, StrategyDailySnapshot


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_benchmark_dates(project_root: Path) -> list[str]:
    path = project_root / "data" / "benchmarks" / "SPY_daily.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return sorted(str(row.get("date") or "") for row in rows if row.get("date"))


def active_trade_on_date(trade: dict[str, Any], date_str: str) -> bool:
    entry_dt = parse_dt(trade.get("entry_time"))
    if entry_dt is None or entry_dt.date().isoformat() > date_str:
        return False
    exit_dt = parse_dt(trade.get("exit_time"))
    return exit_dt is None or exit_dt.date().isoformat() > date_str


def load_price_series(
    broker: BrokerClient,
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, dict[str, float]]:
    price_map: dict[str, dict[str, float]] = {}
    fetch_end = (datetime.fromisoformat(end_date) + timedelta(days=1)).date().isoformat()
    for symbol in symbols:
        bars_env = broker.fetch_bars(symbol=symbol, timeframe="1Day", start=start_date, end=fetch_end)
        payload = bars_env.payload if hasattr(bars_env, "payload") else {}
        bars = payload.get("bars", []) if isinstance(payload, dict) else []
        series: dict[str, float] = {}
        for bar in bars:
            bar_date = str(bar.get("t") or "")[:10]
            close = bar.get("c")
            if bar_date and close is not None:
                series[bar_date] = float(close)
        price_map[symbol] = series
    return price_map


def resolve_close(price_series: dict[str, float], date_str: str) -> float | None:
    if date_str in price_series:
        return price_series[date_str]
    candidates = [d for d in price_series if d <= date_str]
    if not candidates:
        return None
    return price_series[max(candidates)]


def build_daily_snapshot(
    trades: list[dict[str, Any]],
    date_str: str,
    baseline_equity: float,
    price_map: dict[str, dict[str, float]],
) -> tuple[dict[str, Any], dict[str, float]]:
    today_closed = []
    open_trades = []
    cumulative_realized = 0.0
    current_prices: dict[str, float] = {}

    for trade in trades:
        entry_dt = parse_dt(trade.get("entry_time"))
        if entry_dt is None or entry_dt.date().isoformat() > date_str:
            continue

        exit_dt = parse_dt(trade.get("exit_time"))
        if trade.get("status") == "closed" and exit_dt is not None and exit_dt.date().isoformat() <= date_str:
            pnl = float(trade.get("pnl") or 0.0)
            cumulative_realized += pnl
            if exit_dt.date().isoformat() == date_str:
                today_closed.append(trade)
            continue

        if active_trade_on_date(trade, date_str):
            open_trades.append(trade)

    unrealized = 0.0
    for trade in open_trades:
        symbol = str(trade.get("symbol") or "")
        close = resolve_close(price_map.get(symbol, {}), date_str)
        if close is None:
            close = float(trade.get("entry_price") or 0.0)
        current_prices[symbol] = close
        unrealized += (close - float(trade.get("entry_price") or 0.0)) * float(trade.get("qty") or 0.0)

    realized_today = round(sum(float(t.get("pnl") or 0.0) for t in today_closed), 2)
    wins = sum(1 for t in today_closed if float(t.get("pnl") or 0.0) >= 0)
    losses = len(today_closed) - wins
    equity = round(baseline_equity + cumulative_realized + unrealized, 2)

    snap = DailySnapshot(
        date=date_str,
        equity=equity,
        realized_pnl=realized_today,
        unrealized_pnl=round(unrealized, 2),
        total_pnl=round(realized_today + unrealized, 2),
        trade_count=len(today_closed),
        win_count=wins,
        loss_count=losses,
        signals_generated=0,
        orders_submitted=0,
    )
    return asdict(snap), current_prices


def build_strategy_rows(
    trades: list[dict[str, Any]],
    date_str: str,
    current_prices: dict[str, float],
    prior_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    closed_by_strategy: dict[str, dict[str, float | int]] = {}
    cumulative_realized_by_strategy: dict[str, float] = {}
    open_by_strategy: dict[str, dict[str, float | int]] = {}

    def closed_bucket(strategy_id: str) -> dict[str, float | int]:
        return closed_by_strategy.setdefault(
            strategy_id,
            {"realized_pnl": 0.0, "traded_notional": 0.0, "trade_count": 0, "win_count": 0, "loss_count": 0},
        )

    def open_bucket(strategy_id: str) -> dict[str, float | int]:
        return open_by_strategy.setdefault(
            strategy_id,
            {"unrealized_pnl": 0.0, "gross_exposure": 0.0, "open_positions": 0},
        )

    for trade in trades:
        entry_dt = parse_dt(trade.get("entry_time"))
        if entry_dt is None or entry_dt.date().isoformat() > date_str:
            continue

        strategy_id = str(trade.get("strategy_version_id") or trade.get("strategy_id") or "unknown")
        exit_dt = parse_dt(trade.get("exit_time"))

        if trade.get("status") == "closed" and exit_dt is not None and exit_dt.date().isoformat() <= date_str:
            pnl = float(trade.get("pnl") or 0.0)
            cumulative_realized_by_strategy[strategy_id] = cumulative_realized_by_strategy.get(strategy_id, 0.0) + pnl
            if exit_dt.date().isoformat() == date_str:
                row = closed_bucket(strategy_id)
                row["realized_pnl"] = float(row["realized_pnl"]) + pnl
                row["traded_notional"] = float(row["traded_notional"]) + abs(
                    float(trade.get("entry_price") or 0.0) * float(trade.get("qty") or 0.0)
                )
                row["trade_count"] = int(row["trade_count"]) + 1
                if pnl > 0:
                    row["win_count"] = int(row["win_count"]) + 1
                elif pnl < 0:
                    row["loss_count"] = int(row["loss_count"]) + 1
            continue

        if active_trade_on_date(trade, date_str):
            close = float(current_prices.get(str(trade.get("symbol") or ""), float(trade.get("entry_price") or 0.0)))
            qty = float(trade.get("qty") or 0.0)
            entry_price = float(trade.get("entry_price") or 0.0)
            row = open_bucket(strategy_id)
            row["gross_exposure"] = float(row["gross_exposure"]) + (close * qty)
            row["open_positions"] = int(row["open_positions"]) + 1
            row["unrealized_pnl"] = float(row["unrealized_pnl"]) + ((close - entry_price) * qty)

    latest_prior_by_strategy: dict[str, dict[str, Any]] = {}
    for row in prior_rows:
        if str(row.get("date") or "") >= date_str:
            continue
        strategy_id = str(row.get("strategy_version_id") or "unknown")
        prev = latest_prior_by_strategy.get(strategy_id)
        if prev is None or str(row.get("date") or "") > str(prev.get("date") or ""):
            latest_prior_by_strategy[strategy_id] = row

    rows: list[dict[str, Any]] = []
    all_strategy_ids = set(cumulative_realized_by_strategy) | set(closed_by_strategy) | set(open_by_strategy)
    for strategy_id in sorted(all_strategy_ids):
        prev = latest_prior_by_strategy.get(strategy_id)
        closed_row = closed_by_strategy.get(strategy_id, {})
        open_row = open_by_strategy.get(strategy_id, {})
        realized = float(closed_row.get("realized_pnl") or 0.0)
        cumulative_realized = float(cumulative_realized_by_strategy.get(strategy_id) or 0.0)
        unrealized = float(open_row.get("unrealized_pnl") or 0.0)
        gross_exposure = float(open_row.get("gross_exposure") or 0.0)
        traded_notional = float(closed_row.get("traded_notional") or 0.0)
        prev_unrealized = float((prev or {}).get("unrealized_pnl") or 0.0)
        prev_gross = float((prev or {}).get("gross_exposure") or 0.0)
        prev_equity_index = float((prev or {}).get("equity_index") or 100.0)

        day_pnl = realized + (unrealized - prev_unrealized)
        capital_base = max(traded_notional, gross_exposure, prev_gross, 1.0)
        day_return_pct = round(day_pnl / capital_base, 6)
        equity_index = round(prev_equity_index * (1.0 + day_return_pct), 6)

        row = StrategyDailySnapshot(
            date=date_str,
            strategy_version_id=strategy_id,
            equity_index=equity_index,
            day_return_pct=day_return_pct,
            realized_pnl=round(realized, 2),
            cumulative_realized_pnl=round(cumulative_realized, 2),
            unrealized_pnl=round(unrealized, 2),
            total_pnl=round(cumulative_realized + unrealized, 2),
            gross_exposure=round(gross_exposure, 2),
            traded_notional=round(traded_notional, 2),
            trade_count=int(closed_row.get("trade_count") or 0),
            win_count=int(closed_row.get("win_count") or 0),
            loss_count=int(closed_row.get("loss_count") or 0),
            open_positions=int(open_row.get("open_positions") or 0),
        )
        rows.append(asdict(row))
    return rows


def compute_drawdown(snapshots: list[dict[str, Any]]) -> tuple[float, float]:
    peak_equity = 0.0
    max_drawdown = 0.0
    for row in sorted(snapshots, key=lambda r: (str(r.get("date") or ""), float(r.get("equity") or 0.0))):
        equity = float(row.get("equity") or 0.0)
        if equity > peak_equity:
            peak_equity = equity
        if peak_equity > 0:
            max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
    return round(peak_equity, 2), round(max_drawdown, 4)


def save_state(path: Path, data: dict[str, Any]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_name(f"{path.stem}.snapshot_backfill_backup_{timestamp}{path.suffix}")
    shutil.copy2(path, backup_path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", help="Override the first YYYY-MM-DD date to backfill")
    parser.add_argument("--end-date", help="Override the last YYYY-MM-DD date to backfill")
    parser.add_argument("--write", action="store_true", help="Persist changes to pnl_state.json")
    args = parser.parse_args()

    _load_env(project_root / ".env")
    api_key = os.environ.get("BROKER_API_KEY", "")
    api_secret = os.environ.get("BROKER_API_SECRET", "")
    if not api_key or not api_secret:
        raise SystemExit("BROKER_API_KEY / BROKER_API_SECRET missing")

    tracker = PnLTracker(project_root)
    state_path = tracker.state_path
    state = json.loads(state_path.read_text(encoding="utf-8"))
    trades = list(state.get("trades") or [])
    snapshots = list(state.get("daily_snapshots") or [])
    strategy_rows = list(state.get("strategy_daily_snapshots") or [])
    baseline_equity = float(state.get("baseline_equity") or 100000.0)

    existing_dates = sorted({str(row.get("date") or "") for row in snapshots if row.get("date")})
    if not existing_dates and not args.start_date:
        raise SystemExit("No existing daily snapshots; pass --start-date explicitly")

    benchmark_dates = load_benchmark_dates(project_root)
    start_date = args.start_date or max(existing_dates)
    end_date = args.end_date or max(benchmark_dates)
    target_dates = [d for d in benchmark_dates if start_date < d <= end_date]
    if not target_dates:
        print(json.dumps({"target_dates": [], "message": "No missing benchmark-backed dates to backfill."}, indent=2))
        return 0

    relevant_symbols = sorted(
        {
            str(trade.get("symbol") or "")
            for trade in trades
            if trade.get("symbol")
            and parse_dt(trade.get("entry_time")) is not None
            and parse_dt(trade.get("entry_time")).date().isoformat() <= target_dates[-1]
            and (
                parse_dt(trade.get("exit_time")) is None
                or parse_dt(trade.get("exit_time")).date().isoformat() > target_dates[0]
            )
        }
    )

    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True, base_url=os.environ.get("BROKER_BASE_URL"))
    price_map = load_price_series(broker, relevant_symbols, target_dates[0], target_dates[-1])

    existing_by_date = {str(row.get("date") or ""): row for row in snapshots}
    new_snapshot_rows: list[dict[str, Any]] = []
    base_strategy_rows = [row for row in strategy_rows if str(row.get("date") or "") < target_dates[0]]
    generated_strategy_rows = list(base_strategy_rows)

    for date_str in target_dates:
        snapshot_row, current_prices = build_daily_snapshot(trades, date_str, baseline_equity, price_map)
        new_snapshot_rows.append(snapshot_row)
        generated_strategy_rows.extend(build_strategy_rows(trades, date_str, current_prices, generated_strategy_rows))

    final_snapshots = [row for row in snapshots if str(row.get("date") or "") not in set(target_dates)] + new_snapshot_rows
    final_snapshots.sort(key=lambda row: (str(row.get("date") or ""), float(row.get("equity") or 0.0)))

    final_strategy_rows = [
        row for row in strategy_rows if str(row.get("date") or "") not in set(target_dates)
    ] + [row for row in generated_strategy_rows if str(row.get("date") or "") in set(target_dates)]
    final_strategy_rows.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("strategy_version_id") or "")))

    peak_equity, max_drawdown = compute_drawdown(final_snapshots)
    state["daily_snapshots"] = final_snapshots
    state["strategy_daily_snapshots"] = final_strategy_rows
    state["peak_equity"] = max(float(state.get("peak_equity") or 0.0), peak_equity)
    state["max_drawdown_pct"] = max(float(state.get("max_drawdown_pct") or 0.0), max_drawdown)
    state["last_updated"] = datetime.now(timezone.utc).isoformat()

    result = {
        "target_dates": target_dates,
        "symbols_considered": relevant_symbols,
        "generated_daily_snapshots": [
            {
                "date": row["date"],
                "equity": row["equity"],
                "realized_pnl": row["realized_pnl"],
                "unrealized_pnl": row["unrealized_pnl"],
                "replaced_existing": row["date"] in existing_by_date,
            }
            for row in new_snapshot_rows
        ],
        "generated_strategy_rows": len([row for row in final_strategy_rows if str(row.get("date") or "") in set(target_dates)]),
        "peak_equity": state["peak_equity"],
        "max_drawdown_pct": state["max_drawdown_pct"],
    }

    if args.write:
        backup_path = save_state(state_path, state)
        result["backup_path"] = str(backup_path)
        result["written_path"] = str(state_path)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
