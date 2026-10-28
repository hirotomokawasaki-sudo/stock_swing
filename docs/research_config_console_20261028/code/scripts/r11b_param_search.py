#!/usr/bin/env python3
"""R11-B follow-up: parameter grid search for BreakoutMomentumStrategy
(min_momentum, min_signal_strength), with strict train/validation/holdout
discipline to avoid the overfitting trap flagged during the R11-C review.

Design (chosen deliberately over re-running separate simulations per
window): each grid point runs ONE full 2-year simulation with fixed
parameters (position state, symbol availability, and the BAR_LIMIT lookback
window all behave identically to R11-B), then the resulting trade list is
partitioned by entry_date into three non-overlapping segments:

    train      (60%, ~14.5 months) -- used for grid search selection
    validation (20%, ~5 months)    -- used for grid search selection
    holdout    (20%, ~5 months)    -- NEVER used for parameter selection;
                                       only unlocked once, at the very end,
                                       to confirm the winning parameter set

Selection rule: among all grid points, keep only those where train PF>1 AND
validation PF>1 (both windows must independently support the parameter set,
not just an average). Among survivors, rank by validation PF (out-of-sample
proxy) -- NOT by train PF, to avoid picking whatever most overfits the
training window. Ties broken by higher combined train+validation trade
count (prefer statistically sturdier candidates).

Usage:
    python scripts/r11b_param_search.py --search     # train+validation only
    python scripts/r11b_param_search.py --confirm    # run winner on holdout
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

import r11_backtest_engine as base  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"

# Grid: current production defaults are min_momentum=0.05, min_signal_strength=0.40
MOMENTUM_GRID = [0.03, 0.05, 0.08, 0.12]
STRENGTH_GRID = [0.30, 0.40, 0.50, 0.60]


def compute_date_segments(all_dates: list[str]) -> dict[str, tuple[str, str]]:
    n = len(all_dates)
    i60 = int(n * 0.6)
    i80 = int(n * 0.8)
    return {
        "train": (all_dates[0], all_dates[i60 - 1]),
        "validation": (all_dates[i60], all_dates[i80 - 1]),
        "holdout": (all_dates[i80], all_dates[-1]),
    }


def run_one(symbols: list[str], min_momentum: float, min_signal_strength: float,
            notional: float = 10000.0) -> dict[str, Any]:
    return base.run_backtest(
        symbols, notional=notional,
        min_momentum=min_momentum, min_signal_strength=min_signal_strength,
    )


def partition_trades(trades: list[dict[str, Any]], segments: dict[str, tuple[str, str]]) -> dict[str, list[dict[str, Any]]]:
    out = {name: [] for name in segments}
    for t in trades:
        entry_date = t["entry_date"]
        for name, (start, end) in segments.items():
            if start <= entry_date <= end:
                out[name].append(t)
                break
    return out


def search(symbols: list[str]) -> dict[str, Any]:
    price_data = base.load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    segments = compute_date_segments(all_dates)
    print(f"Segments: train={segments['train']} validation={segments['validation']} "
          f"holdout={segments['holdout']} (holdout untouched until --confirm)")

    grid_results = []
    for mm in MOMENTUM_GRID:
        for ss in STRENGTH_GRID:
            print(f"\n--- min_momentum={mm} min_signal_strength={ss} ---")
            result = run_one(symbols, mm, ss)
            trades = result["trades"]
            parts = partition_trades(trades, segments)
            train_summary = base.summarize(parts["train"], "train")
            val_summary = base.summarize(parts["validation"], "validation")
            print(f"  train:      {train_summary}")
            print(f"  validation: {val_summary}")
            grid_results.append({
                "min_momentum": mm,
                "min_signal_strength": ss,
                "train": train_summary,
                "validation": val_summary,
            })

    # Selection: both train PF>1 and validation PF>1, rank by validation PF
    def pf_val(s):
        pf = s.get("profit_factor")
        if pf == "inf":
            return float("inf")
        return pf if isinstance(pf, (int, float)) else -1.0

    survivors = [
        r for r in grid_results
        if r["train"]["n"] >= 20 and r["validation"]["n"] >= 10
        and pf_val(r["train"]) > 1.0 and pf_val(r["validation"]) > 1.0
    ]
    survivors.sort(key=lambda r: (pf_val(r["validation"]), r["train"]["n"] + r["validation"]["n"]), reverse=True)

    print("\n=== Grid search summary (all points) ===")
    for r in sorted(grid_results, key=lambda r: -pf_val(r["validation"])):
        print(f"  mm={r['min_momentum']:.2f} ss={r['min_signal_strength']:.2f} "
              f"train_n={r['train']['n']:>4} train_PF={r['train'].get('profit_factor')} "
              f"val_n={r['validation']['n']:>4} val_PF={r['validation'].get('profit_factor')}")

    print(f"\n=== Survivors (train PF>1 AND validation PF>1, n>=20/10) ===")
    for r in survivors:
        print(f"  mm={r['min_momentum']:.2f} ss={r['min_signal_strength']:.2f} "
              f"train_PF={r['train'].get('profit_factor')} val_PF={r['validation'].get('profit_factor')}")

    winner = survivors[0] if survivors else None
    return {
        "segments": segments,
        "grid_results": grid_results,
        "survivors": survivors,
        "winner": winner,
        # current production baseline for comparison
        "production_default": {"min_momentum": 0.05, "min_signal_strength": 0.40},
    }


def confirm(symbols: list[str], search_result_path: Path) -> None:
    data = json.loads(search_result_path.read_text())
    winner = data.get("winner")
    if winner is None:
        print("No winner found in search results (no survivor met criteria). "
              "Nothing to confirm -- production defaults stand unchanged.")
        return

    mm, ss = winner["min_momentum"], winner["min_signal_strength"]
    print(f"Confirming winner on HOLDOUT (never seen during search): "
          f"min_momentum={mm} min_signal_strength={ss}")

    price_data = base.load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    segments = {k: tuple(v) for k, v in data["segments"].items()}

    result = run_one(symbols, mm, ss)
    parts = partition_trades(result["trades"], segments)
    holdout_summary = base.summarize(parts["holdout"], "holdout")
    print(f"\nWinner holdout performance: {holdout_summary}")

    # Also confirm production default on the same holdout for direct comparison
    prod = data["production_default"]
    prod_result = run_one(symbols, prod["min_momentum"], prod["min_signal_strength"])
    prod_parts = partition_trades(prod_result["trades"], segments)
    prod_holdout = base.summarize(prod_parts["holdout"], "production_default_holdout")
    print(f"Production default ({prod}) holdout performance: {prod_holdout}")

    print("\n=== Verdict ===")
    def pf_val(s):
        pf = s.get("profit_factor")
        return float("inf") if pf == "inf" else (pf if isinstance(pf, (int, float)) else -1.0)

    if pf_val(holdout_summary) > pf_val(prod_holdout) and holdout_summary["n"] >= 10:
        print(f"  Winner (mm={mm}, ss={ss}) outperforms production default on untouched holdout.")
        print(f"  RECOMMENDATION: consider updating production parameters (requires user approval).")
    else:
        print(f"  Winner does NOT clearly outperform production default on untouched holdout.")
        print(f"  RECOMMENDATION: keep production parameters unchanged.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--search", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--save", action="store_true", default=True)
    args = parser.parse_args()

    symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json"))
    out_path = PROJECT_ROOT / "reports" / "r11b_param_search_results.json"

    if args.search:
        result = search(symbols)
        with open(out_path, "w") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                **result,
            }, f, indent=2, ensure_ascii=False)
        print(f"\nSaved: {out_path}")
    elif args.confirm:
        if not out_path.exists():
            print("ERROR: run --search first", file=sys.stderr)
            sys.exit(1)
        confirm(symbols, out_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
