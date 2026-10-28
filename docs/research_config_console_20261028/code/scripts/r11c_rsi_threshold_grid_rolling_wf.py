#!/usr/bin/env python3
"""R11-C RSI-reversed candidate: threshold grid search + rolling walk-forward
robustness check (2026-08-26 follow-up to r11c_v2_rigorous_rerun.py).

Background: r11c_v2_rigorous_rerun.py re-tested the 4 original R11-C
candidates on the rigorous v4 engine (t+1 fill, PIT universe, conservative
OHLC exit, slippage, portfolio caps) and found the RSI-reversed filter
(single threshold=75.0) reversed the 2026-08-15 "reject" verdict: +16%
overall PF, and ~1.8x better degradation resistance in the back-half
walk-forward window vs. baseline. That result used ONE threshold and ONE
midpoint train/test split -- exactly the two things this codebase's own
established anti-pattern checklist (R13-A/B's "single-trade dependency",
R11-B follow-up's "single split can hide regime dependence") warns against
trusting in isolation.

This script closes both gaps for the RSI-reversed candidate specifically:
  1. Threshold grid search (60/65/70/75/80/85) -- to check whether the
     75.0 result is a stable property of "skip already-overbought entries"
     or a threshold-specific artifact.
  2. Rolling walk-forward (stock_swing.research.rolling_walk_forward,
     the SAME module R13-C item 6 used) -- multiple overlapping-train,
     non-overlapping-test windows with an embargo gap, instead of one
     midpoint split.

PRE-REGISTERED evaluation criteria (fixed BEFORE running, to avoid
post-hoc cherry-picking of whichever threshold looks best after the fact):
  - A threshold is "supported" only if: (a) test-window PF >= baseline
    test-window PF in a MAJORITY of rolls (>=3 of 4 default rolls), AND
    (b) overall (all-window) PF does not fall below baseline's overall PF.
  - The grid's headline threshold remains 75.0 (the R11-C original design
    choice, not re-selected after seeing results) -- other thresholds are
    reported for context/robustness, not to hunt for a better number.

This script does NOT modify position_sizing.py, entry_filter.py, or any
production strategy file. Read-only research artifact.

Usage:
    python scripts/r11c_rsi_threshold_grid_rolling_wf.py --save
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from r11_backtest_engine import load_price_data, summarize  # noqa: E402
from r11c_candidate_backtest import build_rsi_reversed_filter  # noqa: E402
from r11c_v2_rigorous_rerun import (  # noqa: E402
    run_backtest_v4_filtered,
    load_symbol_registry,
)
from r11_backtest_engine_v4 import CACHE_DIR  # noqa: E402
from stock_swing.research.rolling_walk_forward import (  # noqa: E402
    generate_rolling_splits,
    partition_trades_by_roll,
)

REGISTRY_PATH = PROJECT_ROOT / "config" / "reference" / "symbol_registry.yaml"

# Pre-registered grid. 75.0 is the original R11-C design choice (kept as
# the headline/reference point); the rest bracket it symmetrically.
THRESHOLD_GRID = [60.0, 65.0, 70.0, 75.0, 80.0, 85.0]


def _pf(s: dict) -> float:
    pf = s.get("profit_factor")
    if pf == "inf":
        return float("inf")
    return pf if isinstance(pf, (int, float)) else -1.0


def run_one_threshold(
    symbols: list[str],
    threshold: float,
    notional: float,
    equity_base: float,
    slippage_bps: float,
) -> dict[str, Any]:
    entry_filter = build_rsi_reversed_filter(symbols, threshold=threshold)
    result = run_backtest_v4_filtered(
        symbols=symbols,
        notional=notional,
        equity_base=equity_base,
        entry_filter=entry_filter,
        enforce_point_in_time_universe=True,
        conservative_ohlc=True,
        slippage_bps=slippage_bps,
        enforce_caps=True,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="R11-C RSI-reversed: threshold grid + rolling walk-forward")
    parser.add_argument("--notional", type=float, default=10_000.0)
    parser.add_argument("--equity-base", type=float, default=1_000_000.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--n-rolls", type=int, default=4)
    parser.add_argument("--train-frac", type=float, default=0.5)
    parser.add_argument("--test-frac", type=float, default=0.15)
    parser.add_argument("--embargo-days", type=int, default=20,
                         help="Matches SimpleExitV2Strategy's max_hold_days=20")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    registry = load_symbol_registry(REGISTRY_PATH)
    cached_symbols = {p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_")}
    symbols = sorted(set(registry.keys()) & cached_symbols)
    print(f"Universe: {len(symbols)} symbols (registry \u2229 cached price data)")

    # --- Baseline (no RSI filter) run, once, shared across all thresholds ---
    print("\nRunning BASELINE (no filter, v4 rigorous engine)...")
    baseline_result = run_backtest_v4_filtered(
        symbols=symbols, notional=args.notional, equity_base=args.equity_base,
        entry_filter=None, enforce_point_in_time_universe=True,
        conservative_ohlc=True, slippage_bps=args.slippage_bps, enforce_caps=True,
    )
    baseline_trades = baseline_result["trades"]
    baseline_overall = summarize(baseline_trades, "baseline_overall")
    print(f"  Overall: n={baseline_overall['n']} WR={baseline_overall.get('win_rate')} "
          f"PF={baseline_overall.get('profit_factor')} net=${baseline_overall.get('net_pnl')}")

    price_data = load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))

    splits = generate_rolling_splits(
        all_dates, n_rolls=args.n_rolls, train_frac=args.train_frac,
        test_frac=args.test_frac, embargo_days=args.embargo_days,
    )
    if not splits:
        print("ERROR: date range too short for requested train/test/embargo fractions", file=sys.stderr)
        return 1
    print(f"\nGenerated {len(splits)} rolling walk-forward splits "
          f"(train_frac={args.train_frac}, test_frac={args.test_frac}, embargo_days={args.embargo_days})")

    baseline_parts_by_roll = [partition_trades_by_roll(baseline_trades, roll) for roll in splits]
    baseline_test_summaries_by_roll = [
        summarize(parts["test"], f"baseline_roll{i}_test")
        for i, parts in enumerate(baseline_parts_by_roll)
    ]
    baseline_test_pf_by_roll = [_pf(s) for s in baseline_test_summaries_by_roll]
    baseline_result_test_n_by_roll = [s.get("n", 0) for s in baseline_test_summaries_by_roll]
    print(f"Baseline test-window PF by roll: {[round(p, 4) if p != float('inf') else 'inf' for p in baseline_test_pf_by_roll]}")
    print(f"Baseline test-window n by roll:  {baseline_result_test_n_by_roll}")
    n_uncomparable_rolls = sum(1 for n in baseline_result_test_n_by_roll if n == 0)
    if n_uncomparable_rolls:
        print(f"  \u26a0\ufe0f  {n_uncomparable_rolls}/{len(splits)} roll(s) have ZERO baseline test-window trades "
              f"(point-in-time universe intro_dates are all 2026 -- see r13c_rolling_walk_forward_"
              f"validation.py's --no-point-in-time-universe docstring for the same root cause). "
              f"These rolls are EXCLUDED from criterion (a)'s comparable-roll count below, not "
              f"silently counted as a win for either side.")

    all_results: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "v4 rigorous engine (t+1 fill, PIT universe, conservative OHLC exit, "
                        "slippage, gross/sector/cluster caps) + rolling walk-forward with embargo",
        "pre_registered_criteria": (
            "A threshold is 'supported' only if (a) test-window PF >= baseline test-window PF "
            "in a majority of rolls, AND (b) overall PF does not fall below baseline overall PF. "
            "75.0 is the headline/reference threshold (R11-C's original design choice), not "
            "re-selected after seeing results."
        ),
        "slippage_bps": args.slippage_bps,
        "rolling_wf_config": {
            "n_rolls": args.n_rolls, "train_frac": args.train_frac,
            "test_frac": args.test_frac, "embargo_days": args.embargo_days,
        },
        "baseline": {
            "overall": baseline_overall,
            "test_pf_by_roll": baseline_test_pf_by_roll,
            "rolls": [
                {"roll": i, "train": splits[i].train, "test": splits[i].test,
                 "test_summary": summarize(baseline_parts_by_roll[i]["test"], f"baseline_roll{i}_test")}
                for i in range(len(splits))
            ],
        },
        "thresholds": {},
    }

    print(f"\n{'='*100}\nTHRESHOLD GRID: {THRESHOLD_GRID}\n{'='*100}")

    for threshold in THRESHOLD_GRID:
        print(f"\nRunning threshold={threshold}...")
        result = run_one_threshold(
            symbols, threshold, args.notional, args.equity_base, args.slippage_bps,
        )
        trades = result["trades"]
        overall = summarize(trades, f"rsi_{threshold}_overall")

        roll_rows = []
        rolls_beating_baseline = 0
        rolls_comparable = 0  # BUG FIX (self-caught, 2026-08-26): rolls where
        # BOTH baseline and candidate had zero test-window trades (test_pf
        # falls back to the sentinel -1.0 for both) were being counted as
        # "beats baseline" via -1.0 >= -1.0, silently inflating the
        # rolls_beating_baseline count with rolls that carry no actual
        # evidence. This codebase's PIT-universe intro_dates are all in
        # 2026 (see r13c_rolling_walk_forward_validation.py's own --no-
        # point-in-time-universe docstring for the same root cause), so any
        # roll whose test window falls entirely before 2026 has zero
        # eligible symbols and zero trades for EVERY candidate, not just
        # this one. Only count a roll toward criterion (a) if baseline had
        # at least 1 test-window trade (a genuine comparison is possible).
        for i, roll in enumerate(splits):
            parts = partition_trades_by_roll(trades, roll)
            test_s = summarize(parts["test"], f"rsi_{threshold}_roll{i}_test")
            test_pf = _pf(test_s)
            baseline_pf = baseline_test_pf_by_roll[i]
            baseline_test_n = baseline_result_test_n_by_roll[i]
            comparable = baseline_test_n > 0
            beats = comparable and test_pf >= baseline_pf
            if comparable:
                rolls_comparable += 1
                if beats:
                    rolls_beating_baseline += 1
            roll_rows.append({
                "roll": i, "train": roll.train, "test": roll.test,
                "test_summary": test_s, "comparable": comparable, "beats_baseline": beats,
            })

        overall_pf = _pf(overall)
        baseline_overall_pf = _pf(baseline_overall)
        criterion_a = rolls_comparable > 0 and rolls_beating_baseline >= (rolls_comparable // 2 + 1)
        criterion_b = overall_pf >= baseline_overall_pf
        supported = criterion_a and criterion_b

        print(f"  n={overall['n']:4d} overall_PF={overall.get('profit_factor')} "
              f"net=${overall.get('net_pnl')}")
        print(f"  rolls beating baseline test PF: {rolls_beating_baseline}/{rolls_comparable} comparable "
              f"(of {len(splits)} total rolls, {len(splits) - rolls_comparable} had zero baseline trades)")
        print(f"  criterion (a) majority-of-COMPARABLE-rolls beat baseline: {criterion_a}")
        print(f"  criterion (b) overall PF >= baseline overall PF ({baseline_overall_pf}): {criterion_b}")
        print(f"  => SUPPORTED: {supported}")

        all_results["thresholds"][str(threshold)] = {
            "overall": overall,
            "rolls_beating_baseline": rolls_beating_baseline,
            "rolls_comparable": rolls_comparable,
            "n_rolls_total": len(splits),
            "criterion_a_majority": criterion_a,
            "criterion_b_overall_pf": criterion_b,
            "supported": supported,
            "rolls": roll_rows,
        }

    print(f"\n{'='*100}\nSUMMARY (pre-registered criteria)\n{'='*100}")
    print(f"{'threshold':>10} {'n':>6} {'overall_PF':>12} {'rolls_beat':>15} {'supported':>10}")
    for threshold in THRESHOLD_GRID:
        r = all_results["thresholds"][str(threshold)]
        marker = " <== headline (75.0)" if threshold == 75.0 else ""
        beat_str = f"{r['rolls_beating_baseline']}/{r['rolls_comparable']}"
        print(f"{threshold:>10} {r['overall']['n']:>6} {r['overall'].get('profit_factor')!s:>12} "
              f"{beat_str:>15} {str(r['supported']):>10}{marker}")
    print(f"\n(rolls_beat = wins among COMPARABLE rolls only, i.e. rolls where baseline had >=1 "
          f"test-window trade; {n_uncomparable_rolls}/{len(splits)} roll(s) excluded as uncomparable)")

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r11c_rsi_threshold_grid_rolling_wf_20260826"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "results.json"
        out_path.write_text(json.dumps(all_results, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
