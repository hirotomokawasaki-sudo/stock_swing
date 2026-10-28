#!/usr/bin/env python3
"""F8: clean-records-only performance analysis.

Computes PF, win rate, expected value, max drawdown, exit attribution,
and ETF/stock breakdown using ONLY clean closed trades
(holding_days >= 0, quarantined trades excluded).

Usage:
    python scripts/f8_clean_records_analysis.py [--json] [--csv PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.tracking.pnl_tracker import PnLTracker, _compute_holding_days


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"count": 0, "win_rate": None, "profit_factor": None, "net_pnl": 0.0,
                "avg_pnl": None, "avg_return_pct": None, "wins": 0, "losses": 0}
    wins   = [t for t in trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl") or 0) < 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses))
    net_pnl      = sum(t.get("pnl") or 0 for t in trades)
    win_rate     = len(wins) / len(trades)
    pf = round(gross_profit / gross_loss, 4) if gross_loss > 0 else None
    avg_pnl = net_pnl / len(trades)
    valid_ret = [t for t in trades if t.get("return_pct") is not None]
    avg_ret = (sum(t["return_pct"] for t in valid_ret) / len(valid_ret)) if valid_ret else None
    # AUDIT FIX (2026-08-23): expected_value previously computed
    # "win_rate * avg_pnl + (1-win_rate) * (net_pnl - win_rate*avg_pnl/win_rate)",
    # a formula that does not correspond to any standard per-trade
    # expectancy definition and produced wildly wrong values (e.g. -$10,773
    # against an actual per-trade average PnL of -$81.64 on the same 252-
    # trade cohort -- off by two orders of magnitude, not just a rounding
    # difference). Standard per-trade expectancy is simply
    # win_rate*avg_win - loss_rate*avg_loss, which is mathematically
    # identical to net_pnl/count (avg_pnl) -- expressed via win/loss
    # averages instead of raw sums to be independently checkable against
    # avg_pnl (the two must always agree for a correct formula; the old one
    # never did except when gross_loss==0 masked the bug via short-circuit).
    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    loss_rate = len(losses) / len(trades) if trades else 0.0
    expectancy = (win_rate * avg_win) - (loss_rate * avg_loss) if trades else None

    return {
        "count":           len(trades),
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        round(win_rate, 4),
        "profit_factor":   pf,
        "net_pnl":         round(net_pnl, 2),
        "gross_profit":    round(gross_profit, 2),
        "gross_loss":      round(gross_loss, 2),
        "avg_pnl":         round(avg_pnl, 2),
        "avg_return_pct":  round(avg_ret * 100, 4) if avg_ret is not None else None,
        # expected_value (per-trade expectancy, USD) == avg_pnl by
        # construction; kept as a separate, explicitly-labeled key (rather
        # than removed) so any existing consumer relying on the key's
        # presence doesn't break, but it is no longer computed via the
        # broken formula above.
        "expected_value":  round(expectancy, 2) if expectancy is not None else None,
    }


def _max_drawdown(trades: list[dict], baseline_equity: float = 1_000_000.0) -> float:
    """Compute max drawdown of the realized-PnL equity curve, as a fraction
    of a real account-equity baseline.

    AUDIT FIX (2026-08-23): previously tracked "peak" as the running
    cumulative-PnL peak itself (starting at 0.0, not at any real equity
    value), so drawdown = (peak - running) / peak used the *cumulative
    profit high-water mark* as the denominator rather than actual account
    equity. Two failure modes resulted:
      1. Before cumulative PnL ever turned positive (peak stays 0.0), the
         `if peak > 0` guard meant drawdown was silently never recorded at
         all for that entire stretch, even while realized losses were
         accumulating -- exactly the period a drawdown metric matters most.
      2. Once peak did turn positive, a small peak (e.g. +$1,443.75, as
         actually occurred on this ledger before the account swung to a
         cumulative loss) makes even a modest subsequent loss look like a
         drawdown approaching 100% of "peak", which is a meaningless
         percentage for judging real portfolio risk -- a $1,444 profit peak
         is not a meaningful capital base to measure drawdown against.
    Fix: denominate drawdown against `baseline_equity` + running cumulative
    PnL (i.e. actual implied account equity over time), with the peak
    initialized to baseline_equity so a drawdown is recorded from trade 1
    even if cumulative PnL has not yet turned positive.
    """
    sorted_t = sorted(trades, key=lambda t: t.get("exit_time") or "")
    peak = baseline_equity
    running = baseline_equity
    max_dd = 0.0
    for t in sorted_t:
        running += t.get("pnl") or 0
        if running > peak:
            peak = running
        if peak > 0:
            dd = (peak - running) / peak
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 4)


def main() -> None:
    parser = argparse.ArgumentParser(description="F8: clean-records performance analysis")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--csv", type=str, help="Write CSV to path")
    args = parser.parse_args()

    tracker = PnLTracker(project_root)
    clean   = tracker.get_clean_closed_trades()
    quarant = tracker.get_quarantined_trades()
    quality = tracker.get_ledger_quality_report()
    _baseline_equity = float(getattr(tracker.state, "baseline_equity", None) or 1_000_000.0)

    UNKNOWN_REASONS = {"broker_fill", "broker_fill_unknown", None, ""}

    # ── Classify by asset class ─────────────────────────────────────────────
    try:
        from stock_swing.risk.position_sizing import classify_asset_class
    except ImportError:
        def classify_asset_class(sym, ac=None):
            return ac or "stock"

    etf_trades   = [t for t in clean if classify_asset_class(t.get("symbol",""), t.get("asset_class")) == "etf"]
    stock_trades = [t for t in clean if classify_asset_class(t.get("symbol",""), t.get("asset_class")) != "etf"]

    # ── Exit attribution ────────────────────────────────────────────────────
    by_reason: dict[str, list] = {}
    for t in clean:
        r = str(t.get("exit_reason") or "unknown")
        if r in ("", "None", "broker_fill", "broker_fill_unknown"):
            r = "unknown"
        by_reason.setdefault(r, []).append(t)

    # ── Holding days distribution ────────────────────────────────────────────
    hd_values = [
        _compute_holding_days(t.get("entry_time"), t.get("exit_time"))
        for t in clean
    ]
    hd_valid = [h for h in hd_values if h is not None]

    # ── Build report ─────────────────────────────────────────────────────────
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "clean_closed_trades_only",
        "ledger_quality": quality,
        "quarantined_count": len(quarant),
        "overall": _metrics(clean),
        "max_drawdown": _max_drawdown(clean, baseline_equity=_baseline_equity),
        "max_drawdown_baseline_equity": _baseline_equity,
        "by_asset_class": {
            "etf":   _metrics(etf_trades),
            "stock": _metrics(stock_trades),
        },
        "by_exit_reason": {
            reason: _metrics(trades)
            for reason, trades in sorted(
                by_reason.items(),
                key=lambda item: len(item[1]),
                reverse=True,
            )
        },
        "holding_days": {
            "min":    round(min(hd_valid), 2) if hd_valid else None,
            "max":    round(max(hd_valid), 2) if hd_valid else None,
            "median": round(sorted(hd_valid)[len(hd_valid)//2], 2) if hd_valid else None,
            "mean":   round(sum(hd_valid)/len(hd_valid), 2) if hd_valid else None,
        },
        "note": (
            "WARNING: clean_closed < 30. PF estimates are unreliable at this sample size."
            if len(clean) < 30 else
            "Sample size sufficient for preliminary analysis."
        ),
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    # ── Human-readable output ────────────────────────────────────────────────
    print("=" * 62)
    print("  F8: clean-records performance analysis")
    print(f"  Generated: {report['generated_at'][:19]} UTC")
    print("=" * 62)

    q = quality
    print(f"\n📋 Ledger Quality:")
    print(f"  clean closed:          {q['clean_closed']:>5d}")
    print(f"  quarantined:           {q['quarantined']:>5d}  ← excluded from all metrics")
    print(f"  no_exit_attribution:   {q['no_exit_attribution']:>5d}  (count as 'unknown')")
    print(f"  attribution coverage:  {q['attribution_coverage_pct']}%")

    ov = report["overall"]
    print(f"\n📊 Overall (clean records only):")
    print(f"  count:         {ov['count']}")
    print(f"  win rate:      {ov['win_rate']:.1%}" if ov.get("win_rate") else "  win rate:      N/A")
    print(f"  profit factor: {ov['profit_factor']}" if ov.get("profit_factor") else "  profit factor: ∞ (no losing trades)" if ov.get("wins") else "  profit factor: N/A")
    print(f"  net PnL:       ${ov['net_pnl']:,.2f}")
    print(f"  avg PnL/trade: ${ov['avg_pnl']:,.2f}" if ov.get("avg_pnl") is not None else "")
    print(f"  avg return:    {ov['avg_return_pct']}%" if ov.get("avg_return_pct") is not None else "")
    print(f"  max drawdown:  {report['max_drawdown']:.1%}")

    print(f"\n📈 By Asset Class:")
    for ac, m in report["by_asset_class"].items():
        pf = m.get("profit_factor")
        pf_str = f"{pf:.3f}" if pf is not None else "∞"
        print(f"  {ac.upper():5s}: n={m['count']:>3d}  WR={m['win_rate']:.1%}  PF={pf_str}  net=${m['net_pnl']:,.0f}")

    print(f"\n🎯 Exit Attribution (clean only):")
    for reason, m in report["by_exit_reason"].items():
        pf = m.get("profit_factor")
        pf_str = f"{pf:.3f}" if pf is not None else "∞"
        tag = " ← (unattributed)" if reason == "unknown" else ""
        print(f"  {reason:25s}: n={m['count']:>3d}  WR={m['win_rate']:.1%}  PF={pf_str}  net=${m['net_pnl']:,.0f}{tag}")

    hd = report["holding_days"]
    if hd["mean"] is not None:
        print(f"\n⏱  Holding Days (clean only):")
        print(f"  min={hd['min']:.1f}d  median={hd['median']:.1f}d  mean={hd['mean']:.1f}d  max={hd['max']:.1f}d")

    print(f"\n⚠️  {report['note']}")
    print()

    if args.csv:
        import csv
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "generated_at", "asset_class", "exit_reason", "count",
                "wins", "losses", "win_rate", "profit_factor",
                "net_pnl", "avg_pnl", "avg_return_pct",
            ])
            w.writeheader()
            for ac, m in report["by_asset_class"].items():
                w.writerow({
                    "generated_at": report["generated_at"],
                    "asset_class": ac, "exit_reason": "ALL",
                    **{k: m.get(k) for k in ["count","wins","losses","win_rate","profit_factor","net_pnl","avg_pnl","avg_return_pct"]},
                })
            for reason, m in report["by_exit_reason"].items():
                w.writerow({
                    "generated_at": report["generated_at"],
                    "asset_class": "ALL", "exit_reason": reason,
                    **{k: m.get(k) for k in ["count","wins","losses","win_rate","profit_factor","net_pnl","avg_pnl","avg_return_pct"]},
                })
        print(f"CSV written: {out}")


if __name__ == "__main__":
    main()
