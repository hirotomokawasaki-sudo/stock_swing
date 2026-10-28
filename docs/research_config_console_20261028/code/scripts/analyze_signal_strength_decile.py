#!/usr/bin/env python3
"""R4-C: entry_signal_strength デサイル別 PF / WR 計測スクリプト.

Usage:
    python scripts/analyze_signal_strength_decile.py [--save] [--since YYYY-MM-DD]

Outputs:
    - Console table (decile x PF / WR / count / net_pnl)
    - Optional JSON to reports/signal_strength_decile.json

Notes:
    - Only trades with entry_signal_strength recorded are included.
    - Clean records only (status=closed, quarantined excluded).
    - decile 1 = lowest 10%, decile 10 = highest 10%.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def compute_decile_stats(
    trades: list[dict],
    since: str | None = None,
    n_buckets: int = 10,
) -> list[dict]:
    """Return per-decile stats sorted by signal_strength ascending."""
    # Filter: closed, has entry_signal_strength
    filtered = [
        t for t in trades
        if t.get("status") == "closed"
        and t.get("entry_signal_strength") is not None
        and t.get("pnl") is not None
    ]
    if since:
        filtered = [
            t for t in filtered
            if (t.get("entry_time") or "") >= since
        ]
    if not filtered:
        return []

    # Sort by signal_strength
    filtered.sort(key=lambda t: float(t["entry_signal_strength"]))
    n = len(filtered)

    # Assign decile (1-based)
    results: list[dict] = []
    bucket_size = n / n_buckets
    for bucket in range(n_buckets):
        start_idx = int(bucket * bucket_size)
        end_idx = int((bucket + 1) * bucket_size) if bucket < n_buckets - 1 else n
        chunk = filtered[start_idx:end_idx]
        if not chunk:
            continue

        ss_min = float(chunk[0]["entry_signal_strength"])
        ss_max = float(chunk[-1]["entry_signal_strength"])
        wins = [t for t in chunk if float(t.get("pnl", 0)) > 0]
        losses = [t for t in chunk if float(t.get("pnl", 0)) < 0]
        gross_win = sum(float(t["pnl"]) for t in wins)
        gross_loss = abs(sum(float(t["pnl"]) for t in losses))
        net_pnl = sum(float(t.get("pnl", 0)) for t in chunk)
        pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
        wr = len(wins) / len(chunk) if chunk else 0.0
        # R4-v2 residual (2026-08-17): expectancy = average PnL per trade in
        # this decile. Distinct from net_pnl (the bucket total) -- expectancy
        # normalizes for bucket size so deciles with different trade counts
        # can be compared on a per-trade basis (e.g. "decile 5 nets +$832/trade
        # vs. decile 8's -$1,670/trade", rather than only comparing totals).
        expectancy = net_pnl / len(chunk) if chunk else 0.0

        results.append({
            "decile": bucket + 1,
            "ss_range": f"{ss_min:.3f}–{ss_max:.3f}",
            "ss_min": ss_min,
            "ss_max": ss_max,
            "count": len(chunk),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(wr, 4),
            "profit_factor": round(pf, 3) if pf != float("inf") else None,
            "net_pnl": round(net_pnl, 2),
            "expectancy": round(expectancy, 2),
            "gross_win": round(gross_win, 2),
            "gross_loss": round(gross_loss, 2),
        })

    return results


def compute_calibration_curve(rows: list[dict]) -> list[dict]:
    """R4-v2 residual (2026-08-23): decile-level calibration curve.

    Treats each decile's ss_min-ss_max midpoint as a proxy for the
    "predicted confidence" that a trade in that bucket is a winner, and
    compares it against the bucket's actual win_rate. This is a read-only
    diagnostic (recommendation-only, no automatic threshold changes)
    intended to show whether higher signal_strength buckets are actually
    associated with higher realized win rates (well-calibrated) or not
    (miscalibrated / flat / inverted).

    Returns one row per input decile with:
        - decile, ss_range, count
        - predicted (midpoint of ss_min/ss_max, used as a pseudo-probability)
        - actual (win_rate)
        - calibration_error (abs(predicted - actual))
    """
    curve: list[dict] = []
    for r in rows:
        predicted = (r["ss_min"] + r["ss_max"]) / 2.0
        actual = r["win_rate"]
        curve.append({
            "decile": r["decile"],
            "ss_range": r["ss_range"],
            "count": r["count"],
            "predicted": round(predicted, 4),
            "actual": round(actual, 4),
            "calibration_error": round(abs(predicted - actual), 4),
        })
    return curve


def print_calibration_curve(curve: list[dict]) -> None:
    if not curve:
        return
    print(f"\n{'='*72}")
    print(" Calibration Curve (signal_strength midpoint vs actual win_rate)")
    print(f"{'='*72}")
    print(f"{'Decile':>7} {'SS range':>14} {'N':>5} {'Predicted':>10} {'Actual WR':>10} {'|Error|':>8}")
    print(f"{'-'*7} {'-'*14} {'-'*5} {'-'*10} {'-'*10} {'-'*8}")
    for c in curve:
        print(
            f"{c['decile']:>7} {c['ss_range']:>14} {c['count']:>5} "
            f"{c['predicted']:>10.1%} {c['actual']:>10.1%} {c['calibration_error']:>8.1%}"
        )
    print(f"{'='*72}")
    mean_error = sum(c["calibration_error"] for c in curve) / len(curve)
    print(f"\n Mean calibration error: {mean_error:.1%}")
    if mean_error > 0.25:
        print(" \u26a0\ufe0f  Large mean calibration error: signal_strength should NOT be")
        print("    treated as a literal win probability in its current form.")
    print()


def print_table(rows: list[dict], total_trades: int, filtered_trades: int) -> None:
    print(f"\n{'='*72}")
    print(" Signal Strength Decile Analysis (R4-C)")
    print(f"{'='*72}")
    print(f" Trades with signal_strength: {filtered_trades} / {total_trades} total closed")
    print()
    print(f"{'Decile':>7} {'SS range':>14} {'N':>5} {'WR':>7} {'PF':>8} {'Net PnL':>12} {'Expectancy':>12}")
    print(f"{'-'*7} {'-'*14} {'-'*5} {'-'*7} {'-'*8} {'-'*12} {'-'*12}")
    for r in rows:
        pf_str = f"{r['profit_factor']:.3f}" if r["profit_factor"] is not None else "∞"
        expectancy = r.get("expectancy", 0.0)
        print(
            f"{r['decile']:>7} {r['ss_range']:>14} {r['count']:>5} "
            f"{r['win_rate']:>7.1%} {pf_str:>8} ${r['net_pnl']:>11,.0f} ${expectancy:>11,.0f}"
        )
    print(f"{'='*72}")

    if rows:
        # Insight
        top3 = sorted(rows, key=lambda r: r["profit_factor"] or 0, reverse=True)[:3]
        bot3 = sorted(rows, key=lambda r: r["profit_factor"] or 0)[:3]
        print(f"\n Top deciles (PF): {', '.join(str(r['decile']) for r in top3)}")
        print(f" Bot deciles (PF): {', '.join(str(r['decile']) for r in bot3)}")
        best_pf = max(rows, key=lambda r: r["profit_factor"] or 0)
        if best_pf["ss_min"] >= 0.7:
            rec_threshold = best_pf["ss_min"]
            print(f"\n💡 Recommendation: min_signal_strength ≥ {rec_threshold:.3f} "
                  f"based on decile {best_pf['decile']} (PF={best_pf['profit_factor']})")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Signal strength decile PF analysis (R4-C)")
    parser.add_argument("--save", action="store_true", help="Save JSON to reports/")
    parser.add_argument("--since", type=str, default=None, help="Filter trades since YYYY-MM-DD")
    parser.add_argument("--buckets", type=int, default=10, help="Number of buckets (default 10)")
    args = parser.parse_args()

    state_path = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
    state = _load(state_path)
    trades = state.get("trades", [])

    closed = [t for t in trades if t.get("status") == "closed"]
    rows = compute_decile_stats(trades, since=args.since, n_buckets=args.buckets)

    filtered_count = sum(r["count"] for r in rows)
    print_table(rows, total_trades=len(closed), filtered_trades=filtered_count)

    calibration_curve = compute_calibration_curve(rows)
    print_calibration_curve(calibration_curve)

    if filtered_count < 20:
        print(f"⚠️  Only {filtered_count} trades with signal_strength recorded.")
        print("   Results may not be statistically meaningful.")
        print("   Signal tracking started 2026-06-23; more data will accumulate over time.")
        print()

    if args.save:
        out_path = PROJECT_ROOT / "reports" / "signal_strength_decile.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "since": args.since,
            "total_closed": len(closed),
            "filtered_count": filtered_count,
            "decile_stats": rows,
            "calibration_curve": calibration_curve,
        }
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"[saved] {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
