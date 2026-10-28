#!/usr/bin/env python3
"""R0-v2/R9 reduce_size follow-up #2 (2026-08-26): re-measure reduce_size's
real effect using the ACTUAL portfolio-level exposure-cap mechanism, not
the earlier per-trade-notional-halving approximation.

Background: scripts/r0v2_reduce_size_effect.py (2026-08-15) simulated
reduce_size as "halve the notional of each new entry" and concluded the
effect was mild (~10% loss mitigation). Live investigation on 2026-08-26
(user question: "why is BUY blocked entirely tonight despite guardrail
only being 'degraded', not 'halted'?") found that is NOT how reduce_size
actually works in production:

    paper_demo.py:
        _reduce_size_multiplier = 0.5 if guard_decision.action == reduce_size
        _effective_exposure_cap = dynamic_exposure_cap * _reduce_size_multiplier

    position_sizing.py's PositionSizingPolicy.size():
        regime_limit = inputs.exposure_cap_override  # this halved cap
        max_total_exposure_usd = equity * regime_limit
        remaining_capacity = max_total_exposure_usd - exposure
        shares_by_exposure = floor(max(remaining_capacity, 0) / price)

reduce_size does NOT halve each new order's notional -- it halves the
PORTFOLIO-WIDE exposure cap (e.g. dynamic_exposure_cap=0.83 -> 0.415).
Confirmed live 2026-08-26: with current_total_exposure=$455,632 (47.3% of
equity) and the halved cap capping max_total_exposure_usd at $399,452
(41.5% of equity), remaining_capacity was $0 and EVERY buy candidate was
rejected with skip_reason=insufficient_remaining_exposure -- a binary
on/off block, not a size reduction, whenever the ALREADY-OPEN book exceeds
the halved cap.

This script re-simulates R11-B's baseline with this ACTUAL mechanism:
track portfolio-level open notional across the whole simulation (not just
per-trade sizing), apply exposure_cap_override=dynamic_cap*0.5 when
consecutive_losing_trades>=5 (same threshold/rule as the 2026-08-15
script), and measure both (a) how often reduce_size fully blocks ALL new
entries (not just shrinks them) and (b) the resulting PnL difference vs.
baseline.

Usage:
    python scripts/r0v2_reduce_size_portfolio_level_check.py [--save]
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
from stock_swing.guardrails.risk_snapshot import compute_consecutive_losing_trades  # noqa: E402
from stock_swing.risk.position_sizing import PositionSizingInputs, PositionSizingPolicy  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
REDUCE_SIZE_THRESHOLD = 5
REDUCE_SIZE_MULTIPLIER = 0.5
BASE_EXPOSURE_CAP = 0.68  # matches paper_demo.py's _BASE_EXPOSURE_CAP (dynamic bonus omitted here
                           # for simplicity -- see LIMITATIONS; using the static base is a
                           # conservative simplification, not the full signal-count-dependent formula)


def to_pnl_tracker_shape(trade: dict[str, Any]) -> dict[str, Any]:
    return {"status": "closed", "exit_time": trade["exit_date"] + "T21:00:00+00:00", "pnl": trade["pnl"]}


def run_simulation(
    symbols: list[str],
    equity: float,
    apply_reduce_size: bool,
) -> dict[str, Any]:
    """Simulate R11-B's entry/exit logic with REAL PositionSizingPolicy
    portfolio-level exposure tracking. When apply_reduce_size=True, the
    exposure cap is halved whenever consecutive_losing_trades>=5 (matching
    production's ACTUAL binary block-or-allow mechanism, not a per-trade
    notional halving).
    """
    price_data = base.load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(f"Simulating {len(symbols)} symbols, equity=${equity:,.0f}, "
          f"apply_reduce_size={apply_reduce_size} (portfolio-level exposure cap mechanism)")

    entry_strategy = base.BreakoutMomentumStrategy(min_momentum=0.05, min_signal_strength=0.40)
    exit_strategy = base.load_exit_strategy()
    sizing_policy = PositionSizingPolicy()

    open_positions: dict[str, base.Position] = {}
    closed_trades: list[dict[str, Any]] = []
    reduce_size_active_days = 0
    fully_blocked_days = 0  # days where reduce_size was active AND >=1 candidate existed AND ALL were rejected for exposure
    candidates_seen_while_reduced = 0
    candidates_blocked_while_reduced = 0

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

            # --- Exits ---
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
                        })
                        del open_positions[sym]

            # --- Determine reduce_size state (same rule as 2026-08-15 script) ---
            trades_so_far = [to_pnl_tracker_shape(t) for t in closed_trades]
            consecutive = compute_consecutive_losing_trades(trades_so_far)
            reduce_size_active = apply_reduce_size and consecutive >= REDUCE_SIZE_THRESHOLD
            if reduce_size_active:
                reduce_size_active_days += 1
            exposure_cap = BASE_EXPOSURE_CAP * (REDUCE_SIZE_MULTIPLIER if reduce_size_active else 1.0)

            # --- Current portfolio-level open notional (mark-to-market at last close) ---
            current_total_exposure = sum(
                pos.qty * (price_data.get(sym, {}).get(date_str, {}).get("close") or pos.entry_price)
                for sym, pos in open_positions.items()
            )

            # --- Entry candidates ---
            candidate_records = []
            for sym, recs in features_by_symbol.items():
                if sym not in open_positions:
                    candidate_records.extend(recs)  # full window needed for momentum compute()
            if candidate_records:
                candidate_momentum = momentum_feat.compute(candidate_records)
                buy_signals = entry_strategy.generate(candidate_momentum)

                day_blocked = 0
                day_seen = 0
                for sig in buy_signals:
                    sym = sig.symbol
                    if sym in open_positions:
                        continue
                    bar = price_data.get(sym, {}).get(date_str)
                    if bar is None or bar.get("close", 0) <= 0:
                        continue
                    price = bar["close"]

                    sizing_result = sizing_policy.size(PositionSizingInputs(
                        account_equity=equity,
                        current_price=price,
                        current_total_exposure=current_total_exposure,
                        market_regime="bullish",
                        symbol=sym,
                        confidence=sig.confidence if hasattr(sig, "confidence") else None,
                        exposure_cap_override=exposure_cap,
                    ))

                    if reduce_size_active:
                        day_seen += 1
                        candidates_seen_while_reduced += 1

                    if sizing_result.final_shares < 1:
                        if reduce_size_active:
                            day_blocked += 1
                            candidates_blocked_while_reduced += 1
                        continue

                    qty = sizing_result.final_shares
                    open_positions[sym] = base.Position(
                        symbol=sym, entry_date=current_dt, entry_price=price,
                        qty=qty, entry_signal_strength=sig.signal_strength,
                    )
                    current_total_exposure += qty * price

                if reduce_size_active and day_seen > 0 and day_blocked == day_seen:
                    fully_blocked_days += 1
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
            "entry_price": pos.entry_price, "exit_date": final_date,
            "exit_price": exit_price, "qty": pos.qty, "pnl": pnl,
            "return_pct": return_pct, "holding_days": hold_days,
            "exit_reason": "backtest_end_forced_close",
            "entry_signal_strength": pos.entry_signal_strength,
        })

    return {
        "trades": closed_trades,
        "reduce_size_active_days": reduce_size_active_days,
        "fully_blocked_days": fully_blocked_days,
        "candidates_seen_while_reduced": candidates_seen_while_reduced,
        "candidates_blocked_while_reduced": candidates_blocked_while_reduced,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--equity", type=float, default=1_000_000.0)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_"))
    print(f"Universe: {len(symbols)} symbols\n")

    print("=" * 90)
    print("Baseline (no reduce_size)")
    print("=" * 90)
    baseline_result = run_simulation(symbols, args.equity, apply_reduce_size=False)
    baseline_summary = base.summarize(baseline_result["trades"], "baseline")
    print(json.dumps(baseline_summary, indent=2, default=str))

    print("\n" + "=" * 90)
    print("With reduce_size (ACTUAL portfolio-level exposure-cap-halving mechanism)")
    print("=" * 90)
    reduced_result = run_simulation(symbols, args.equity, apply_reduce_size=True)
    reduced_summary = base.summarize(reduced_result["trades"], "with_reduce_size")
    print(json.dumps(reduced_summary, indent=2, default=str))

    print(f"\nreduce_size active days: {reduced_result['reduce_size_active_days']}")
    print(f"Days where reduce_size was active AND fully blocked ALL candidates: "
          f"{reduced_result['fully_blocked_days']}")
    print(f"Candidates seen while reduce_size active: {reduced_result['candidates_seen_while_reduced']}")
    print(f"Candidates blocked (insufficient_remaining_exposure) while active: "
          f"{reduced_result['candidates_blocked_while_reduced']}")
    if reduced_result["candidates_seen_while_reduced"] > 0:
        block_rate = reduced_result["candidates_blocked_while_reduced"] / reduced_result["candidates_seen_while_reduced"]
        print(f"Block rate while reduce_size active: {block_rate:.1%}")

    print("\n" + "=" * 90)
    print("COMPARISON: this run (portfolio-level cap) vs 2026-08-15 script (per-trade notional halving)")
    print("=" * 90)
    print(f"  {'metric':30} {'baseline':>15} {'with_reduce_size':>18}")
    print(f"  {'n':30} {baseline_summary['n']:>15} {reduced_summary['n']:>18}")
    print(f"  {'profit_factor':30} {baseline_summary.get('profit_factor')!s:>15} {reduced_summary.get('profit_factor')!s:>18}")
    print(f"  {'net_pnl':30} {baseline_summary.get('net_pnl')!s:>15} {reduced_summary.get('net_pnl')!s:>18}")
    print("\n  2026-08-15 script found: PF 0.560->0.578 in validation window, only 24/226 (11%)")
    print("  of trades affected -- a MILD, gradual per-trade sizing effect.")
    print("  This run measures the ACTUAL binary block-or-allow effect when the portfolio's")
    print("  existing open book already exceeds the halved exposure cap.")

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r0v2_reduce_size_portfolio_level_20260826"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "results.json"
        out_path.write_text(json.dumps({
            "baseline": baseline_summary,
            "with_reduce_size": reduced_summary,
            "reduce_size_active_days": reduced_result["reduce_size_active_days"],
            "fully_blocked_days": reduced_result["fully_blocked_days"],
            "candidates_seen_while_reduced": reduced_result["candidates_seen_while_reduced"],
            "candidates_blocked_while_reduced": reduced_result["candidates_blocked_while_reduced"],
        }, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
