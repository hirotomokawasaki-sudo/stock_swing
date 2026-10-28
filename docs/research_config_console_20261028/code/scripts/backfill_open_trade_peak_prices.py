#!/usr/bin/env python3
"""Backfill peak_price for open tracker trades from historical price data.

Phase B strategy:
- entry day: intraday high after entry time
- intermediate full days: daily highs
- today: intraday high
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        import os
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(project_root / ".env")

from stock_swing.sources.massive_client import MassiveBar, MassiveClient
from stock_swing.tracking.pnl_tracker import PnLTracker


def _parse_iso(value: str) -> datetime:
    return _ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _parse_as_of(value: str) -> datetime:
    return _parse_iso(value)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass
class PeakBackfillComponents:
    entry_price: float
    prior_peak: float
    entry_day_peak: float | None
    intermediate_daily_peak: float | None
    today_intraday_peak: float | None


@dataclass
class PeakBackfillResult:
    new_peak: float
    components: PeakBackfillComponents


MinuteCache = dict[tuple[str, str, int], list[MassiveBar]]
DailyCache = dict[tuple[str, str, str], list[MassiveBar]]


def _max_high_from_daily_bars(bars: list[MassiveBar]) -> float | None:
    highs = [float(bar.high) for bar in bars]
    return max(highs) if highs else None



def _max_high_from_minute_bars(
    bars: list[MassiveBar],
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
) -> float | None:
    highs: list[float] = []
    for bar in bars:
        ts = _ensure_utc(bar.timestamp)
        if start_dt and ts < start_dt:
            continue
        if end_dt and ts > end_dt:
            continue
        highs.append(float(bar.high))
    return max(highs) if highs else None



def get_minute_bars_cached(
    client: MassiveClient,
    cache: MinuteCache,
    symbol: str,
    day: date,
    minute_multiplier: int,
) -> list[MassiveBar]:
    key = (symbol, day.isoformat(), minute_multiplier)
    if key not in cache:
        cache[key] = client.fetch_minute_bars(
            symbol,
            from_date=day.isoformat(),
            to_date=day.isoformat(),
            multiplier=minute_multiplier,
        )
    return cache[key]



def get_daily_bars_cached(
    client: MassiveClient,
    cache: DailyCache,
    symbol: str,
    from_day: date,
    to_day: date,
) -> list[MassiveBar]:
    key = (symbol, from_day.isoformat(), to_day.isoformat())
    if key not in cache:
        cache[key] = client.fetch_daily_bars(symbol, from_day.isoformat(), to_day.isoformat())
    return cache[key]



def fetch_entry_day_intraday_peak(
    client: MassiveClient,
    minute_cache: MinuteCache,
    symbol: str,
    entry_time: datetime,
    minute_multiplier: int,
) -> float | None:
    bars = get_minute_bars_cached(client, minute_cache, symbol, entry_time.date(), minute_multiplier)
    return _max_high_from_minute_bars(bars, start_dt=entry_time)



def fetch_intermediate_daily_peak(
    client: MassiveClient,
    daily_cache: DailyCache,
    symbol: str,
    start_day: date,
    end_day: date,
) -> float | None:
    if start_day > end_day:
        return None
    bars = get_daily_bars_cached(client, daily_cache, symbol, start_day, end_day)
    return _max_high_from_daily_bars(bars)



def fetch_today_intraday_peak(
    client: MassiveClient,
    minute_cache: MinuteCache,
    symbol: str,
    today_utc: date,
    minute_multiplier: int,
) -> float | None:
    bars = get_minute_bars_cached(client, minute_cache, symbol, today_utc, minute_multiplier)
    return _max_high_from_minute_bars(bars)



def compute_effective_peak_price(
    *,
    entry_price: float,
    prior_peak: float,
    entry_day_peak: float | None,
    intermediate_daily_peak: float | None,
    today_intraday_peak: float | None,
) -> PeakBackfillResult:
    components = PeakBackfillComponents(
        entry_price=entry_price,
        prior_peak=prior_peak,
        entry_day_peak=entry_day_peak,
        intermediate_daily_peak=intermediate_daily_peak,
        today_intraday_peak=today_intraday_peak,
    )
    candidates = [
        components.entry_price,
        components.prior_peak,
        components.entry_day_peak,
        components.intermediate_daily_peak,
        components.today_intraday_peak,
    ]
    new_peak = max(float(x) for x in candidates if x is not None)
    return PeakBackfillResult(new_peak=new_peak, components=components)



def backfill_trade_peak(
    *,
    client: MassiveClient,
    minute_cache: MinuteCache,
    daily_cache: DailyCache,
    trade: dict[str, Any],
    now_utc: datetime,
    minute_multiplier: int,
    use_intraday_entry: bool,
    use_intraday_today: bool,
) -> PeakBackfillResult:
    entry_time = _parse_iso(str(trade["entry_time"]))
    entry_day = entry_time.date()
    today_utc = now_utc.date()

    entry_price = float(trade.get("entry_price") or 0)
    prior_peak = float(trade.get("peak_price") or entry_price)

    entry_day_peak = None
    intermediate_daily_peak = None
    today_intraday_peak = None

    if entry_day == today_utc:
        if use_intraday_entry:
            entry_day_peak = fetch_entry_day_intraday_peak(
                client, minute_cache, str(trade.get("symbol") or ""), entry_time, minute_multiplier
            )
        return compute_effective_peak_price(
            entry_price=entry_price,
            prior_peak=prior_peak,
            entry_day_peak=entry_day_peak,
            intermediate_daily_peak=None,
            today_intraday_peak=None,
        )

    if use_intraday_entry:
        entry_day_peak = fetch_entry_day_intraday_peak(
            client, minute_cache, str(trade.get("symbol") or ""), entry_time, minute_multiplier
        )

    mid_start = entry_day + timedelta(days=1)
    mid_end = today_utc - timedelta(days=1)
    intermediate_daily_peak = fetch_intermediate_daily_peak(
        client,
        daily_cache,
        str(trade.get("symbol") or ""),
        mid_start,
        mid_end,
    )

    if use_intraday_today:
        today_intraday_peak = fetch_today_intraday_peak(
            client,
            minute_cache,
            str(trade.get("symbol") or ""),
            today_utc,
            minute_multiplier,
        )

    return compute_effective_peak_price(
        entry_price=entry_price,
        prior_peak=prior_peak,
        entry_day_peak=entry_day_peak,
        intermediate_daily_peak=intermediate_daily_peak,
        today_intraday_peak=today_intraday_peak,
    )



def _parse_symbol_filter(raw: str) -> set[str]:
    return {part.strip().upper() for part in raw.split(",") if part.strip()}



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", action="store_true", help="Create a timestamped pnl_state backup before writing")
    parser.add_argument("--intraday-entry", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--intraday-today", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--minute-multiplier", type=int, default=5)
    parser.add_argument("--symbols", type=str, default="")
    parser.add_argument("--as-of", type=str, default="", help="UTC timestamp used as the effective current time")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tracker = PnLTracker(project_root)
    open_trades = tracker.get_open_positions()
    if not open_trades:
        print("No open trades found. Nothing to backfill.")
        return 0

    symbol_filter = _parse_symbol_filter(args.symbols)
    if symbol_filter:
        open_trades = [t for t in open_trades if str(t.get("symbol") or "").upper() in symbol_filter]
        if not open_trades:
            print("No matching open trades after --symbols filter.")
            return 0

    if args.backup and not args.dry_run and tracker.state_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = tracker.state_path.with_name(f"pnl_state_peak_backfill_backup_{stamp}.json")
        shutil.copy2(tracker.state_path, backup_path)
        print(f"Backup created: {backup_path}")

    client = MassiveClient()
    now_utc = _parse_as_of(args.as_of) if args.as_of else datetime.now(UTC)
    minute_cache: MinuteCache = {}
    daily_cache: DailyCache = {}

    trades_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in open_trades:
        symbol = str(trade.get("symbol") or "")
        entry_time = trade.get("entry_time")
        if symbol and entry_time:
            trades_by_symbol[symbol].append(trade)

    updated = 0
    for symbol, trades in sorted(trades_by_symbol.items()):
        for trade in trades:
            entry_time = _parse_iso(str(trade["entry_time"]))
            prior_peak = float(trade.get("peak_price") or trade.get("entry_price") or 0)
            result = backfill_trade_peak(
                client=client,
                minute_cache=minute_cache,
                daily_cache=daily_cache,
                trade=trade,
                now_utc=now_utc,
                minute_multiplier=args.minute_multiplier,
                use_intraday_entry=args.intraday_entry,
                use_intraday_today=args.intraday_today,
            )
            new_peak = result.new_peak
            if abs(new_peak - prior_peak) > 1e-9:
                updated += 1
                print(
                    f"UPDATED {symbol} trade={trade.get('trade_id')} entry={entry_time.isoformat()} "
                    f"peak {prior_peak:.2f} -> {new_peak:.2f} "
                    f"[entry_intraday={result.components.entry_day_peak} "
                    f"mid_daily={result.components.intermediate_daily_peak} "
                    f"today_intraday={result.components.today_intraday_peak}]"
                )
                if not args.dry_run:
                    trade["peak_price"] = new_peak

    if updated and not args.dry_run:
        tracker.state.last_updated = now_utc.isoformat()
        tracker._save_state()  # internal write path reused intentionally for maintenance script
    print(f"Backfill complete. Updated open trades: {updated} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
