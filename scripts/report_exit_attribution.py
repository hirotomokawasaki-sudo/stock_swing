#!/usr/bin/env python3
"""
R1-C: Exit Reason Attribution Report
=====================================
Shows per-reason stats (count, PF, win-rate, avg PnL) and computes
attribution_completeness = known_reason / total_closed × 100.

Splits output into:
  - Pre-R1-B  (entry before 2026-06-25): legacy broker_fill expected
  - Post-R1-B (entry on/after 2026-06-25): should have signal reasons

Usage:
    python scripts/report_exit_attribution.py [--cutoff YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# R1-B was deployed on 2026-06-25
DEFAULT_CUTOFF = "2026-06-25"

# Reasons considered "properly attributed"
ATTRIBUTED_REASONS = {
    "breakeven_stop",
    "trailing_stop",
    "stop_loss",
    "signal_stop",
    "signal_breakeven",
    "signal_trailing",
    "manual",
    "target_reached",
}

# Reasons that are legacy / unknown attribution
UNATTRIBUTED_REASONS = {
    "broker_fill",
    "broker_fill_unknown",
    None,
    "",
    "unknown",
    "MISSING",
}


def profit_factor(wins: float, losses: float) -> str:
    """Returns PF string; ∞ when no losses."""
    if losses == 0:
        return "∞" if wins > 0 else "N/A"
    return f"{wins / losses:.3f}"


def build_reason_stats(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for t in trades:
        reason = t.get("exit_reason") or "MISSING"
        pnl = float(t.get("pnl") or 0)
        if reason not in stats:
            stats[reason] = {"count": 0, "wins": 0, "losses": 0,
                             "gross_profit": 0.0, "gross_loss": 0.0, "net_pnl": 0.0}
        s = stats[reason]
        s["count"] += 1
        s["net_pnl"] += pnl
        if pnl > 0:
            s["wins"] += 1
            s["gross_profit"] += pnl
        elif pnl < 0:
            s["losses"] += 1
            s["gross_loss"] += abs(pnl)
    return stats


def print_reason_table(stats: dict[str, dict[str, Any]], title: str) -> None:
    if not stats:
        print(f"  (no trades)")
        return
    total = sum(s["count"] for s in stats.values())
    header = f"{'Reason':<22} {'N':>5} {'%':>5}  {'WR%':>6}  {'PF':>7}  {'Avg PnL':>10}  {'Net PnL':>12}  {'attr?':>5}"
    sep = "-" * len(header)
    print(f"\n{title}")
    print(sep)
    print(header)
    print(sep)
    for reason, s in sorted(stats.items(), key=lambda x: -x[1]["count"]):
        n = s["count"]
        pct = n / total * 100 if total else 0
        wr = s["wins"] / n * 100 if n else 0
        pf = profit_factor(s["gross_profit"], s["gross_loss"])
        avg = s["net_pnl"] / n if n else 0
        net = s["net_pnl"]
        attributed = "✅" if reason in ATTRIBUTED_REASONS else "❌"
        print(f"  {reason:<20} {n:>5} {pct:>5.1f}%  {wr:>5.1f}%  {pf:>7}  {avg:>+10.2f}  {net:>+12.2f}  {attributed:>5}")
    print(sep)


def attribution_completeness(trades: list[dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    known = sum(1 for t in trades if (t.get("exit_reason") or "") in ATTRIBUTED_REASONS)
    return known / len(trades) * 100


def main() -> None:
    parser = argparse.ArgumentParser(description="R1-C Exit Attribution Report")
    parser.add_argument("--cutoff", default=DEFAULT_CUTOFF,
                        help=f"R1-B cutoff date (default: {DEFAULT_CUTOFF})")
    parser.add_argument("--data-dir", default=None,
                        help="Path to stock_swing project root (default: auto-detect)")
    args = parser.parse_args()

    if args.data_dir:
        project_root = Path(args.data_dir)
    else:
        project_root = Path(__file__).resolve().parents[1]

    pnl_path = project_root / "data" / "tracking" / "pnl_state.json"
    if not pnl_path.exists():
        print(f"ERROR: pnl_state.json not found at {pnl_path}", file=sys.stderr)
        sys.exit(1)

    with open(pnl_path, encoding="utf-8") as f:
        state = json.load(f)

    all_trades = state.get("trades", [])
    closed = [t for t in all_trades if t.get("exit_price") is not None]
    open_trades = [t for t in all_trades if t.get("exit_price") is None]

    cutoff = args.cutoff
    pre_rb = [t for t in closed if (t.get("entry_time") or t.get("entry_date") or "")[:10] < cutoff]
    post_rb = [t for t in closed if (t.get("entry_time") or t.get("entry_date") or "")[:10] >= cutoff]

    # ─── Header ──────────────────────────────────────────────────────────────
    print("=" * 72)
    print("  R1-C Exit Attribution Report")
    print(f"  R1-B cutoff: {cutoff}  |  Closed: {len(closed)}  |  Open: {len(open_trades)}")
    print("=" * 72)

    # ─── Overall ─────────────────────────────────────────────────────────────
    overall_stats = build_reason_stats(closed)
    print_reason_table(overall_stats, "ALL CLOSED TRADES")

    overall_ac = attribution_completeness(closed)
    print(f"\n  Attribution completeness (all):     {overall_ac:>6.1f}%  (target ≥ 95%)")

    # ─── Pre-R1-B ────────────────────────────────────────────────────────────
    pre_stats = build_reason_stats(pre_rb)
    print_reason_table(pre_stats, f"PRE-R1-B  (entry < {cutoff}, n={len(pre_rb)}) — legacy broker_fill expected")
    pre_ac = attribution_completeness(pre_rb)
    print(f"\n  Attribution completeness (pre):     {pre_ac:>6.1f}%  (legacy — not actionable)")

    # ─── Post-R1-B ───────────────────────────────────────────────────────────
    post_stats = build_reason_stats(post_rb)
    print_reason_table(post_stats, f"POST-R1-B (entry ≥ {cutoff}, n={len(post_rb)}) — signal reasons expected")
    post_ac = attribution_completeness(post_rb)
    target_ok = "✅" if post_ac >= 95.0 else "🔲"
    print(f"\n  Attribution completeness (post):    {post_ac:>6.1f}%  {target_ok} (target ≥ 95%)")

    # ─── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    total_attributed = sum(1 for t in closed if (t.get("exit_reason") or "") in ATTRIBUTED_REASONS)
    total_legacy_bf = sum(1 for t in closed if t.get("exit_reason") == "broker_fill")
    total_unknown = sum(1 for t in closed if (t.get("exit_reason") or "") in ("broker_fill_unknown", None, "", "MISSING"))
    print(f"  Signal-attributed trades:  {total_attributed:>4}  ({total_attributed/len(closed)*100:.1f}%)")
    print(f"  Legacy broker_fill:        {total_legacy_bf:>4}  ({total_legacy_bf/len(closed)*100:.1f}%)")
    print(f"  Unknown/unattributed:      {total_unknown:>4}  ({total_unknown/len(closed)*100:.1f}%)")
    print()
    print(f"  Post-R1-B completeness:    {post_ac:>6.1f}%  {target_ok}")
    if post_ac < 95.0 and post_rb:
        missing = [t.get("symbol", "?") for t in post_rb
                   if (t.get("exit_reason") or "") not in ATTRIBUTED_REASONS]
        print(f"  Unattributed post-R1-B:    {', '.join(missing[:10])}"
              + (" ..." if len(missing) > 10 else ""))
    print("=" * 72)


if __name__ == "__main__":
    main()
