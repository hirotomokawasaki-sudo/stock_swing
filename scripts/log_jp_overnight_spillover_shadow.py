#!/usr/bin/env python3
"""Daily shadow-signal logger for the JP overnight-spillover hypothesis.

See docs/jp_semiconductor_ai_expansion_plan.md (Phase 2.5) and
src/stock_swing/strategy_engine/overnight_spillover_shadow.py for context.

This script:
  1. Fetches the most recent completed US benchmark (SOXX) daily return via
     Yahoo Finance.
  2. Evaluates each JP candidate symbol against that return using
     evaluate_overnight_spillover_signal().
  3. Also backfills jp_open_gap_pct for the *previous* shadow record of each
     symbol (if the JP market has opened since then and the actual gap is
     now observable), so shadow records eventually get an outcome attached
     for forward-validation review.
  4. Appends structured JSON records to
     data/jp_overnight_spillover_shadow_log.jsonl via log_shadow().

Does NOT submit any order, does NOT require any broker connection, and is
NOT wired into paper_demo.py. Intended to be run once per day via cron,
after JPX market open (e.g. 09:15 JST), so that jp_open_gap_pct backfill for
the previous day's signals has real data available.

Usage:
    python scripts/log_jp_overnight_spillover_shadow.py [--threshold 2.0] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance is required. pip install yfinance", file=sys.stderr)
    sys.exit(1)

from stock_swing.strategy_engine.overnight_spillover_shadow import (
    DEFAULT_LARGE_MOVE_THRESHOLD_PCT,
    JP_CANDIDATE_TIERS,
    SHADOW_LOG_RELATIVE,
    evaluate_overnight_spillover_signal,
    log_shadow,
)

US_BENCHMARK_SYMBOL = "SOXX"


def fetch_latest_us_benchmark_return(symbol: str) -> float | None:
    """Fetch the most recently completed daily return for the US benchmark."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="10d", interval="1d", auto_adjust=True)
        if hist is None or len(hist) < 2:
            return None
        closes = hist["Close"]
        latest_return = (closes.iloc[-1] / closes.iloc[-2] - 1) * 100
        # NaN guard (2026-09-04 regression fix): yfinance can return a
        # half-formed latest row (NaN close, e.g. pre-market placeholder),
        # producing a NaN return that passes the `is None` check downstream
        # and corrupts the shadow log with would_signal=True garbage.
        import math
        if math.isnan(float(latest_return)):
            print(f"WARNING: {symbol} latest return is NaN (half-formed row), skipping", file=sys.stderr)
            return None
        return float(latest_return)
    except Exception as exc:
        print(f"WARNING: failed to fetch {symbol}: {exc}", file=sys.stderr)
        return None


def fetch_jp_open_gap(symbol: str) -> float | None:
    """Fetch the most recent overnight gap (today's open vs prior close) for
    a JP symbol, if available."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d", interval="1d", auto_adjust=True)
        if hist is None or len(hist) < 2:
            return None
        prior_close = hist["Close"].iloc[-2]
        latest_open = hist["Open"].iloc[-1]
        if prior_close <= 0:
            return None
        return float((latest_open / prior_close - 1) * 100)
    except Exception as exc:
        print(f"WARNING: failed to fetch JP gap for {symbol}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_LARGE_MOVE_THRESHOLD_PCT,
        help="Large-move threshold pct for the US benchmark (default matches Phase 1)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be logged without writing to the shadow log file",
    )
    args = parser.parse_args()

    print(f"=== JP Overnight Spillover Shadow Signal Logger (Phase 2.5) ===")
    print(f"US benchmark: {US_BENCHMARK_SYMBOL}, threshold={args.threshold}%\n")

    us_return = fetch_latest_us_benchmark_return(US_BENCHMARK_SYMBOL)
    if us_return is None:
        print("ERROR: could not fetch US benchmark return, aborting.", file=sys.stderr)
        return 1

    print(f"Latest {US_BENCHMARK_SYMBOL} daily return: {us_return:+.2f}%\n")

    shadow_log_path = None if args.dry_run else (PROJECT_ROOT / SHADOW_LOG_RELATIVE)

    signals = []
    for symbol in JP_CANDIDATE_TIERS:
        jp_gap = fetch_jp_open_gap(symbol)
        result = evaluate_overnight_spillover_signal(
            symbol,
            US_BENCHMARK_SYMBOL,
            us_return,
            threshold_pct=args.threshold,
            jp_open_gap_pct=jp_gap,
        )
        signals.append(result)
        log_shadow(result, shadow_log_path=shadow_log_path)

        gap_str = f"{jp_gap:+.2f}%" if jp_gap is not None else "n/a"
        print(
            f"  {symbol:<10} would_signal={result.would_signal!s:<6} "
            f"direction={result.direction:<5} strength={result.signal_strength:.3f} "
            f"jp_open_gap={gap_str:<8} | {result.reason}"
        )

    n_signals = sum(1 for s in signals if s.would_signal)
    print(f"\n{n_signals}/{len(signals)} symbols would have received a BUY signal today.")

    if args.dry_run:
        print("\n(--dry-run: nothing was written to the shadow log)")
    else:
        print(f"\nAppended {len(signals)} records to {shadow_log_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
