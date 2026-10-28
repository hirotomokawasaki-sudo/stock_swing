#!/usr/bin/env python3
"""ETF vs Stock profit factor attribution report.

Answers:
  - What is the realized PF split between ETF and Stock trades?
  - What would overall PF be with ETF buys disabled?
  - What is PF trend over time (weekly)?
  - How do strategy_ids compare (once ETF_STRATEGY_ID tagging is active)?

Usage:
  python scripts/compare_etf_stock_attribution.py
  python scripts/compare_etf_stock_attribution.py --json > artifacts/attribution_report.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"

ETF_SYMBOLS = {
    'SHOC','SOXQ','SOXX','SMH','FTXL','PTF','SMHX','FRWD','TTEQ','GTOP',
    'CHPX','CHPS','PSCT','QTEC','TDIV','SKYY','QTUM',
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _pf(trades: list[dict]) -> float | None:
    wins   = [t for t in trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl") or 0) < 0]
    gross_win  = sum(t.get("pnl", 0) for t in wins)
    gross_loss = abs(sum(t.get("pnl", 0) for t in losses))
    if gross_loss == 0:
        return None
    return round(gross_win / gross_loss, 3)


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"count": 0, "pnl": 0, "profit_factor": None,
                "win_rate": None, "avg_win": None, "avg_loss": None}
    wins   = [t for t in trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl") or 0) < 0]
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    avg_win  = sum(t.get("pnl", 0) for t in wins)  / len(wins)   if wins   else None
    avg_loss = sum(t.get("pnl", 0) for t in losses) / len(losses) if losses else None
    return {
        "count": len(trades),
        "pnl": round(total_pnl, 2),
        "profit_factor": _pf(trades),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
        "avg_win":  round(avg_win,  2) if avg_win  is not None else None,
        "avg_loss": round(avg_loss, 2) if avg_loss is not None else None,
    }


def _iso_week(trade: dict) -> str:
    raw = trade.get("exit_time") or trade.get("entry_time") or ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.strftime("%Y-W%V")
    except Exception:
        return "unknown"


# ── main ─────────────────────────────────────────────────────────────────────

def build_report(state: dict) -> dict:
    closed = [t for t in state.get("trades", []) if t.get("status") == "closed"]

    etf_trades   = [t for t in closed if t.get("symbol", "") in ETF_SYMBOLS]
    stock_trades = [t for t in closed if t.get("symbol", "") not in ETF_SYMBOLS]

    # ── Section 1: Top-level split ──────────────────────────────────────────
    split = {
        "all":   _stats(closed),
        "etf":   _stats(etf_trades),
        "stock": _stats(stock_trades),
        "stock_only_pf_gain": None,
    }
    if split["all"]["profit_factor"] and split["stock"]["profit_factor"]:
        split["stock_only_pf_gain"] = round(
            split["stock"]["profit_factor"] - split["all"]["profit_factor"], 3
        )

    # ── Section 2: Projected PF without ETF ────────────────────────────────
    projected = {
        "scenario": "ETF buys disabled (stock trades only)",
        "pf": split["stock"]["profit_factor"],
        "pnl": split["stock"]["pnl"],
        "baseline_pf": split["all"]["profit_factor"],
        "baseline_pnl": split["all"]["pnl"],
        "delta_pnl": round(
            (split["stock"]["pnl"] or 0) - (split["all"]["pnl"] or 0), 2
        ),
    }

    # ── Section 3: Strategy ID breakdown ───────────────────────────────────
    by_strategy: dict[str, list[dict]] = defaultdict(list)
    for t in closed:
        by_strategy[t.get("strategy_id") or "unknown"].append(t)
    strategy_breakdown = {
        sid: _stats(trades) for sid, trades in sorted(by_strategy.items())
    }

    # ── Section 4: Weekly PF trend ─────────────────────────────────────────
    by_week: dict[str, list[dict]] = defaultdict(list)
    for t in closed:
        by_week[_iso_week(t)].append(t)
    weekly = {}
    for week in sorted(by_week):
        wt = by_week[week]
        weekly[week] = {
            "all":   _stats(wt),
            "etf":   _stats([t for t in wt if t.get("symbol") in ETF_SYMBOLS]),
            "stock": _stats([t for t in wt if t.get("symbol") not in ETF_SYMBOLS]),
        }

    # ── Section 5: ETF symbols ranked by drag ──────────────────────────────
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for t in etf_trades:
        by_symbol[t.get("symbol", "?")].append(t)
    etf_symbol_drag = sorted(
        [{"symbol": sym, **_stats(trades)} for sym, trades in by_symbol.items()],
        key=lambda x: x["pnl"],
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "split": split,
        "projected_without_etf": projected,
        "by_strategy_id": strategy_breakdown,
        "weekly_trend": weekly,
        "etf_symbols_by_pnl_drag": etf_symbol_drag,
    }


def print_text_report(report: dict) -> None:
    split = report["split"]
    proj  = report["projected_without_etf"]

    print("=" * 65)
    print("ETF vs STOCK ATTRIBUTION REPORT")
    print(f"Generated: {report['generated_at'][:16]} UTC")
    print("=" * 65)

    print("\n── Section 1: Top-level Split ─────────────────────────────")
    for label, key in [("ALL", "all"), ("ETF", "etf"), ("STOCK", "stock")]:
        s = split[key]
        pf  = f"{s['profit_factor']:.3f}" if s['profit_factor'] else "N/A"
        wr  = f"{s['win_rate']:.1%}"       if s['win_rate']      else "N/A"
        pnl = f"${s['pnl']:>+10,.2f}"
        print(f"  {label:6s}  trades={s['count']:>3}  PF={pf:>7}  WR={wr:>6}  PnL={pnl}")

    print(f"\n  → PF gain from disabling ETF buys: "
          f"+{split['stock_only_pf_gain']:.3f}" if split["stock_only_pf_gain"] else "")

    print("\n── Section 2: Projected PF Without ETF Buys ───────────────")
    print(f"  Baseline  PF={proj['baseline_pf']:.3f}  PnL=${proj['baseline_pnl']:>+,.2f}")
    print(f"  Stock-only PF={proj['pf']:.3f}  PnL=${proj['pnl']:>+,.2f}")
    print(f"  Delta PnL = ${proj['delta_pnl']:>+,.2f}")

    print("\n── Section 3: Strategy ID Breakdown ───────────────────────")
    for sid, s in report["by_strategy_id"].items():
        pf = f"{s['profit_factor']:.3f}" if s['profit_factor'] else " N/A"
        print(f"  {sid:35s}  n={s['count']:>3}  PF={pf}  PnL=${s['pnl']:>+8,.0f}")

    print("\n── Section 4: Weekly PF Trend ─────────────────────────────")
    for week, w in report["weekly_trend"].items():
        a = w["all"]
        pf = f"{a['profit_factor']:.3f}" if a["profit_factor"] else " N/A"
        pnl = f"${a['pnl']:>+8,.0f}"
        etf_n = w["etf"]["count"]
        stk_n = w["stock"]["count"]
        print(f"  {week}  PF={pf}  PnL={pnl}  (etf={etf_n} stock={stk_n})")

    print("\n── Section 5: ETF Symbols by PnL Drag ─────────────────────")
    for row in report["etf_symbols_by_pnl_drag"]:
        pf = f"{row['profit_factor']:.3f}" if row["profit_factor"] else " N/A"
        print(f"  {row['symbol']:6s}  n={row['count']:>2}  PF={pf}  PnL=${row['pnl']:>+8,.0f}")

    print("\n" + "=" * 65)
    print("RECOMMENDATION")
    stock_pf = split["stock"]["profit_factor"] or 0
    etf_pf   = split["etf"]["profit_factor"]   or 0
    print(f"  Stock PF ({stock_pf:.3f}) vs ETF PF ({etf_pf:.3f})")
    if etf_pf < 0.5:
        print("  → ETF trades have NEGATIVE expected value. Keep ETF buy guardrail ON.")
    elif etf_pf < 1.0:
        print("  → ETF trades are sub-1.0 PF. Monitor before re-enabling buys.")
    else:
        print("  → ETF PF recovered to >1.0. Consider re-enabling with reduced sizing.")
    print("=" * 65)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    parser.add_argument("--state", default=str(STATE_FILE), help="Path to pnl_state.json")
    parser.add_argument("--out", help="Write JSON output to file")
    args = parser.parse_args()

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    report = build_report(state)

    if args.json or args.out:
        output = json.dumps(report, indent=2, ensure_ascii=False)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(output, encoding="utf-8")
            print(f"Written to {args.out}")
        if args.json:
            print(output)
    else:
        print_text_report(report)


if __name__ == "__main__":
    main()
