#!/usr/bin/env python3
"""R13-D Phase 2 (2026-08-23): validates that the new production-pattern
code (SectorMomentumFeature + SectorRotationStrategy) reproduces Phase 1's
validated headline result before considering the design "confirmed".

Phase 1 (scripts/r13d_etf_sector_rotation_phase1.py) computed the rotation
result with plain-dict pure functions, deliberately NOT using this
codebase's FeatureResult/CandidateSignal architecture (a fast, throwaway
feasibility check). This script re-runs the SAME top-2/63d/21d rotation
using the ACTUAL SectorMomentumFeature + SectorRotationStrategy classes
that would be wired into paper_demo.py in a future Phase 3, replaying
against the identical real 2-year price cache
(data/r11_price_cache/*.json) used by R13-C and R13-D Phase 1.

This is NOT a new backtest engine -- it is a consistency check: does the
"real" feature/strategy code path (the code that would actually run in
production) produce numbers matching Phase 1's already-validated pure-
function research script? If they diverge, that would indicate a bug in
the feature/strategy wiring introduced when translating Phase 1's
research code into this codebase's architecture.

Usage:
    python scripts/r13d_sector_rotation_feature_strategy_validation.py [--top-n 2]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from stock_swing.core.types import CanonicalRecord  # noqa: E402
from stock_swing.feature_engine.sector_momentum_feature import SectorMomentumFeature  # noqa: E402
from stock_swing.risk.allocation_config import read_symbol_registry  # noqa: E402
from stock_swing.strategy_engine.sector_rotation_strategy import SectorRotationStrategy  # noqa: E402

from r13d_etf_sector_rotation_phase1 import (  # noqa: E402
    load_closes,
    load_sector_map,
    run_rotation,
    summarize_curve,
)

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"


def make_record(symbol: str, date_str: str, close: float) -> CanonicalRecord:
    event_time = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
    return CanonicalRecord(
        record_id=f"r13d_val_{symbol}_{date_str}",
        schema_version="v1",
        source="r11_yfinance_cache",
        source_type="price",
        symbol=symbol,
        event_type="bar_daily",
        event_time=event_time,
        as_of=event_time.isoformat(),
        ingested_at=event_time,
        timezone="UTC",
        payload_version="v1",
        payload={"close": close},
        quality_flags=[],
    )


def replay_with_production_classes(
    sector_map: dict[str, str],
    top_n: int,
    lookback_days: int,
    hold_days: int,
    all_dates: list[str],
) -> list[dict]:
    """Re-run the rotation using SectorMomentumFeature + SectorRotationStrategy
    at each simulated rebalance date, and diff the resulting holdings
    against Phase 1's pure-function trailing_return ranking for the same
    date -- this is the actual point of the check (do the two independently
    written implementations agree?).

    IMPORTANT: `all_dates` must be the SAME date array (and therefore the
    same index-to-date mapping) that Phase 1's own trailing_return() ranking
    uses -- i.e. derived from sector RETURN series (build_sector_daily_
    returns()), not raw close-price dates. Close-price date series has one
    more leading date than the return series (a return needs a prior close
    to compare against), so using a locally-rebuilt close-price-based date
    array here would silently misalign every index by one day relative to
    Phase 1's ranking and produce spurious mismatches unrelated to any real
    inconsistency in the feature/strategy code itself.
    """
    symbol_closes = {sym: load_closes(sym) for sym in sector_map}

    checkpoints = []
    i = lookback_days
    while i < len(all_dates):
        date = all_dates[i]
        # AUDIT-STYLE FIX #1 (2026-08-23, caught by this very consistency
        # check before it was trusted): SectorMomentumFeature computes
        # daily returns INTERNALLY from the close prices it is given, so a
        # `lookback_days`-day return window needs `lookback_days + 1`
        # underlying close prices (the extra one is needed to compute the
        # return for the FIRST day in the window -- you cannot compute a
        # day's % change without also knowing the close from the day
        # before it). This is now documented as a required calling
        # convention in SectorMomentumFeature's docstring as well, for
        # whoever wires this into Phase 3 production code.
        #
        # AUDIT-STYLE FIX #2 (2026-08-23): Phase 1's own trailing_return()
        # uses an EXCLUSIVE end_idx (`dates[end_idx-lookback:end_idx]`),
        # meaning its lookback window for a rebalance evaluated "as of" day
        # `i` uses returns only through day `i-1`'s close-to-close move --
        # it deliberately does NOT include the rebalance day's own return.
        # To reproduce that exactly (not a real bug in Phase 1, just an
        # implementation detail this replay must match to compare
        # apples-to-apples), the close-price window supplied here must
        # likewise stop at day `i-1`, i.e. use dates[i-lookback_days-1 : i]
        # (64 closes spanning indices i-64..i-1, NOT including day i at all).
        window_dates = all_dates[max(0, i - lookback_days - 1) : i]

        records = []
        for sym, closes in symbol_closes.items():
            for d in window_dates:
                if d in closes:
                    records.append(make_record(sym, d, closes[d]))

        feature = SectorMomentumFeature(sector_map=sector_map, lookback_days=lookback_days)
        feature_results = feature.compute(records)

        strategy = SectorRotationStrategy(top_n=top_n)
        signals = strategy.generate(features=feature_results)
        production_holdings = sorted({s.metadata["sector"] for s in signals})

        checkpoints.append({
            "date": date,
            "production_holdings": production_holdings,
            "ranked_sectors": feature_results[0].values.get("ranked_sectors"),
        })
        i += hold_days

    return checkpoints


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--lookback-days", type=int, default=63)
    parser.add_argument("--hold-days", type=int, default=21)
    args = parser.parse_args()

    sector_map = load_sector_map()

    print("=" * 90)
    print("R13-D Phase 2: SectorMomentumFeature + SectorRotationStrategy consistency check")
    print("vs. Phase 1's pure-function research script (scripts/r13d_etf_sector_rotation_phase1.py)")
    print("=" * 90)

    # Build the date array exactly as Phase 1 does (from RETURN series, not
    # raw close-price series) so index-to-date mapping is identical for
    # both the production replay and the Phase 1 cross-check below.
    from r13d_etf_sector_rotation_phase1 import build_sector_daily_returns as _build_returns
    _sector_returns_for_dates, _ = _build_returns(sector_map)
    shared_all_dates = sorted(set().union(*[set(r.keys()) for r in _sector_returns_for_dates.values()]))

    checkpoints = replay_with_production_classes(
        sector_map, top_n=args.top_n, lookback_days=args.lookback_days, hold_days=args.hold_days,
        all_dates=shared_all_dates,
    )

    print(f"\nChecked {len(checkpoints)} rebalance dates. Sample (first 5, last 5):")
    sample = checkpoints[:5] + (["..."] if len(checkpoints) > 10 else []) + checkpoints[-5:]
    for cp in sample:
        if cp == "...":
            print("  ...")
            continue
        print(f"  {cp['date']}: production_holdings={cp['production_holdings']}  "
              f"ranked_top3={cp['ranked_sectors'][:3]}")

    # Cross-check: run Phase 1's own pure-function rotation over the same
    # window and compare final-holdings agreement at each checkpoint date.
    from r13d_etf_sector_rotation_phase1 import build_sector_daily_returns, trailing_return

    sector_returns, sector_members = build_sector_daily_returns(sector_map)
    all_dates = shared_all_dates

    mismatches = 0
    for cp in checkpoints:
        idx = all_dates.index(cp["date"]) if cp["date"] in all_dates else None
        if idx is None:
            continue
        scores = {}
        for sector, rets in sector_returns.items():
            tr = trailing_return(rets, all_dates, idx, args.lookback_days)
            if tr is not None:
                scores[sector] = tr
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        phase1_holdings = sorted([s for s, _ in ranked[: args.top_n]])
        if phase1_holdings != cp["production_holdings"]:
            mismatches += 1
            print(f"\n  ⚠️  MISMATCH at {cp['date']}: phase1={phase1_holdings} "
                  f"vs production={cp['production_holdings']}")

    print("\n" + "-" * 90)
    print("VERDICT")
    print("-" * 90)
    if mismatches == 0:
        print(f"  ✅ All {len(checkpoints)} checkpoints agree between Phase 1's pure-function "
              f"research script and the production-pattern SectorMomentumFeature + "
              f"SectorRotationStrategy classes. Feature/strategy wiring is consistent "
              f"with the validated Phase 1 result.")
    else:
        print(f"  ❌ {mismatches}/{len(checkpoints)} checkpoints disagree -- investigate before "
              f"treating this Phase 2 design as validated.")


if __name__ == "__main__":
    main()
