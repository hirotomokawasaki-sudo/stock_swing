#!/usr/bin/env python3
"""Compare exit strategy variants against the current SimpleExitV2 baseline.

Design scaffold for the 4-way experiment:
- A: baseline SimpleExitV2
- B: baseline + break-even stop
- C: baseline + stalled-winner exit
- D: baseline + staged trailing stop

This file is intentionally a structured template:
- CLI and data plumbing are in place
- variant definitions are explicit
- output/report shapes are defined
- replay / open-position evaluation hooks are marked TODO

Recommended next implementation order:
1. Implement `load_price_store()` using Massive/Yahoo/local cache
2. Implement `replay_closed_trades()` with bar-by-bar exit replay
3. Implement `evaluate_open_positions_snapshot()` for forward-like comparison
4. Fill `print_report()` with richer tables / JSON export
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.backtest.price_cache import PriceCache
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.massive_client import MassiveClient

DEFAULT_PNL_PATH = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "exit_variant_comparison.json"
DEFAULT_PRICE_CACHE_DIR = PROJECT_ROOT / "data" / "backtest_price_cache"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass
class ExitVariantSpec:
    key: str
    name: str
    description: str
    stop_loss_pct: float = -0.07
    trailing_activation_pct: float = 0.05
    trailing_stop_pct: float = 0.03
    max_hold_days: int = 20
    break_even_activation_pct: float | None = None
    break_even_floor_pct: float | None = None
    stalled_min_hold_days: int | None = None
    stalled_peak_threshold_pct: float | None = None
    stalled_current_threshold_pct: float | None = None
    staged_trailing_levels: list[dict[str, float]] = field(default_factory=list)


@dataclass
class ClosedTradeReplay:
    trade_id: str
    symbol: str
    entry_time: str | None
    actual_exit_time: str | None
    actual_exit_price: float | None
    actual_pnl: float | None
    actual_return_pct: float | None
    simulated_exit_time: str | None
    simulated_exit_price: float | None
    simulated_pnl: float | None
    simulated_return_pct: float | None
    simulated_exit_reason: str | None
    pnl_delta: float | None


@dataclass
class VariantMetrics:
    variant_key: str
    variant_name: str
    trade_count: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    avg_return_pct: float = 0.0
    avg_hold_days: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    stop_loss_count: int = 0
    take_profit_count: int = 0
    trailing_count: int = 0
    max_hold_count: int = 0
    break_even_count: int = 0
    stalled_winner_count: int = 0
    manual_count: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class OpenPositionDecision:
    symbol: str
    qty: float
    hold_days: float | None
    return_pct: float | None
    peak_return_pct: float | None
    would_exit: bool
    exit_reason: str | None


@dataclass
class VariantComparison:
    spec: ExitVariantSpec
    metrics: VariantMetrics
    changed_trades: list[ClosedTradeReplay] = field(default_factory=list)
    open_position_decisions: list[OpenPositionDecision] = field(default_factory=list)


def build_variants() -> list[ExitVariantSpec]:
    return [
        ExitVariantSpec(
            key="A",
            name="baseline",
            description="Current SimpleExitV2 baseline",
        ),
        ExitVariantSpec(
            key="B",
            name="baseline_plus_break_even",
            description="Baseline + break-even stop after +4%",
            break_even_activation_pct=0.04,
            break_even_floor_pct=0.0,
        ),
        ExitVariantSpec(
            key="C",
            name="baseline_plus_stalled_winner",
            description="Baseline + stalled winner exit after 3+ days if peak<6% and current<2%",
            stalled_min_hold_days=3,
            stalled_peak_threshold_pct=0.06,
            stalled_current_threshold_pct=0.02,
        ),
        ExitVariantSpec(
            key="C6",
            name="baseline_plus_stalled_winner_conservative",
            description="Baseline + stalled winner exit after 6+ days if peak<5% and current<0.5%",
            stalled_min_hold_days=6,
            stalled_peak_threshold_pct=0.05,
            stalled_current_threshold_pct=0.005,
        ),
        ExitVariantSpec(
            key="D",
            name="baseline_plus_staged_trailing",
            description="Baseline + tighter staged trailing at higher profit bands",
            staged_trailing_levels=[
                {"activation_pct": 0.05, "trailing_stop_pct": 0.035},
                {"activation_pct": 0.08, "trailing_stop_pct": 0.03},
                {"activation_pct": 0.12, "trailing_stop_pct": 0.025},
            ],
        ),
    ]


def load_pnl_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def filter_closed_trades(
    trades: list[dict[str, Any]],
    start: datetime | None,
    end: datetime | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade in trades:
        if trade.get("status") != "closed":
            continue
        entry_dt = parse_dt(trade.get("entry_time"))
        if start and entry_dt and entry_dt < start:
            continue
        if end and entry_dt and entry_dt > end:
            continue
        rows.append(trade)
    return rows


def filter_open_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [trade for trade in trades if trade.get("status") == "open"]


def load_live_broker_snapshot() -> list[dict[str, Any]]:
    load_env_file(PROJECT_ROOT / ".env")
    api_key = os.environ.get("BROKER_API_KEY")
    api_secret = os.environ.get("BROKER_API_SECRET")
    if not api_key or not api_secret:
        return []
    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
    response = broker.fetch_positions()
    payload = response.payload if hasattr(response, "payload") else response
    return payload if isinstance(payload, list) else []


def aggregate_open_trades(open_trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for trade in open_trades:
        symbol = str(trade.get("symbol") or "").upper()
        if not symbol:
            continue
        qty = float(trade.get("qty") or 0.0)
        entry_price = float(trade.get("entry_price") or 0.0)
        peak_price = float(trade.get("peak_price") or 0.0)
        entry_time = trade.get("entry_time") or trade.get("created_at")
        row = grouped.setdefault(symbol, {
            "symbol": symbol,
            "qty": 0.0,
            "entry_notional": 0.0,
            "entry_time": None,
            "peak_price": 0.0,
        })
        row["qty"] += qty
        row["entry_notional"] += entry_price * qty
        if entry_time and (row["entry_time"] is None or str(entry_time) < str(row["entry_time"])):
            row["entry_time"] = entry_time
        row["peak_price"] = max(float(row["peak_price"] or 0.0), peak_price)
    for row in grouped.values():
        row["avg_entry_price"] = (row["entry_notional"] / row["qty"]) if row["qty"] > 0 else 0.0
    return grouped


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def normalize_bar(date: datetime, bar: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": date.date().isoformat(),
        "open": float(bar.get("open") or 0.0),
        "high": float(bar.get("high") or 0.0),
        "low": float(bar.get("low") or 0.0),
        "close": float(bar.get("close") or 0.0),
        "volume": float(bar.get("volume") or 0.0),
    }


def build_price_lookup(price_store: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        symbol: {bar["date"]: bar for bar in bars}
        for symbol, bars in price_store.items()
    }


def trailing_stop_pct_for_variant(variant: ExitVariantSpec, peak_return_pct: float) -> float:
    trailing_stop_pct = variant.trailing_stop_pct
    for level in sorted(variant.staged_trailing_levels, key=lambda row: row["activation_pct"]):
        if peak_return_pct >= level["activation_pct"]:
            trailing_stop_pct = level["trailing_stop_pct"]
    return trailing_stop_pct


def evaluate_exit_on_bar(
    variant: ExitVariantSpec,
    entry_price: float,
    peak_price: float,
    hold_days: float,
    bar: dict[str, Any],
) -> tuple[str | None, float | None, float, float]:
    """Evaluate variant exit rules on a single daily bar.

    Returns:
    - exit_reason
    - exit_price
    - updated_peak_price
    - updated_peak_return_pct

    Implementation policy:
    1. Update peak_price with today's high before evaluating trailing/break-even state.
    2. Use low for protective exits (stop/trailing/break-even) to avoid optimistic bias.
    3. Use close for time/stalled exits to model end-of-day liquidation.
    4. Keep rule precedence stable across variants for fair comparison.
    """
    day_high = float(bar.get("high") or 0.0)
    day_low = float(bar.get("low") or 0.0)
    day_close = float(bar.get("close") or 0.0)
    updated_peak_price = max(peak_price, day_high, entry_price)
    updated_peak_return_pct = (updated_peak_price - entry_price) / entry_price if entry_price > 0 else 0.0
    current_return_pct = (day_close - entry_price) / entry_price if entry_price > 0 else 0.0

    stop_loss_price = entry_price * (1 + variant.stop_loss_pct)
    if day_low <= stop_loss_price:
        return "stop_loss", stop_loss_price, updated_peak_price, updated_peak_return_pct

    if variant.break_even_activation_pct is not None and updated_peak_return_pct >= variant.break_even_activation_pct:
        break_even_price = entry_price * (1 + float(variant.break_even_floor_pct or 0.0))
        if day_low <= break_even_price:
            return "break_even", break_even_price, updated_peak_price, updated_peak_return_pct

    if updated_peak_return_pct >= variant.trailing_activation_pct:
        trailing_stop_pct = trailing_stop_pct_for_variant(variant, updated_peak_return_pct)
        trailing_stop_price = updated_peak_price * (1 - trailing_stop_pct)
        if day_low <= trailing_stop_price:
            return "trailing_stop", trailing_stop_price, updated_peak_price, updated_peak_return_pct

    if (
        variant.stalled_min_hold_days is not None
        and hold_days >= variant.stalled_min_hold_days
        and updated_peak_return_pct < float(variant.stalled_peak_threshold_pct or 0.0)
        and current_return_pct < float(variant.stalled_current_threshold_pct or 0.0)
    ):
        return "stalled_winner", day_close, updated_peak_price, updated_peak_return_pct

    if hold_days >= variant.max_hold_days:
        return "max_hold", day_close, updated_peak_price, updated_peak_return_pct

    return None, None, updated_peak_price, updated_peak_return_pct


def simulate_one_trade_replay(
    trade: dict[str, Any],
    variant: ExitVariantSpec,
    symbol_bars: dict[str, dict[str, Any]],
) -> ClosedTradeReplay | None:
    """Replay one closed trade using daily bars.

    Current implementation choices:
    - Entry is fixed at actual `entry_time` / `entry_price`
    - Replay window ends at the actual exit date
    - Exit checks start from the first trading bar after entry date
    - If no synthetic rule triggers, fall back to actual exit outcome

    This is a conservative first-pass counterfactual and avoids inventing
    extended holding periods beyond the observed trade horizon.
    """
    entry_dt = parse_dt(trade.get("entry_time"))
    actual_exit_dt = parse_dt(trade.get("exit_time"))
    entry_price = float(trade.get("entry_price") or 0.0)
    qty = float(trade.get("qty") or 0.0)
    symbol = str(trade.get("symbol") or "")
    trade_id = str(trade.get("trade_id") or "")

    if not entry_dt or not actual_exit_dt or entry_price <= 0 or qty <= 0 or not symbol:
        return None

    actual_exit_price = float(trade.get("exit_price") or 0.0)
    actual_pnl = float(trade.get("pnl") or 0.0)
    actual_return_pct = (
        float(trade.get("return_pct") or 0.0) * 100.0
        if trade.get("return_pct") is not None
        else ((actual_exit_price - entry_price) / entry_price) * 100.0
        if actual_exit_price > 0
        else None
    )

    peak_price = entry_price
    simulated_exit_reason: str | None = None
    simulated_exit_price: float | None = None
    simulated_exit_time: str | None = None

    entry_date = entry_dt.date().isoformat()
    actual_exit_date = actual_exit_dt.date().isoformat()
    replay_dates = [
        date_str for date_str in sorted(symbol_bars.keys())
        if entry_date < date_str <= actual_exit_date
    ]

    for date_str in replay_dates:
        bar = symbol_bars.get(date_str)
        if not bar:
            continue
        bar_dt = datetime.fromisoformat(f"{date_str}T23:59:59+00:00")
        hold_days = (bar_dt - entry_dt).total_seconds() / 86400.0
        exit_reason, exit_price, peak_price, _peak_return_pct = evaluate_exit_on_bar(
            variant=variant,
            entry_price=entry_price,
            peak_price=peak_price,
            hold_days=hold_days,
            bar=bar,
        )
        if exit_reason and exit_price is not None and exit_price > 0:
            simulated_exit_reason = exit_reason
            simulated_exit_price = exit_price
            simulated_exit_time = bar_dt.isoformat()
            break

    if simulated_exit_price is None:
        simulated_exit_price = actual_exit_price if actual_exit_price > 0 else entry_price
        simulated_exit_time = actual_exit_dt.isoformat()
        simulated_exit_reason = str(trade.get("exit_reason") or "actual_fallback")

    simulated_pnl = (simulated_exit_price - entry_price) * qty
    simulated_return_pct = ((simulated_exit_price - entry_price) / entry_price) * 100.0

    return ClosedTradeReplay(
        trade_id=trade_id,
        symbol=symbol,
        entry_time=entry_dt.isoformat(),
        actual_exit_time=actual_exit_dt.isoformat(),
        actual_exit_price=actual_exit_price,
        actual_pnl=actual_pnl,
        actual_return_pct=actual_return_pct,
        simulated_exit_time=simulated_exit_time,
        simulated_exit_price=simulated_exit_price,
        simulated_pnl=simulated_pnl,
        simulated_return_pct=simulated_return_pct,
        simulated_exit_reason=simulated_exit_reason,
        pnl_delta=simulated_pnl - actual_pnl,
    )


def load_price_store(symbols: list[str], start: datetime | None, end: datetime | None) -> dict[str, Any]:
    """Load bar data required for bar-by-bar replay.

    Behavior:
    - Load local daily-bar cache first
    - If cache is empty/incomplete, fetch the full range from Massive
    - Persist fetched bars back into `PriceCache` for deterministic reruns

    Notes:
    - We intentionally fetch the full symbol range instead of per-missing-day repair.
      For this experiment the simpler full-range refresh is more robust and cheaper to reason about.
    - If Massive is unavailable, cached bars are still returned.
    """
    if not symbols:
        return {}

    load_env_file(PROJECT_ROOT / ".env")
    cache = PriceCache(DEFAULT_PRICE_CACHE_DIR)
    fetch_start = (start - timedelta(days=2)) if start else datetime(2026, 1, 1, tzinfo=timezone.utc)
    fetch_end = (end + timedelta(days=25)) if end else datetime.now(timezone.utc)

    massive: MassiveClient | None = None
    try:
        massive = MassiveClient(api_key=os.environ.get("MASSIVE_API_KEY"))
    except Exception:
        massive = None

    price_store: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        bars_by_date = cache.get_price_range(symbol, fetch_start, fetch_end)

        need_fetch = not bars_by_date
        if not need_fetch:
            cached_dates = {day.isoformat() for day in bars_by_date.keys()}
            if fetch_start.date().isoformat() not in cached_dates or fetch_end.date().isoformat() not in cached_dates:
                need_fetch = True

        if need_fetch and massive is not None:
            try:
                fetched_bars = massive.fetch_daily_bars(
                    symbol,
                    fetch_start.date().isoformat(),
                    fetch_end.date().isoformat(),
                    limit=5000,
                )
                for bar in fetched_bars:
                    bar_dt = bar.timestamp.replace(tzinfo=timezone.utc) if bar.timestamp.tzinfo is None else bar.timestamp.astimezone(timezone.utc)
                    price_data = {
                        "open": float(bar.open),
                        "high": float(bar.high),
                        "low": float(bar.low),
                        "close": float(bar.close),
                        "volume": float(bar.volume),
                    }
                    cache._save_to_file(symbol, bar_dt, price_data)
                bars_by_date = cache.get_price_range(symbol, fetch_start, fetch_end)
            except Exception:
                pass

        normalized = [normalize_bar(day, bar) for day, bar in sorted(bars_by_date.items(), key=lambda item: item[0])]
        price_store[symbol] = normalized
    return price_store


def replay_closed_trades(
    trades: list[dict[str, Any]],
    variant: ExitVariantSpec,
    price_store: dict[str, Any],
) -> VariantComparison:
    """Replay each closed trade using variant exit logic.

    Implementation policy for the full version:
    - Treat actual `entry_time` / `entry_price` as fixed
    - Replay forward on daily bars only (first pass)
    - Start checking exits from entry_date + 1 day
    - Use peak_price derived from observed highs since entry
    - Use `evaluate_exit_on_bar()` for all rule decisions
    - If no rule triggers before actual exit window ends, force-close at actual exit close/date
      so every replay yields a deterministic trade result

    This avoids look-ahead bias while still giving a practical counterfactual comparison.
    """
    changed: list[ClosedTradeReplay] = []
    price_lookup = build_price_lookup(price_store)
    simulated_rows: list[ClosedTradeReplay] = []
    skipped_count = 0

    for trade in trades:
        symbol = str(trade.get("symbol") or "")
        replay = simulate_one_trade_replay(trade, variant, price_lookup.get(symbol, {}))
        if replay is None:
            skipped_count += 1
            continue
        simulated_rows.append(replay)
        if abs(float(replay.pnl_delta or 0.0)) >= 0.01 or replay.simulated_exit_reason != str(trade.get("exit_reason") or ""):
            changed.append(replay)

    total_pnls = [float(row.simulated_pnl or 0.0) for row in simulated_rows]
    returns = [float(row.simulated_return_pct or 0.0) for row in simulated_rows]
    hold_days = []
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    for row in simulated_rows:
        pnl = float(row.simulated_pnl or 0.0)
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            gross_loss += abs(pnl)
        entry_dt = parse_dt(row.entry_time)
        exit_dt = parse_dt(row.simulated_exit_time)
        if entry_dt and exit_dt:
            hold_days.append((exit_dt - entry_dt).total_seconds() / 86400.0)

    metrics = VariantMetrics(
        variant_key=variant.key,
        variant_name=variant.name,
        trade_count=len(simulated_rows),
        win_rate=(wins / len(simulated_rows) * 100.0) if simulated_rows else 0.0,
        total_pnl=sum(total_pnls),
        avg_pnl=(sum(total_pnls) / len(total_pnls)) if total_pnls else 0.0,
        avg_return_pct=mean(returns) if returns else 0.0,
        avg_hold_days=mean(hold_days) if hold_days else 0.0,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else 0.0,
        notes=[
            f"Replayed {len(simulated_rows)} trades using daily-bar first-pass logic.",
            f"Loaded cached bars for {sum(1 for bars in price_store.values() if bars)} symbols; skipped {skipped_count} trades.",
        ],
    )

    for row in simulated_rows:
        reason = str(row.simulated_exit_reason or "manual")
        if reason == "stop_loss":
            metrics.stop_loss_count += 1
        elif reason == "take_profit":
            metrics.take_profit_count += 1
        elif "trail" in reason:
            metrics.trailing_count += 1
        elif reason == "max_hold":
            metrics.max_hold_count += 1
        elif reason == "break_even":
            metrics.break_even_count += 1
        elif reason == "stalled_winner":
            metrics.stalled_winner_count += 1
        else:
            metrics.manual_count += 1

    return VariantComparison(spec=variant, metrics=metrics, changed_trades=changed)


def evaluate_open_positions_snapshot(
    open_trades: list[dict[str, Any]],
    variant: ExitVariantSpec,
    broker_snapshot: list[dict[str, Any]] | None = None,
) -> list[OpenPositionDecision]:
    """Evaluate which current open positions each variant would exit now.

    Snapshot policy:
    - Aggregate tracker open trades by symbol
    - Use broker positions for live qty/current_price/avg_entry_price when available
    - Use tracker peak_price if present; otherwise fall back to current_price
    - Reuse `evaluate_exit_on_bar()` with a synthetic bar:
      `high=max(known_peak,current_price), low=current_price, close=current_price`
    """
    tracker_map = aggregate_open_trades(open_trades)
    if broker_snapshot is None:
        broker_snapshot = load_live_broker_snapshot()

    decisions: list[OpenPositionDecision] = []
    broker_map = {
        str(pos.get("symbol") or "").upper(): pos
        for pos in broker_snapshot
        if pos.get("symbol")
    }

    for symbol in sorted(set(tracker_map) | set(broker_map)):
        tracker = tracker_map.get(symbol, {})
        broker = broker_map.get(symbol, {})

        qty = float((broker.get("qty") if broker else None) or tracker.get("qty") or 0.0)
        avg_entry_price = float((broker.get("avg_entry_price") if broker else None) or tracker.get("avg_entry_price") or 0.0)
        current_price = float((broker.get("current_price") if broker else None) or 0.0)
        if qty <= 0 or avg_entry_price <= 0 or current_price <= 0:
            decisions.append(OpenPositionDecision(
                symbol=symbol,
                qty=qty,
                hold_days=None,
                return_pct=None,
                peak_return_pct=None,
                would_exit=False,
                exit_reason="missing_snapshot_data",
            ))
            continue

        entry_time_raw = tracker.get("entry_time")
        entry_dt = parse_dt(entry_time_raw) if entry_time_raw else None
        hold_days = ((datetime.now(timezone.utc) - entry_dt).total_seconds() / 86400.0) if entry_dt else None

        known_peak_price = max(float(tracker.get("peak_price") or 0.0), current_price)
        synthetic_bar = {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "open": current_price,
            "high": known_peak_price,
            "low": current_price,
            "close": current_price,
            "volume": 0.0,
        }
        current_return_pct = ((current_price - avg_entry_price) / avg_entry_price) if avg_entry_price > 0 else None
        peak_return_pct = ((known_peak_price - avg_entry_price) / avg_entry_price) if avg_entry_price > 0 else None

        exit_reason = None
        if hold_days is not None:
            exit_reason, _exit_price, _peak_price, _peak_return = evaluate_exit_on_bar(
                variant=variant,
                entry_price=avg_entry_price,
                peak_price=known_peak_price,
                hold_days=hold_days,
                bar=synthetic_bar,
            )

        decisions.append(OpenPositionDecision(
            symbol=symbol,
            qty=qty,
            hold_days=hold_days,
            return_pct=(current_return_pct * 100.0) if current_return_pct is not None else None,
            peak_return_pct=(peak_return_pct * 100.0) if peak_return_pct is not None else None,
            would_exit=bool(exit_reason),
            exit_reason=exit_reason,
        ))

    return decisions


def print_report(comparisons: list[VariantComparison]) -> None:
    print("\n=== Exit Variant Comparison ===")
    baseline = comparisons[0].metrics if comparisons else None
    print("Variant | Trades | Win% | TotalPnL | ΔvsBase | AvgPnL | AvgRet% | AvgHoldD | ProfitFactor | Changed | OpenExit")
    print("-" * 132)
    for comparison in comparisons:
        m = comparison.metrics
        delta_pnl = (m.total_pnl - baseline.total_pnl) if baseline else 0.0
        open_exit_count = sum(1 for row in comparison.open_position_decisions if row.would_exit)
        print(
            f"{m.variant_key}:{m.variant_name:<24} "
            f"{m.trade_count:>5} "
            f"{m.win_rate:>6.2f}% "
            f"${m.total_pnl:>10.2f} "
            f"{delta_pnl:>+8.2f} "
            f"${m.avg_pnl:>8.2f} "
            f"{m.avg_return_pct:>8.2f}% "
            f"{m.avg_hold_days:>8.2f} "
            f"{m.profit_factor:>12.2f} "
            f"{len(comparison.changed_trades):>7} "
            f"{open_exit_count:>8}"
        )

    for comparison in comparisons:
        print(f"\n--- {comparison.spec.key}:{comparison.spec.name} ---")
        for note in comparison.metrics.notes[:2]:
            print(f"note: {note}")

        changed = sorted(
            comparison.changed_trades,
            key=lambda row: abs(float(row.pnl_delta or 0.0)),
            reverse=True,
        )[:5]
        if changed:
            print("top changed trades:")
            for row in changed:
                print(
                    f"  {row.symbol:<6} pnlΔ={float(row.pnl_delta or 0.0):+8.2f} "
                    f"actual={float(row.actual_pnl or 0.0):+8.2f} sim={float(row.simulated_pnl or 0.0):+8.2f} "
                    f"reason={row.simulated_exit_reason}"
                )
        else:
            print("top changed trades: none")

        open_exits = sorted(
            [row for row in comparison.open_position_decisions if row.would_exit],
            key=lambda row: (float(row.return_pct or -999.0), float(row.hold_days or -999.0)),
            reverse=True,
        )[:10]
        if open_exits:
            print("open positions flagged now:")
            for row in open_exits:
                print(
                    f"  {row.symbol:<6} ret={float(row.return_pct or 0.0):>6.2f}% "
                    f"peak={float(row.peak_return_pct or 0.0):>6.2f}% hold={float(row.hold_days or 0.0):>5.2f}d "
                    f"reason={row.exit_reason}"
                )
        else:
            print("open positions flagged now: none")


def serialize(comparisons: list[VariantComparison]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "variant_count": len(comparisons),
        "comparisons": [
            {
                "spec": asdict(comparison.spec),
                "metrics": asdict(comparison.metrics),
                "changed_trades": [asdict(row) for row in comparison.changed_trades],
                "open_position_decisions": [asdict(row) for row in comparison.open_position_decisions],
            }
            for comparison in comparisons
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare exit variants against current SimpleExitV2 baseline")
    parser.add_argument("--pnl-path", type=Path, default=DEFAULT_PNL_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--start-date", type=str, help="Entry-date lower bound (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="Entry-date upper bound (YYYY-MM-DD)")
    parser.add_argument("--limit-symbols", nargs="*", help="Optional symbol allowlist")
    parser.add_argument("--skip-open-snapshot", action="store_true")
    args = parser.parse_args()

    state = load_pnl_state(args.pnl_path)
    trades = state.get("trades", [])

    start = parse_dt(f"{args.start_date}T00:00:00+00:00") if args.start_date else None
    end = parse_dt(f"{args.end_date}T23:59:59+00:00") if args.end_date else None

    if args.limit_symbols:
        allow = {symbol.upper() for symbol in args.limit_symbols}
        trades = [trade for trade in trades if str(trade.get("symbol") or "").upper() in allow]

    closed_trades = filter_closed_trades(trades, start, end)
    open_trades = filter_open_trades(trades)
    symbols = sorted({str(trade.get("symbol") or "").upper() for trade in closed_trades + open_trades if trade.get("symbol")})
    price_store = load_price_store(symbols, start, end)

    comparisons: list[VariantComparison] = []
    for variant in build_variants():
        comparison = replay_closed_trades(closed_trades, variant, price_store)
        if not args.skip_open_snapshot:
            comparison.open_position_decisions = evaluate_open_positions_snapshot(open_trades, variant)
        comparisons.append(comparison)

    print_report(comparisons)

    payload = serialize(comparisons)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote scaffold comparison artifact: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
