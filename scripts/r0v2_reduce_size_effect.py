#!/usr/bin/env python3
"""R0-v2/R9 addendum follow-up (2026-08-15): quantify reduce_size's actual
downstream PnL effect during the R11-B validation/correction window.

The prior guardrail stress test (scripts/r0v2_guardrail_stress_test.py)
found that reduce_size fired 11 times during the validation window
(2025-10-27 to 2026-03-20) via consecutive_losing_trades>=5, but did not
simulate its actual effect on position sizing -- it only reported WHEN the
rule would have fired. This script closes that gap: it re-runs the R11-B
baseline simulation with reduce_size's real production behavior applied
(new-entry notional cut to 50% while consecutive_losing_trades>=5, exactly
matching src/stock_swing/cli/paper_demo.py's
`_reduce_size_multiplier = 0.5 if guard_decision.action == reduce_size`
logic), then compares the resulting trade list's PnL against the
unmodified baseline for the validation window specifically.

Design: rather than duplicating r11_backtest_engine.run_backtest()'s full
simulation loop, this re-implements only the entry-sizing decision point
with dynamic notional based on running consecutive-loss count computed the
same way production/risk_snapshot.py does
(compute_consecutive_losing_trades), fed by the same closed-trade history
being built up during the single-pass simulation.

Usage:
    python scripts/r0v2_reduce_size_effect.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import r11_backtest_engine as base  # noqa: E402
import r11b_param_search as r11b  # noqa: E402
from stock_swing.guardrails.risk_snapshot import compute_consecutive_losing_trades  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
REDUCE_SIZE_THRESHOLD = 5  # matches config/guardrails/autonomous_stop.yaml consecutive_losing_trades rule
REDUCE_SIZE_MULTIPLIER = 0.5  # matches paper_demo.py's _reduce_size_multiplier


def to_pnl_tracker_shape(trade: dict[str, Any]) -> dict[str, Any]:
    return {"status": "closed", "exit_time": trade["exit_date"] + "T21:00:00+00:00", "pnl": trade["pnl"]}


def run_with_reduce_size(symbols: list[str], base_notional: float = 29100.0) -> dict[str, Any]:
    """Re-run the R11-B simulation loop with dynamic reduce_size sizing.

    base_notional defaults to the live-average notional (~$29,100, per the
    guardrail stress test's scale factor), not the $10k PF-comparability
    basis, because this script is specifically about realistic dollar PnL
    impact, not cross-symbol PF comparison.
    """
    price_data = base.load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(f"Simulating {len(symbols)} symbols over {len(all_dates)} trading days with "
          f"dynamic reduce_size sizing (base_notional=${base_notional:,.0f}, "
          f"threshold={REDUCE_SIZE_THRESHOLD}, multiplier={REDUCE_SIZE_MULTIPLIER})")

    entry_strategy = base.BreakoutMomentumStrategy(min_momentum=0.05, min_signal_strength=0.40)
    exit_strategy = base.load_exit_strategy()

    open_positions: dict[str, base.Position] = {}
    closed_trades: list[dict[str, Any]] = []
    reduce_size_active_days = 0

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        base._freeze(current_dt)
        try:
            window_start_idx = max(0, i - base.BAR_LIMIT + 1)
            window_dates = all_dates[window_start_idx : i + 1]

            features_by_symbol: dict[str, list] = {}
            for sym, bars in price_data.items():
                recs = [base.make_record(sym, d, bars[d]) for d in window_dates if d in bars]
                if recs:
                    features_by_symbol[sym] = recs

            momentum_feat = base.PriceMomentumFeature(period_days=base.BAR_LIMIT)
            all_records = []
            for recs in features_by_symbol.values():
                all_records.extend(recs)
            momentum_results = momentum_feat.compute(all_records)

            # --- Exits (unchanged from R11-B) ---
            if open_positions:
                current_positions_payload = {}
                for sym, pos in open_positions.items():
                    bar = price_data.get(sym, {}).get(date_str)
                    if bar is None:
                        continue
                    close_px = bar["close"]
                    pos.peak_price = max(pos.peak_price, close_px)
                    current_positions_payload[sym] = {
                        "qty": pos.qty, "avg_entry_price": pos.entry_price,
                        "current_price": close_px, "peak_price": pos.peak_price,
                        "created_at": pos.entry_date.isoformat(),
                        "entry_signal_strength": pos.entry_signal_strength,
                    }
                if current_positions_payload:
                    exit_signals = exit_strategy.generate(
                        features=list(momentum_results), current_positions=current_positions_payload,
                    )
                    for sig in exit_signals:
                        sym = sig.symbol
                        pos = open_positions.get(sym)
                        if pos is None:
                            continue
                        exit_price = sig.metadata.get("current_price", price_data[sym][date_str]["close"])
                        pnl = (exit_price - pos.entry_price) * pos.qty
                        return_pct = (exit_price - pos.entry_price) / pos.entry_price
                        hold_days = (current_dt - pos.entry_date).days
                        closed_trades.append({
                            "symbol": sym, "entry_date": pos.entry_date.date().isoformat(),
                            "entry_price": pos.entry_price, "exit_date": date_str,
                            "exit_price": exit_price, "qty": pos.qty, "pnl": pnl,
                            "return_pct": return_pct, "holding_days": hold_days,
                            "exit_reason": sig.metadata.get("exit_trigger", "unknown"),
                            "entry_signal_strength": pos.entry_signal_strength,
                            "sized_at_notional": pos.entry_price * pos.qty,
                        })
                        del open_positions[sym]

            # --- Dynamic notional based on running consecutive-loss count ---
            # Computed the same way risk_snapshot.py does, from closed trades
            # accumulated so far in this single-pass simulation (chronological
            # order preserved since we process dates in order).
            trades_so_far = [to_pnl_tracker_shape(t) for t in closed_trades]
            consecutive = compute_consecutive_losing_trades(trades_so_far)
            reduce_size_active = consecutive >= REDUCE_SIZE_THRESHOLD
            effective_notional = base_notional * (REDUCE_SIZE_MULTIPLIER if reduce_size_active else 1.0)
            if reduce_size_active:
                reduce_size_active_days += 1

            # --- Entries (unchanged logic, dynamic notional) ---
            candidate_records = []
            for sym, recs in features_by_symbol.items():
                if sym not in open_positions:
                    candidate_records.extend(recs)
            if candidate_records:
                candidate_momentum = momentum_feat.compute(candidate_records)
                buy_signals = entry_strategy.generate(candidate_momentum)
                for sig in buy_signals:
                    sym = sig.symbol
                    if sym in open_positions:
                        continue
                    bar = price_data.get(sym, {}).get(date_str)
                    if bar is None or bar["close"] <= 0:
                        continue
                    entry_price = bar["close"]
                    qty = effective_notional / entry_price
                    open_positions[sym] = base.Position(
                        symbol=sym, entry_date=current_dt, entry_price=entry_price,
                        qty=qty, entry_signal_strength=sig.signal_strength,
                    )
        finally:
            base._unfreeze()

    final_date = all_dates[-1]
    for sym, pos in open_positions.items():
        bar = price_data.get(sym, {}).get(final_date)
        if bar is None:
            continue
        exit_price = bar["close"]
        pnl = (exit_price - pos.entry_price) * pos.qty
        return_pct = (exit_price - pos.entry_price) / pos.entry_price
        hold_days = (datetime.fromisoformat(final_date).replace(tzinfo=timezone.utc) - pos.entry_date).days
        closed_trades.append({
            "symbol": sym, "entry_date": pos.entry_date.date().isoformat(),
            "exit_date": final_date, "entry_price": pos.entry_price,
            "exit_price": exit_price, "qty": pos.qty, "pnl": pnl,
            "return_pct": return_pct, "holding_days": hold_days,
            "exit_reason": "backtest_end_forced_close",
            "entry_signal_strength": pos.entry_signal_strength,
            "sized_at_notional": pos.entry_price * pos.qty,
        })

    print(f"  reduce_size was active on {reduce_size_active_days}/{len(all_dates)} simulated days")
    return {"trades": closed_trades, "reduce_size_active_days": reduce_size_active_days}


def main() -> None:
    symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json"))
    live_notional = 29100.0  # matches r0v2_guardrail_stress_test.py's LIVE_AVG_NOTIONAL_PER_TRADE

    # Baseline: R11-B trades (fixed $10k), rescaled to live notional for fair
    # dollar comparison (same rescaling approach as the guardrail stress test).
    with open(PROJECT_ROOT / "reports" / "r11_backtest_results.json") as f:
        baseline_data = json.load(f)
    scale = live_notional / 10000.0
    baseline_trades = [
        {**t, "pnl": t["pnl"] * scale} for t in baseline_data["trades"]
    ]

    # With reduce_size: full re-simulation with dynamic sizing
    result = run_with_reduce_size(symbols, base_notional=live_notional)
    rs_trades = result["trades"]

    price_data = base.load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    segments = r11b.compute_date_segments(all_dates)

    print("\n=== Comparison: baseline (fixed notional) vs with reduce_size (dynamic notional) ===")
    print(f"(Both rescaled/sized to live avg notional ~${live_notional:,.0f}/trade)\n")

    for seg_name, (start, end) in segments.items():
        base_seg = [t for t in baseline_trades if start <= t["entry_date"] <= end]
        rs_seg = [t for t in rs_trades if start <= t["entry_date"] <= end]
        base_summary = base.summarize(base_seg, f"{seg_name}_baseline")
        rs_summary = base.summarize(rs_seg, f"{seg_name}_reduce_size")
        print(f"[{seg_name}] {start} to {end}")
        print(f"  baseline:     n={base_summary['n']:>4} PF={base_summary.get('profit_factor')} "
              f"net=${base_summary.get('net_pnl', 0):,.0f}")
        print(f"  reduce_size:  n={rs_summary['n']:>4} PF={rs_summary.get('profit_factor')} "
              f"net=${rs_summary.get('net_pnl', 0):,.0f}")
        delta = rs_summary.get('net_pnl', 0) - base_summary.get('net_pnl', 0)
        print(f"  delta: ${delta:+,.0f}\n")

    overall_base = base.summarize(baseline_trades, "overall_baseline")
    overall_rs = base.summarize(rs_trades, "overall_reduce_size")
    print(f"[OVERALL 2yr] baseline: n={overall_base['n']} PF={overall_base.get('profit_factor')} "
          f"net=${overall_base.get('net_pnl', 0):,.0f}")
    print(f"[OVERALL 2yr] reduce_size: n={overall_rs['n']} PF={overall_rs.get('profit_factor')} "
          f"net=${overall_rs.get('net_pnl', 0):,.0f}")

    out_path = PROJECT_ROOT / "reports" / "r0v2_reduce_size_effect_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "live_notional": live_notional,
            "reduce_size_threshold": REDUCE_SIZE_THRESHOLD,
            "reduce_size_multiplier": REDUCE_SIZE_MULTIPLIER,
            "reduce_size_active_days": result["reduce_size_active_days"],
            "baseline_trades": baseline_trades,
            "reduce_size_trades": rs_trades,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
