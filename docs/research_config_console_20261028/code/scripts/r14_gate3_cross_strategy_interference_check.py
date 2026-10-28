#!/usr/bin/env python3
"""R14 Gate 3 cross-strategy interference check (2026-08-25).

QUESTION: entry_filter.py's rolling-PF gate (Gate 3) computes profit factor
PER-SYMBOL from ALL closed trades in pnl_state.json's `trades` list --
it does not distinguish which strategy closed them. If
dip_buy_meanreversion_v1 were ever promoted from shadow to a live (order-
submitting) strategy sharing the same EntryFilterEngine as
breakout_momentum_v1, would ONE strategy's recent losses on a symbol block
the OTHER strategy's entry into that same symbol, even though their entry
conditions are logically opposite (bullish-momentum vs bearish-momentum)?

This is a NO-CODE-CHANGE analysis, not a Phase 3 implementation: it reuses
the exact same `compute_rolling_pf()` function entry_filter.py's real Gate 3
calls (imported, not reimplemented) and replays it point-in-time (no
lookahead: only closed trades with exit_date strictly before the candidate
signal's date are visible) against BOTH backtests' trade histories already
produced for R14 Phase 1:
  - momentum trades: reports/r11_backtest_v3_results.json (breakout_momentum_v1,
    point-in-time universe, conservative-OHLC-exit, 10bp slippage)
  - dip-buy trades: docs/r14_dip_buy_meanreversion_phase1_20260825/trades.json
    (dip_buy_meanreversion_v1, SAME cost model / point-in-time universe)

Both directions are checked:
  (A) Would momentum's own closed-trade history have blocked a dip-buy
      candidate on the same symbol (using the REAL default gate:
      rolling_pf_gate=0.70, min_trades_for_gate=5)?
  (B) Would dip-buy's own closed-trade history have blocked a momentum
      candidate on the same symbol under the same gate?

LIMITATION (explicit): this assumes a single shared `trades` pool exactly
as EntryFilterEngine.filter() consumes it today (closed_trades passed in as
one flat list) -- it does NOT model a hypothetical strategy-scoped Gate 3
(that would require an actual code change and is exactly the design
decision this analysis is meant to inform, not pre-empt). It also does not
model interaction with the OTHER portfolio-level shared risk layers
(circuit breaker, cluster cap, PortfolioAllocator) -- those are separately
flagged, unresolved dependencies noted in the R14 Phase 1/2 docs.

Usage:
    python scripts/r14_gate3_cross_strategy_interference_check.py [--save]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.risk.entry_filter import compute_rolling_pf  # noqa: E402

ROLLING_PF_GATE = 0.70    # matches EntryFilterConfig's real default
MIN_TRADES_FOR_GATE = 5   # matches EntryFilterConfig's real default


def _as_closed_trade_dicts(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize a backtest trade list into the {symbol, pnl, exit_date}
    shape compute_rolling_pf() expects (it only reads 'symbol' and 'pnl')."""
    out = []
    for t in trades:
        out.append({"symbol": t["symbol"], "pnl": t["pnl"], "exit_date": t["exit_date"]})
    return out


def check_would_be_blocked(
    candidate_symbol: str,
    candidate_signal_date: str,
    other_strategy_closed_trades: list[dict[str, Any]],
) -> dict[str, Any]:
    """Point-in-time Gate 3 check: would `candidate_symbol`'s BUY on
    `candidate_signal_date` have been blocked by the OTHER strategy's
    rolling PF on that symbol, using only trades already closed before
    that date (no lookahead)?
    """
    visible = [t for t in other_strategy_closed_trades if t["exit_date"] < candidate_signal_date]
    pf_stats = compute_rolling_pf(visible, min_trades=MIN_TRADES_FOR_GATE)
    stat = pf_stats.get(candidate_symbol)
    if stat is None or stat.profit_factor is None:
        return {"would_block": False, "reason": "insufficient_trades_for_gate", "pf": None, "n": stat.closed_count if stat else 0}
    if stat.profit_factor < ROLLING_PF_GATE:
        return {"would_block": True, "reason": "rolling_pf_gate", "pf": stat.profit_factor, "n": stat.closed_count}
    return {"would_block": False, "reason": "pf_ok", "pf": stat.profit_factor, "n": stat.closed_count}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    momentum_path = PROJECT_ROOT / "reports" / "r11_backtest_v3_results.json"
    dipbuy_path = PROJECT_ROOT / "docs" / "r14_dip_buy_meanreversion_phase1_20260825" / "trades.json"

    momentum_trades = json.loads(momentum_path.read_text())["trades"]
    dipbuy_trades = json.loads(dipbuy_path.read_text())

    momentum_closed = _as_closed_trade_dicts(momentum_trades)
    dipbuy_closed = _as_closed_trade_dicts(dipbuy_trades)

    print(f"momentum trades: {len(momentum_trades)}, dip-buy trades: {len(dipbuy_trades)}")
    print(f"Gate 3 config used: rolling_pf_gate={ROLLING_PF_GATE}, min_trades_for_gate={MIN_TRADES_FOR_GATE}\n")

    # --- Direction A: momentum's history blocking dip-buy entries ---
    a_results = []
    for t in dipbuy_trades:
        check = check_would_be_blocked(t["symbol"], t["signal_date"], momentum_closed)
        a_results.append({**check, "symbol": t["symbol"], "signal_date": t["signal_date"], "dipbuy_pnl": t["pnl"]})

    a_blocked = [r for r in a_results if r["would_block"]]
    a_blocked_would_have_won = [r for r in a_blocked if r["dipbuy_pnl"] > 0]

    print("=" * 70)
    print("DIRECTION A: would momentum's recent losses block dip-buy entries?")
    print("=" * 70)
    print(f"  Total dip-buy candidates checked: {len(a_results)}")
    print(f"  Would be BLOCKED by momentum's rolling PF: {len(a_blocked)} "
          f"({len(a_blocked) / len(a_results) * 100:.1f}%)")
    print(f"  Of those blocked, would-have-been WINNING dip-buy trades: "
          f"{len(a_blocked_would_have_won)} "
          f"({len(a_blocked_would_have_won) / len(a_blocked) * 100:.1f}% of blocked, if any)"
          if a_blocked else "  Of those blocked, would-have-been WINNING: n/a (0 blocked)")
    if a_blocked:
        print("\n  Blocked dip-buy candidates (symbol, date, momentum_pf_at_time, dipbuy_actual_pnl):")
        for r in sorted(a_blocked, key=lambda r: r["signal_date"]):
            marker = "  <- WOULD HAVE WON" if r["dipbuy_pnl"] > 0 else ""
            print(f"    {r['symbol']:6} {r['signal_date']}  momentum_pf={r['pf']:.3f} (n={r['n']})  "
                  f"dipbuy_pnl=${r['dipbuy_pnl']:+.2f}{marker}")

    # --- Direction B: dip-buy's history blocking momentum entries ---
    b_results = []
    for t in momentum_trades:
        check = check_would_be_blocked(t["symbol"], t["signal_date"], dipbuy_closed)
        b_results.append({**check, "symbol": t["symbol"], "signal_date": t["signal_date"], "momentum_pnl": t["pnl"]})

    b_blocked = [r for r in b_results if r["would_block"]]
    b_blocked_would_have_won = [r for r in b_blocked if r["momentum_pnl"] > 0]

    print("\n" + "=" * 70)
    print("DIRECTION B: would dip-buy's recent losses block momentum entries?")
    print("=" * 70)
    print(f"  Total momentum candidates checked: {len(b_results)}")
    print(f"  Would be BLOCKED by dip-buy's rolling PF: {len(b_blocked)} "
          f"({len(b_blocked) / len(b_results) * 100:.1f}%)")
    print(f"  Of those blocked, would-have-been WINNING momentum trades: "
          f"{len(b_blocked_would_have_won)} "
          f"({len(b_blocked_would_have_won) / len(b_blocked) * 100:.1f}% of blocked, if any)"
          if b_blocked else "  Of those blocked, would-have-been WINNING: n/a (0 blocked)")
    if b_blocked:
        print("\n  Blocked momentum candidates (symbol, date, dipbuy_pf_at_time, momentum_actual_pnl):")
        for r in sorted(b_blocked, key=lambda r: r["signal_date"]):
            marker = "  <- WOULD HAVE WON" if r["momentum_pnl"] > 0 else ""
            print(f"    {r['symbol']:6} {r['signal_date']}  dipbuy_pf={r['pf']:.3f} (n={r['n']})  "
                  f"momentum_pnl=${r['momentum_pnl']:+.2f}{marker}")

    # --- Net PnL impact estimate (naive: sum of pnl on blocked trades) ---
    a_forgone_pnl = sum(r["dipbuy_pnl"] for r in a_blocked)
    b_forgone_pnl = sum(r["momentum_pnl"] for r in b_blocked)

    print("\n" + "=" * 70)
    print("NET PNL IMPACT ESTIMATE (naive: assumes blocked trade simply never happens)")
    print("=" * 70)
    print(f"  Direction A (dip-buy entries blocked by momentum's PF): net PnL forgone = ${a_forgone_pnl:+.2f}")
    print(f"  Direction B (momentum entries blocked by dip-buy's PF): net PnL forgone = ${b_forgone_pnl:+.2f}")

    output = {
        "config": {"rolling_pf_gate": ROLLING_PF_GATE, "min_trades_for_gate": MIN_TRADES_FOR_GATE},
        "direction_a_momentum_blocks_dipbuy": {
            "total_candidates": len(a_results),
            "blocked_count": len(a_blocked),
            "blocked_pct": round(len(a_blocked) / len(a_results) * 100, 2) if a_results else 0,
            "blocked_would_have_won_count": len(a_blocked_would_have_won),
            "forgone_pnl": round(a_forgone_pnl, 2),
            "blocked_detail": a_blocked,
        },
        "direction_b_dipbuy_blocks_momentum": {
            "total_candidates": len(b_results),
            "blocked_count": len(b_blocked),
            "blocked_pct": round(len(b_blocked) / len(b_results) * 100, 2) if b_results else 0,
            "blocked_would_have_won_count": len(b_blocked_would_have_won),
            "forgone_pnl": round(b_forgone_pnl, 2),
            "blocked_detail": b_blocked,
        },
    }

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r14_dip_buy_meanreversion_phase1_20260825"
        out_path = out_dir / "gate3_interference_check.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
