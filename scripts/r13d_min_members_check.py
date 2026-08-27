#!/usr/bin/env python3
"""R13-D follow-up (2026-08-26): measure the effect of actually enforcing
`min_members` in the sector-rotation ranking, which
r13d_etf_sector_rotation_phase1.py's `run_rotation()` accepts as a
parameter (default 2) but never references in its body -- confirmed by
reading the function: `eligible_sectors = {s: r for s, r in
sector_returns.items()}` copies ALL sectors unconditionally, ignoring
min_members entirely.

Background (2026-08-26 evidence-based-system-audit finding, Medium):
single-ETF sectors (technology_cloud=SKYY, technology=QQQ,
quantum_computing=QTUM, broad_market=SPY) are ranked and can be selected
for rotation on equal footing with genuinely multi-member sectors
(semiconductor n=7, software n=6), even though the stated intent
(min_members param + docstring's own "with >=2 members to reduce
single-ETF noise" line) was to exclude or de-prioritize them. This script
reuses r13d_etf_sector_rotation_phase1.py's own helper functions
UNCHANGED (build_sector_daily_returns, trailing_return, equal_weight_all,
summarize_curve) and only re-implements run_rotation() with the
min_members filter actually applied, to measure whether the headline
GO-verdict Sharpe numbers change.

This does NOT modify r13d_etf_sector_rotation_phase1.py or any production
file. Read-only research artifact.

Usage:
    python scripts/r13d_min_members_check.py --save
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from r13d_etf_sector_rotation_phase1 import (  # noqa: E402
    build_sector_daily_returns,
    equal_weight_all,
    load_closes,
    load_sector_map,
    summarize_curve,
    trailing_return,
)


def run_rotation_with_min_members(
    sector_returns: dict[str, dict[str, float]],
    sector_members: dict[str, list[str]],
    all_dates: list[str],
    top_n: int,
    lookback_days: int,
    hold_days: int,
    min_members: int = 2,
) -> dict[str, Any]:
    """Same logic as r13d_etf_sector_rotation_phase1.run_rotation(), but
    with min_members ACTUALLY enforced: sectors with fewer than
    min_members tracked ETFs are excluded from ranking/selection entirely
    (matching the docstring's stated intent, which the original function's
    body never implemented).
    """
    eligible_sectors = {
        s: r for s, r in sector_returns.items()
        if len(sector_members.get(s, [])) >= min_members
    }
    excluded_sectors = sorted(set(sector_returns.keys()) - set(eligible_sectors.keys()))

    daily_portfolio_returns: list[tuple[str, float]] = []
    rebalance_log: list[dict[str, Any]] = []

    i = lookback_days
    current_holdings: list[str] = []
    days_since_rebalance = hold_days

    while i < len(all_dates):
        date = all_dates[i]
        if days_since_rebalance >= hold_days:
            scores = {}
            for sector, rets in eligible_sectors.items():
                tr = trailing_return(rets, all_dates, i, lookback_days)
                if tr is not None:
                    scores[sector] = tr
            ranked = sorted(scores.items(), key=lambda x: -x[1])
            current_holdings = [s for s, _ in ranked[:top_n]]
            rebalance_log.append({
                "date": date, "holdings": current_holdings,
                "scores": {s: round(v, 4) for s, v in ranked},
            })
            days_since_rebalance = 0

        if current_holdings:
            day_rets = [
                sector_returns[s].get(date, 0.0) for s in current_holdings
                if date in sector_returns[s]
            ]
            port_ret = sum(day_rets) / len(day_rets) if day_rets else 0.0
        else:
            port_ret = 0.0
        daily_portfolio_returns.append((date, port_ret))
        days_since_rebalance += 1
        i += 1

    return {
        "daily_returns": daily_portfolio_returns,
        "rebalance_log": rebalance_log,
        "excluded_sectors": excluded_sectors,
        "eligible_sectors": sorted(eligible_sectors.keys()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--lookback-days", type=int, default=63)
    parser.add_argument("--hold-days", type=int, default=21)
    parser.add_argument("--min-members", type=int, default=2)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    sector_map = load_sector_map()
    sector_returns, sector_members = build_sector_daily_returns(sector_map)
    print("Sectors tracked:")
    for s, members in sorted(sector_members.items()):
        flag = "" if len(members) >= args.min_members else f"  <-- EXCLUDED (n<{args.min_members})"
        print(f"  {s:20s} n={len(members)}  {members}{flag}")

    all_dates = sorted(set().union(*[set(r.keys()) for r in sector_returns.values()]))
    print(f"\nDate range: {all_dates[0]} -> {all_dates[-1]} ({len(all_dates)} days)")

    # --- Original behavior (min_members NOT enforced, i.e. the actual
    # current headline result) ---
    from r13d_etf_sector_rotation_phase1 import run_rotation as run_rotation_original
    original_result = run_rotation_original(
        sector_returns, all_dates, top_n=args.top_n,
        lookback_days=args.lookback_days, hold_days=args.hold_days,
    )
    start_idx = args.lookback_days
    eq_weight_daily = equal_weight_all(sector_returns, all_dates, start_idx)
    spy_closes = load_closes("SPY")
    spy_dates = sorted(spy_closes.keys())
    spy_returns: dict[str, float] = {}
    prev = None
    for d in spy_dates:
        if prev is not None and spy_closes[prev] > 0:
            spy_returns[d] = (spy_closes[d] - spy_closes[prev]) / spy_closes[prev]
        prev = d
    spy_daily = [(d, spy_returns[d]) for d in all_dates[start_idx:] if d in spy_returns]

    original_summary = summarize_curve("original_min_members_unenforced", original_result["daily_returns"])
    eq_summary = summarize_curve("equal_weight_all_sectors", eq_weight_daily)
    spy_summary = summarize_curve("spy_buy_and_hold", spy_daily)

    # --- Fixed behavior (min_members enforced) ---
    fixed_result = run_rotation_with_min_members(
        sector_returns, sector_members, all_dates, top_n=args.top_n,
        lookback_days=args.lookback_days, hold_days=args.hold_days,
        min_members=args.min_members,
    )
    fixed_summary = summarize_curve(f"fixed_min_members_{args.min_members}", fixed_result["daily_returns"])

    print(f"\nExcluded sectors (min_members={args.min_members}): {fixed_result['excluded_sectors']}")
    print(f"Eligible sectors: {fixed_result['eligible_sectors']}")

    print("\n" + "=" * 90)
    print("COMPARISON: min_members unenforced (current headline) vs enforced (fix)")
    print("=" * 90)
    for r in [original_summary, fixed_summary, eq_summary, spy_summary]:
        print(f"  {r['label']:35s} n={r['n_days']:4d}  total_return={r['total_return_pct']:+7.2f}%  "
              f"CAGR={r['cagr_pct']}%  Sharpe={r['sharpe']}  maxDD={r['max_drawdown_pct']}%")

    print("\n" + "-" * 90)
    print("Rebalance holdings comparison (first 5 rebalances)")
    print("-" * 90)
    print("Original (unenforced):")
    for entry in original_result["rebalance_log"][:5]:
        print(f"  {entry['date']}: {entry['holdings']}")
    print("Fixed (min_members enforced):")
    for entry in fixed_result["rebalance_log"][:5]:
        print(f"  {entry['date']}: {entry['holdings']}")

    print("\n" + "-" * 90)
    print("VERDICT")
    print("-" * 90)
    beats_eq_fixed = (fixed_summary["sharpe"] or -999) > (eq_summary["sharpe"] or -999)
    beats_spy_fixed = (fixed_summary["sharpe"] or -999) > (spy_summary["sharpe"] or -999)
    beats_eq_orig = (original_summary["sharpe"] or -999) > (eq_summary["sharpe"] or -999)
    beats_spy_orig = (original_summary["sharpe"] or -999) > (spy_summary["sharpe"] or -999)
    print(f"  Original (unenforced) beats both baselines: {beats_eq_orig and beats_spy_orig}")
    print(f"  Fixed (min_members enforced) beats both baselines: {beats_eq_fixed and beats_spy_fixed}")
    if (beats_eq_orig and beats_spy_orig) == (beats_eq_fixed and beats_spy_fixed):
        print("  => min_members enforcement does NOT change the GO/NO-GO verdict.")
    else:
        print("  \u26a0\ufe0f  min_members enforcement CHANGES the GO/NO-GO verdict -- investigate further.")

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r13d_min_members_check_20260826"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "results.json"
        out_path.write_text(json.dumps({
            "original_min_members_unenforced": original_summary,
            "fixed_min_members_enforced": fixed_summary,
            "equal_weight_all_sectors": eq_summary,
            "spy_buy_and_hold": spy_summary,
            "excluded_sectors": fixed_result["excluded_sectors"],
            "eligible_sectors": fixed_result["eligible_sectors"],
            "original_rebalance_log_sample": original_result["rebalance_log"][:10],
            "fixed_rebalance_log_sample": fixed_result["rebalance_log"][:10],
        }, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
