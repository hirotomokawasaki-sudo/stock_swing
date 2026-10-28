#!/usr/bin/env python3
"""R13-D (2026-08-27): select a new Phase 1 headline config with
--enforce-min-members applied, and validate it the same way the OLD
(buggy) headline was validated in
docs/r13d_etf_sector_rotation_phase1_20260823/robustness_checks.md --
specifically the walk-forward period1/period2 split, which had NOT yet
been re-run for the two min_members-safe candidates identified in
docs/r13d_min_members_check_20260826/README.md:

  - Candidate A: top_n=1, lookback=63d, hold=21d (Sharpe=1.473 full-period)
  - Candidate B: top_n=2, lookback=126d, hold=21d (Sharpe=1.415 full-period)

Per the 08-26 finding ("a single headline-setting GO/NO-GO is fragile to
one implementation bug"), this script explicitly runs the walk-forward
check as a SECOND validation gate before either candidate is adopted as
the new headline -- not just the full-period Sharpe already measured.

This is Phase 1 research only; scripts/r13d_etf_sector_rotation_phase1.py
(the production research script, still unwired to any live trading path)
is imported unmodified, not duplicated.

Usage:
    python scripts/r13d_new_headline_selection.py [--save]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from r13d_etf_sector_rotation_phase1 import (  # noqa: E402
    build_sector_daily_returns,
    equal_weight_all,
    load_closes,
    load_sector_map,
    run_rotation,
    summarize_curve,
)

SPY_SYMBOL = "SPY"


def spy_curve(all_dates: list[str], start_idx: int) -> list[tuple[str, float]]:
    closes = load_closes(SPY_SYMBOL)
    dates = sorted(closes.keys())
    rets = {}
    prev = None
    for d in dates:
        if prev is not None and closes[prev] > 0:
            rets[d] = (closes[d] - closes[prev]) / closes[prev]
        prev = d
    return [(d, rets.get(d, 0.0)) for d in all_dates[start_idx:]]


def run_config(
    sector_returns, sector_members, all_dates, top_n, lookback_days, hold_days,
    date_slice: tuple[str, str] | None = None,
):
    """Run rotation + both baselines over the full range, or restricted to
    a [start_date, end_date] window if date_slice is given (walk-forward
    split), applying --enforce-min-members semantics throughout."""
    start_idx = lookback_days
    dates_in_scope = all_dates
    if date_slice is not None:
        start_d, end_d = date_slice
        dates_in_scope = [d for d in all_dates if start_d <= d <= end_d]
        # need lookback context before the window start for trailing_return
        # to work at the first in-window rebalance; run_rotation walks the
        # full all_dates list internally starting at lookback_days, so we
        # instead post-filter the resulting daily_returns to the window.
    rotation = run_rotation(
        sector_returns, all_dates, top_n=top_n, lookback_days=lookback_days,
        hold_days=hold_days, sector_members=sector_members,
    )
    rot_daily = rotation["daily_returns"]
    ew_daily = equal_weight_all(sector_returns, all_dates, start_idx)
    spy_daily = spy_curve(all_dates, start_idx)

    if date_slice is not None:
        start_d, end_d = date_slice
        rot_daily = [(d, r) for d, r in rot_daily if start_d <= d <= end_d]
        ew_daily = [(d, r) for d, r in ew_daily if start_d <= d <= end_d]
        spy_daily = [(d, r) for d, r in spy_daily if start_d <= d <= end_d]

    return {
        "rotation": summarize_curve(f"rotation_top{top_n}", rot_daily),
        "equal_weight": summarize_curve("equal_weight_all", ew_daily),
        "spy": summarize_curve("spy_buy_hold", spy_daily),
    }


def verdict(result: dict) -> str:
    rot_sharpe = result["rotation"]["sharpe"]
    ew_sharpe = result["equal_weight"]["sharpe"]
    spy_sharpe = result["spy"]["sharpe"]
    if rot_sharpe is None:
        return "NO_DATA"
    beats_ew = ew_sharpe is not None and rot_sharpe > ew_sharpe
    beats_spy = spy_sharpe is not None and rot_sharpe > spy_sharpe
    if beats_ew and beats_spy:
        return "GO"
    if beats_ew or beats_spy:
        return "MIXED"
    return "NO_GO"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    sector_map = load_sector_map()
    sector_returns, sector_members = build_sector_daily_returns(sector_map)
    all_dates = sorted(set().union(*[set(r.keys()) for r in sector_returns.values()]))

    candidates = {
        "candidate_A_top1_63d_21d": dict(top_n=1, lookback_days=63, hold_days=21),
        "candidate_B_top2_126d_21d": dict(top_n=2, lookback_days=126, hold_days=21),
    }

    # Walk-forward split matching robustness_checks.md's original dates
    period1 = ("2024-11-14", "2025-09-30")
    period2 = ("2025-10-01", "2026-08-14")

    output: dict = {"candidates": {}}

    for name, params in candidates.items():
        print(f"\n{'=' * 70}\n{name}: {params}\n{'=' * 70}")

        full = run_config(sector_returns, sector_members, all_dates, **params)
        full_verdict = verdict(full)
        print(f"FULL PERIOD: rotation Sharpe={full['rotation']['sharpe']} "
              f"vs equal_weight={full['equal_weight']['sharpe']} "
              f"vs spy={full['spy']['sharpe']}  => {full_verdict}")

        p1 = run_config(sector_returns, sector_members, all_dates, **params, date_slice=period1)
        p1_verdict = verdict(p1)
        print(f"PERIOD1 ({period1[0]}..{period1[1]}): rotation Sharpe="
              f"{p1['rotation']['sharpe']} vs equal_weight={p1['equal_weight']['sharpe']} "
              f"vs spy={p1['spy']['sharpe']}  => {p1_verdict}")

        p2 = run_config(sector_returns, sector_members, all_dates, **params, date_slice=period2)
        p2_verdict = verdict(p2)
        print(f"PERIOD2 ({period2[0]}..{period2[1]}): rotation Sharpe="
              f"{p2['rotation']['sharpe']} vs equal_weight={p2['equal_weight']['sharpe']} "
              f"vs spy={p2['spy']['sharpe']}  => {p2_verdict}")

        output["candidates"][name] = {
            "params": params,
            "full_period": {**full, "verdict": full_verdict},
            "period1": {**p1, "verdict": p1_verdict},
            "period2": {**p2, "verdict": p2_verdict},
        }

    if args.save:
        out_path = PROJECT_ROOT / "reports" / "r13d_new_headline_selection_results.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
