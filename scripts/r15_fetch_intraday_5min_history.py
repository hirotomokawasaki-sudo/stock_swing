#!/usr/bin/env python3
"""R15 (2026-08-27): Fetch and cache 2 years of 5-minute intraday OHLCV bars
via the broker API, for a future intraday-aware backtest engine.

Background (2026-08-26 evidence-based-system-audit finding, discussed with
user 2026-08-27): every backtest engine used today (r11_backtest_engine*,
r13c/r13d/r14 variants) simulates on DAILY OHLC bars only (data/
r11_price_cache/*.json, sourced from yfinance), evaluating entries/exits
once per simulated trading day. Production (paper_demo.py) runs 4x/day
(premarket/open/midday/close cron) and evaluates exits against the
broker's REAL-TIME current_price at each run, AND fetches 5-minute
intraday bars for breakout candidates (PAPER_DEMO_USE_INTRADAY=true
default) for a two-stage entry decision -- neither of these production
behaviors has ever been backtested. This script is the data-collection
step (read-only, no production impact) toward closing that gap.

DATA SOURCE: broker.fetch_bars(symbol, timeframe="5Min", start=..., end=...)
-- the SAME BrokerClient method and "iex" feed production's own
fetch_intraday_bars() (paper_demo.py) uses, so this cache reflects the
SAME market-data source/limitations production actually sees (single-
exchange IEX feed, not a consolidated SIP tape -- a known limitation of
the paper account's free data tier, inherited here deliberately for
like-for-like comparison rather than "fixed" with a different, unrealistic
data source).

FETCH STRATEGY: one broker API call per (symbol, calendar month) pair
covering the same 2024-08-15..2026-08-14 window as the existing daily
cache (data/r11_price_cache/), to stay within reasonable per-call bar
counts (~1,700 bars/symbol/month observed) without needing pagination.
Results are cached per-symbol as a single JSON file keyed by ISO-8601
timestamp, mirroring the daily cache's per-symbol-file convention but
under a separate directory (data/r15_intraday_5min_cache/) so it does not
collide with or get confused for the daily cache.

Usage:
    python scripts/r15_fetch_intraday_5min_history.py [--symbols AAPL,MSFT] [--start 2024-08-15] [--end 2026-08-14]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.sources.broker_client import BrokerClient  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "r15_intraday_5min_cache"
REGISTRY_PATH = PROJECT_ROOT / "config" / "reference" / "symbol_registry.yaml"
DAILY_CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"


def load_env(env_file: Path) -> None:
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def load_universe_symbols() -> list[str]:
    """Default universe: symbols already present in the daily price cache
    (data/r11_price_cache/*.json), NOT the full symbol_registry.yaml.

    The registry also includes 11 JP tickers (e.g. '3436.T') added for the
    2026-08-19 JP semiconductor expansion research track -- Alpaca (the
    broker this script's data source uses) is a US-equities-only paper
    account and returns HTTP 400 for any '.T' symbol. Since the daily
    cache used by every existing backtest engine (r11_backtest_engine*,
    r13c/r13d/r14 variants) already excludes JP symbols for the same
    reason (see r11_backtest_engine_v4.py's own "registry \u2229 cached
    price data" universe-intersection pattern), this intraday cache
    matches that same 69-symbol US-only universe by construction rather
    than re-deriving it from the registry and hitting the same 400s again.
    """
    if DAILY_CACHE_DIR.exists():
        cached = sorted(
            p.stem for p in DAILY_CACHE_DIR.glob("*.json")
            if not p.stem.startswith("_")
        )
        if cached:
            return cached
    with open(REGISTRY_PATH) as f:
        registry = yaml.safe_load(f)
    return sorted(s for s in registry["symbols"].keys() if not s.endswith(".T"))


def month_ranges(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Split [start_date, end_date] (YYYY-MM-DD) into calendar-month
    (start_iso, end_iso) UTC pairs suitable for fetch_bars(start=, end=)."""
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    ranges = []
    cur = start
    while cur < end:
        # next month boundary
        if cur.month == 12:
            nxt = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            nxt = cur.replace(month=cur.month + 1, day=1)
        chunk_end = min(nxt, end)
        ranges.append((
            cur.isoformat().replace("+00:00", "Z"),
            chunk_end.isoformat().replace("+00:00", "Z"),
        ))
        cur = chunk_end
    return ranges


def fetch_symbol_intraday(
    broker: BrokerClient,
    symbol: str,
    ranges: list[tuple[str, str]],
    retry: int = 3,
) -> dict[str, dict[str, float]]:
    """Fetch all 5-min bars for one symbol across all month ranges.

    Returns {iso_timestamp: {open, high, low, close, volume}}, deduplicated
    and sorted by construction (dict insertion order follows chronological
    range iteration; caller does not need to re-sort for typical use, but
    keys are ISO strings so sorted() also works if needed).
    """
    bars_by_ts: dict[str, dict[str, float]] = {}
    for start_iso, end_iso in ranges:
        attempt = 0
        while True:
            try:
                env = broker.fetch_bars(symbol, timeframe="5Min", start=start_iso, end=end_iso, limit=10000)
                break
            except Exception as exc:
                # Don't retry a 4xx (e.g. 400 for an unsupported/invalid
                # symbol) -- that's a permanent rejection, not a transient
                # failure, and retrying it 3x with exponential backoff just
                # wastes minutes per bad symbol for no benefit.
                if "400" in str(exc) or "404" in str(exc):
                    print(f"    SKIP: {symbol} {start_iso[:7]} permanent error (no retry): {exc}", file=sys.stderr)
                    env = None
                    break
                attempt += 1
                if attempt > retry:
                    print(f"    WARN: {symbol} {start_iso[:7]} failed after {retry} retries: {exc}", file=sys.stderr)
                    env = None
                    break
                wait = 2 ** attempt
                print(f"    retry {attempt}/{retry} for {symbol} {start_iso[:7]} after {exc} (sleep {wait}s)")
                time.sleep(wait)
        if env is None:
            continue
        payload = env.payload if hasattr(env, "payload") else env
        # BUG FIX (found during full-universe run, 2026-08-26): dict.get("bars", [])
        # only falls back to [] when the KEY is absent -- if Alpaca returns
        # {"bars": None} (observed for symbols with no trading activity in a
        # given month, e.g. a stock not yet listed), .get() returns None
        # (the key IS present), and iterating None raised "'NoneType' object
        # is not iterable", silently failing the entire symbol (all 6
        # first-run failures -- CHPS/CHPX/FRWD/GTOP/NBIS/TTEQ -- were this,
        # not a real API error).
        raw_bars = (payload.get("bars") if isinstance(payload, dict) else payload) or []
        for b in raw_bars:
            ts = b.get("t")
            if not ts:
                continue
            bars_by_ts[ts] = {
                "open": float(b["o"]),
                "high": float(b["h"]),
                "low": float(b["l"]),
                "close": float(b["c"]),
                "volume": float(b.get("v", 0) or 0),
            }
    return bars_by_ts


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch 2y of 5-min intraday bars via broker API")
    parser.add_argument("--symbols", default=None, help="Comma-separated override; default = full universe")
    parser.add_argument("--start", default=None, help="YYYY-MM-DD; default = daily cache's earliest date")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD; default = daily cache's latest date")
    parser.add_argument("--skip-existing", action="store_true", help="Skip symbols already cached")
    args = parser.parse_args()

    load_env(PROJECT_ROOT / ".env")
    api_key = os.environ.get("BROKER_API_KEY")
    api_secret = os.environ.get("BROKER_API_SECRET")
    if not api_key or not api_secret:
        print("ERROR: BROKER_API_KEY and BROKER_API_SECRET must be set", file=sys.stderr)
        return 1

    symbols = args.symbols.split(",") if args.symbols else load_universe_symbols()

    # Determine date range from the existing daily cache by default, so
    # this intraday cache covers EXACTLY the same window as every backtest
    # engine used so far (apples-to-apples comparison).
    start_date, end_date = args.start, args.end
    if start_date is None or end_date is None:
        sample_path = next(DAILY_CACHE_DIR.glob("*.json"), None)
        if sample_path is None:
            print("ERROR: no daily cache files found and --start/--end not given", file=sys.stderr)
            return 1
        sample = json.loads(sample_path.read_text())
        dates = sorted(sample.keys())
        start_date = start_date or dates[0]
        end_date = end_date or dates[-1]

    print(f"Universe: {len(symbols)} symbols")
    print(f"Date range: {start_date} -> {end_date}")

    ranges = month_ranges(start_date, end_date)
    print(f"Month chunks per symbol: {len(ranges)}")
    print(f"Total API calls planned: {len(symbols) * len(ranges)}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)

    ok, failed, skipped = [], [], []
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        out_path = CACHE_DIR / f"{sym}.json"
        if args.skip_existing and out_path.exists():
            skipped.append(sym)
            continue
        try:
            bars = fetch_symbol_intraday(broker, sym, ranges)
            if not bars:
                print(f"  [{i}/{len(symbols)}] {sym:6} -> 0 bars, treating as FAILED")
                failed.append(sym)
                continue
            out_path.write_text(json.dumps(bars, indent=None, sort_keys=True), encoding="utf-8")
            elapsed = time.time() - t0
            print(f"  [{i}/{len(symbols)}] {sym:6} -> {len(bars):6,} bars saved "
                  f"(elapsed {elapsed:.0f}s)")
            ok.append(sym)
        except Exception as exc:
            print(f"  [{i}/{len(symbols)}] {sym:6} -> FAILED: {exc}", file=sys.stderr)
            failed.append(sym)

    total_elapsed = time.time() - t0
    print(f"\nDone in {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"OK: {len(ok)}  FAILED: {len(failed)}  SKIPPED: {len(skipped)}")
    if failed:
        print(f"Failed symbols: {', '.join(failed)}")

    # Manifest for downstream backtest engines to sanity-check coverage.
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_date": start_date,
        "end_date": end_date,
        "symbols_ok": ok,
        "symbols_failed": failed,
        "symbols_skipped": skipped,
        "feed": "iex",
        "timeframe": "5Min",
        "source": "broker.fetch_bars() (same method/feed as production's paper_demo.py fetch_intraday_bars())",
    }
    (CACHE_DIR / "_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
