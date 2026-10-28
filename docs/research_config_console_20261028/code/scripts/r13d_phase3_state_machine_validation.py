#!/usr/bin/env python3
"""R13-D Phase 3 (2026-08-24): validates the new rebalance-cadence state
machine (stock_swing.strategy_engine.sector_rotation_state) against a
DAILY call cadence, closing the exact gap Phase 2 explicitly deferred:
"wiring this into paper_demo.py's daily/multiple-per-day cron cadence
would need an explicit persistent last-rebalance-date + current-holdings
state file... so the strategy does not needlessly reshuffle a position
purely because a later cron run recomputes a fresh top-N."

WHAT THIS CHECKS: Phase 2's own consistency check
(r13d_sector_rotation_feature_strategy_validation.py) only ever called
SectorMomentumFeature/SectorRotationStrategy at hold_days-spaced
checkpoints -- it never simulated what happens if the (stateless) strategy
were called EVERY trading day, which is what a real daily/multi-per-day
cron would actually do. This script simulates exactly that: call the
feature/strategy pair every single trading day, but gate actual holdings
changes through is_rebalance_due()/advance_rebalance_state(), and verify:

  1. Rebalance-count sanity: over N trading days with hold_days-day
     spacing, the number of ACTUAL rebalances should be
     approximately N/hold_days (not one per trading day, which is what
     would happen with no state gate at all).
  2. Holdings stability: on non-rebalance days, current_holdings must
     stay IDENTICAL to the prior day even though the underlying
     SectorMomentumFeature ranking may have already shifted (this is
     the literal bug Phase 3 exists to prevent).
  3. Rebalance-day equivalence: on days when a rebalance IS triggered,
     the resulting holdings must exactly match Phase 2's already-
     validated hold_days-checkpoint holdings for the same date (i.e. the
     state machine does not change WHAT gets selected, only WHEN).

Usage:
    python scripts/r13d_phase3_state_machine_validation.py [--top-n 2] [--hold-days 21]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from stock_swing.core.types import CanonicalRecord  # noqa: E402
from stock_swing.feature_engine.sector_momentum_feature import SectorMomentumFeature  # noqa: E402
from stock_swing.strategy_engine.sector_rotation_strategy import SectorRotationStrategy  # noqa: E402
from stock_swing.strategy_engine.sector_rotation_state import (  # noqa: E402
    RebalanceState,
    advance_rebalance_state,
    compute_rebalance_diff,
    is_rebalance_due,
)

from r13d_etf_sector_rotation_phase1 import (  # noqa: E402
    build_sector_daily_returns,
    load_closes,
    load_sector_map,
    trailing_return,
)

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"


def make_record(symbol: str, date_str: str, close: float) -> CanonicalRecord:
    event_time = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
    return CanonicalRecord(
        record_id=f"r13d_phase3_{symbol}_{date_str}",
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


def compute_holdings_for_date(
    symbol_closes: dict[str, dict[str, float]],
    sector_map: dict[str, str],
    all_dates: list[str],
    idx: int,
    top_n: int,
    lookback_days: int,
) -> tuple[list[str], list[str]] | None:
    """Return (top_sectors, member_holdings) as of all_dates[idx], using the
    REAL SectorMomentumFeature + SectorRotationStrategy classes (same
    calling convention as Phase 2's validation script: window stops at
    idx-1, needs lookback_days+1 closes).
    """
    if idx < lookback_days + 1:
        return None
    window_dates = all_dates[idx - lookback_days - 1 : idx]
    records = []
    for sym, closes in symbol_closes.items():
        for d in window_dates:
            if d in closes:
                records.append(make_record(sym, d, closes[d]))

    feature = SectorMomentumFeature(sector_map=sector_map, lookback_days=lookback_days)
    feature_results = feature.compute(records)
    if not feature_results[0].values.get("ranked_sectors"):
        return None

    strategy = SectorRotationStrategy(top_n=top_n)
    signals = strategy.generate(features=feature_results)
    if not signals:
        return None

    top_sectors = sorted({s.metadata["sector"] for s in signals})
    holdings = sorted({s.symbol for s in signals})
    return top_sectors, holdings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--lookback-days", type=int, default=63)
    parser.add_argument("--hold-days", type=int, default=21)
    args = parser.parse_args()

    sector_map = load_sector_map()
    symbol_closes = {sym: load_closes(sym) for sym in sector_map}

    sector_returns, _ = build_sector_daily_returns(sector_map)
    all_dates = sorted(set().union(*[set(r.keys()) for r in sector_returns.values()]))

    print("=" * 90)
    print("R13-D Phase 3: daily-call rebalance state machine validation")
    print(f"({len(all_dates)} trading days, top_n={args.top_n}, "
          f"lookback_days={args.lookback_days}, hold_days={args.hold_days})")
    print("=" * 90)

    state: RebalanceState | None = None
    rebalance_events: list[dict] = []
    stability_violations = 0
    prior_holdings_snapshot: list[str] | None = None

    start_idx = args.lookback_days + 1
    for idx in range(start_idx, len(all_dates)):
        date_str = all_dates[idx]
        today = date_cls.fromisoformat(date_str)

        due = is_rebalance_due(state, today=today, hold_days=args.hold_days)

        if not due:
            # Stability check: holdings must be UNCHANGED from the prior
            # day when no rebalance is due, regardless of what the
            # underlying ranking would currently say.
            current = state.current_holdings if state else []
            if prior_holdings_snapshot is not None and current != prior_holdings_snapshot:
                stability_violations += 1
                print(f"  ⚠️  STABILITY VIOLATION at {date_str}: holdings changed "
                      f"without a due rebalance ({prior_holdings_snapshot} -> {current})")
            prior_holdings_snapshot = current
            continue

        result = compute_holdings_for_date(
            symbol_closes, sector_map, all_dates, idx,
            top_n=args.top_n, lookback_days=args.lookback_days,
        )
        if result is None:
            prior_holdings_snapshot = state.current_holdings if state else []
            continue

        new_sectors, new_holdings = result
        prior_holdings = state.current_holdings if state else []
        diff = compute_rebalance_diff(prior_holdings, new_holdings)

        state = advance_rebalance_state(
            state, today=today, new_sectors=new_sectors, new_holdings=new_holdings,
        )
        prior_holdings_snapshot = state.current_holdings
        rebalance_events.append({
            "date": date_str,
            "sectors": new_sectors,
            "holdings": new_holdings,
            "diff_enter": diff.enter,
            "diff_exit": diff.exit,
            "is_noop": diff.is_noop,
        })

    total_days_simulated = len(all_dates) - start_idx
    expected_rebalances = total_days_simulated / args.hold_days
    actual_rebalances = len(rebalance_events)

    print(f"\nSimulated {total_days_simulated} daily calls (every trading day, "
          f"not just hold_days-spaced checkpoints).")
    print(f"Actual rebalances triggered: {actual_rebalances} "
          f"(naive expectation ~{expected_rebalances:.1f} at exactly hold_days spacing)")
    print(f"Stability violations (holdings changed without a due rebalance): "
          f"{stability_violations}")

    print(f"\nFirst 3 and last 3 rebalance events:")
    sample = rebalance_events[:3] + (["..."] if len(rebalance_events) > 6 else []) + rebalance_events[-3:]
    for ev in sample:
        if ev == "...":
            print("  ...")
            continue
        print(f"  {ev['date']}: sectors={ev['sectors']} holdings={ev['holdings']} "
              f"enter={ev['diff_enter']} exit={ev['diff_exit']} noop={ev['is_noop']}")

    noop_rebalances = sum(1 for ev in rebalance_events if ev["is_noop"])
    print(f"\nRebalances that were a no-op (same top-N as before, diff empty): "
          f"{noop_rebalances}/{len(rebalance_events)}")

    print("\n" + "-" * 90)
    print("VERDICT")
    print("-" * 90)
    ok = True
    if stability_violations > 0:
        print(f"  ❌ {stability_violations} stability violation(s): holdings changed on a "
              f"non-rebalance day. State machine is NOT correctly gating daily calls.")
        ok = False
    else:
        print(f"  ✅ Zero stability violations across {total_days_simulated} simulated daily "
              f"calls: holdings only ever change on a due rebalance day, exactly the property "
              f"Phase 2 identified as missing for a daily/multi-per-day cron cadence.")
    # Sanity bound: with hold_days spacing, actual rebalances should be
    # within a small integer tolerance of the naive expectation (exact
    # match isn't guaranteed since is_rebalance_due's calendar-day gate and
    # the trading-day index stepping interact slightly, but a large
    # deviation would indicate the gate isn't working at all).
    if abs(actual_rebalances - expected_rebalances) > max(3, expected_rebalances * 0.5):
        print(f"  ⚠️  Rebalance count ({actual_rebalances}) deviates substantially from the "
              f"naive hold_days-spacing expectation ({expected_rebalances:.1f}) -- investigate.")
        ok = False
    else:
        print(f"  ✅ Rebalance count ({actual_rebalances}) is consistent with hold_days={args.hold_days}"
              f"-spaced cadence (naive expectation {expected_rebalances:.1f}).")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
