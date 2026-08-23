#!/usr/bin/env python3
"""R13-C (2026-08-24): rolling walk-forward robustness check for the v3
backtest engine (t+1 fill + point-in-time universe + conservative OHLC
exits + slippage), using roadmap items 6 (rolling walk-forward + embargo)
and 7 (trial registry) together.

WHY: every walk-forward check run so far for this strategy (R11-B's single
50/50 midpoint split, r11b_param_search.py's one-shot 60/20/20 train/
validation/holdout) uses exactly ONE fixed split. The 2026-08-15 R11-B
follow-up review found that a single split's conclusion can depend heavily
on where the cut happens to land (see docs/console_improvement_tasks.md's
"R11-B付鍘" section: a 2-way split hid a mid-2025 correction that a 3-way
split later exposed). This script runs MULTIPLE overlapping-train,
non-overlapping-test rolling windows (via stock_swing.research.
rolling_walk_forward) over the v3 engine's actual trade list, so a reader
can see whether validation-style underperformance is a one-off artifact of
one split point or a recurring pattern across several.

Every roll's train/test PF is also logged to the trial registry (via
stock_swing.research.trial_registry) so this becomes a durable, queryable
record rather than another one-off console printout -- directly closing
the "no durable record of how many trials were run" gap roadmap item 7
was written to fix.

Usage:
    python scripts/r13c_rolling_walk_forward_validation.py [--n-rolls 4] [--embargo-days 20] [--record-trials]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from r11_backtest_engine import load_price_data, summarize  # noqa: E402
from r11_backtest_engine_v3 import run_backtest_v3  # noqa: E402
from stock_swing.research.rolling_walk_forward import (  # noqa: E402
    generate_rolling_splits,
    partition_trades_by_roll,
)
from stock_swing.research.trial_registry import TrialRecord, TrialRegistry  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"


def _pf_val(s: dict) -> float:
    pf = s.get("profit_factor")
    if pf == "inf":
        return float("inf")
    return pf if isinstance(pf, (int, float)) else -1.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--notional", type=float, default=10_000.0)
    parser.add_argument("--slippage-bps", type=float, default=10.0)
    parser.add_argument("--n-rolls", type=int, default=4)
    parser.add_argument("--train-frac", type=float, default=0.5)
    parser.add_argument("--test-frac", type=float, default=0.15)
    parser.add_argument("--embargo-days", type=int, default=20,
                         help="Matches SimpleExitV2Strategy's max_hold_days=20 -- "
                              "the longest a single position can bias train/test adjacency")
    parser.add_argument("--record-trials", action="store_true",
                         help="Log each roll's train/test result to data/research/trial_registry.jsonl")
    parser.add_argument("--no-point-in-time-universe", action="store_true",
                         help="Disable the R13-C universe-intro-date gate. NOTE: as of 2026-08-24 "
                              "every cached symbol's intro_date falls in 2026 (system-tracking-start "
                              "proxy, not a true historical universe-selection date -- see "
                              "r11_symbol_universe_intro_dates.py's docstring), so with the gate "
                              "ENABLED (default), rolling windows whose TRAIN period falls entirely "
                              "before 2026 will show n=0 train trades. That is not a bug in this "
                              "script -- it is an honest consequence of the point-in-time gate combined "
                              "with this system's short symbol-tracking history. Pass this flag to see "
                              "the strategy's regime-robustness on the FULL 2-year price history "
                              "instead (re-introducing the survivorship bias item 2 exists to remove, "
                              "documented tradeoff -- use both views together, not in isolation).")
    args = parser.parse_args()

    if args.symbols:
        symbols = args.symbols.split(",")
    else:
        symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_"))

    print(f"Running v3 backtest engine once over {len(symbols)} symbols "
          f"(t+1 fill + point-in-time universe + conservative OHLC exits + "
          f"{args.slippage_bps}bp one-way slippage)...")
    result = run_backtest_v3(
        symbols, notional=args.notional,
        enforce_point_in_time_universe=not args.no_point_in_time_universe,
        conservative_ohlc=True,
        slippage_bps=args.slippage_bps,
    )
    trades = result["trades"]
    overall = summarize(trades, "overall")
    print(f"\nTotal trades: {len(trades)}  Overall: n={overall['n']} "
          f"WR={overall.get('win_rate')} PF={overall.get('profit_factor')} net=${overall.get('net_pnl')}")

    price_data = load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))

    splits = generate_rolling_splits(
        all_dates, n_rolls=args.n_rolls, train_frac=args.train_frac,
        test_frac=args.test_frac, embargo_days=args.embargo_days,
    )
    if not splits:
        print("ERROR: date range too short for the requested train/test/embargo fractions", file=sys.stderr)
        sys.exit(1)

    registry = TrialRegistry() if args.record_trials else None

    print(f"\n{'='*90}\nROLLING WALK-FORWARD ({len(splits)} rolls, "
          f"train_frac={args.train_frac}, test_frac={args.test_frac}, "
          f"embargo_days={args.embargo_days})\n{'='*90}")

    roll_rows = []
    for roll in splits:
        parts = partition_trades_by_roll(trades, roll)
        train_s = summarize(parts["train"], f"roll{roll.roll_index}_train")
        test_s = summarize(parts["test"], f"roll{roll.roll_index}_test")
        embargo_n = len(parts["embargo"])

        print(f"\nRoll {roll.roll_index}: train={roll.train} "
              f"embargo={roll.embargo} test={roll.test}")
        print(f"  train: n={train_s['n']:4d} PF={train_s.get('profit_factor')} "
              f"WR={train_s.get('win_rate')} net=${train_s.get('net_pnl')}")
        print(f"  test:  n={test_s['n']:4d} PF={test_s.get('profit_factor')} "
              f"WR={test_s.get('win_rate')} net=${test_s.get('net_pnl')}  "
              f"(embargo_dropped={embargo_n})")

        roll_rows.append({"roll": roll.roll_index, "train": train_s, "test": test_s})

        if registry is not None:
            for segment, s in (("train", train_s), ("test", test_s)):
                registry.record(TrialRecord(
                    script="r13c_rolling_walk_forward_validation.py",
                    roadmap_item="R13-C-item6",
                    params={"n_rolls": args.n_rolls, "train_frac": args.train_frac,
                             "test_frac": args.test_frac, "embargo_days": args.embargo_days,
                             "slippage_bps": args.slippage_bps, "roll_index": roll.roll_index},
                    data_window={"start": roll.train[0] if segment == "train" else roll.test[0],
                                 "end": roll.train[1] if segment == "train" else roll.test[1]},
                    segment=segment,
                    n_trades=s.get("n"),
                    profit_factor=s.get("profit_factor"),
                    win_rate=s.get("win_rate"),
                    net_pnl=s.get("net_pnl"),
                ))

    test_pfs = [_pf_val(r["test"]) for r in roll_rows if r["test"]["n"] > 0]
    n_test_pf_above_1 = sum(1 for pf in test_pfs if pf > 1.0)
    print(f"\n{'='*90}\nSUMMARY: {n_test_pf_above_1}/{len(test_pfs)} rolls had test-window PF > 1.0\n{'='*90}")
    if test_pfs:
        print(f"Test-window PFs across rolls: {[round(pf, 3) if pf != float('inf') else 'inf' for pf in test_pfs]}")

    if registry is not None:
        total_trials = registry.count_trials(roadmap_item="R13-C-item6")
        print(f"\nTrial registry: {total_trials} total R13-C-item6 trials recorded at {registry.path}")


if __name__ == "__main__":
    main()
