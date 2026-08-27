#!/usr/bin/env python3
"""R11-C RSI-reversed candidate: re-test WITHOUT the v4 engine's "one
position per symbol" exclusivity rule, to isolate the RSI filter's direct
effect from the entry-timing-shift artifact discovered in
r11c_rsi_threshold_grid_rolling_wf.py.

Background (2026-08-26, same-day follow-up): the threshold grid search
found that most of the RSI-reversed filter's apparent improvement came not
from avoiding bad entries directly, but from an artifact of v4's `if sym in
open_positions or sym in pending_entries: continue` exclusivity rule --
blocking one day's signal for a symbol frees that symbol's "slot" for a
later day's signal on the SAME symbol. Reading the actual production
decision path (RiskValidator.validate(), BreakoutMomentumStrategy.
generate(), EntryFilterEngine.filter(), paper_demo.py's position-limit
check) confirmed NONE of them block a new BUY on a symbol that already has
an open position -- production only caps by DOLLAR AMOUNT
(position_limit_pct), not by position count. So this timing-shift artifact
would NOT occur in production the same way.

This script re-runs the RSI-reversed candidate on a MODIFIED v4 engine
that allows unlimited concurrent positions per symbol (removing the
exclusivity gate, closer to production's dollar-cap-only behavior), to
measure the RSI filter's effect with the artifact removed.

NOTE: this is still a simplification, not a full reproduction of
production's dollar-based position_limit_pct gate (which requires a
live equity curve and per-symbol notional tracking this fixed-notional
engine does not have). It answers a narrower question: "with the
symbol-exclusivity confound removed entirely, does the RSI filter still
show an effect purely from avoiding bad entries?" A definitively
production-faithful backtest would need the dollar-cap logic ported in
separately (documented as a further limitation, not fixed here).

Usage:
    python scripts/r11c_rsi_no_symbol_exclusivity.py --save
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from stock_swing.core.types import CanonicalRecord  # noqa: E402
from stock_swing.feature_engine.price_momentum_feature import (  # noqa: E402
    PriceMomentumFeature,
)
from stock_swing.strategy_engine.breakout_momentum_strategy import (  # noqa: E402
    BreakoutMomentumStrategy,
)

import r11_backtest_engine as base  # noqa: E402
from r11_backtest_engine import load_exit_strategy, load_price_data, make_record, summarize  # noqa: E402
from r11_backtest_engine_v2 import load_universe_intro_dates  # noqa: E402
from r11_backtest_engine_v3 import Position, _check_conservative_exit_for_day  # noqa: E402
from r11_backtest_engine_v4 import CACHE_DIR, BAR_LIMIT  # noqa: E402
from r11c_candidate_backtest import build_rsi_reversed_filter  # noqa: E402
from r11c_v2_rigorous_rerun import load_symbol_registry  # noqa: E402

REGISTRY_PATH = PROJECT_ROOT / "config" / "reference" / "symbol_registry.yaml"


def run_backtest_no_exclusivity(
    symbols: list[str],
    notional: float,
    entry_filter: Callable[[str, str], bool] | None,
    min_momentum: float = 0.05,
    min_signal_strength: float = 0.40,
    enforce_point_in_time_universe: bool = True,
    conservative_ohlc: bool = True,
    slippage_bps: float = 0.0,
) -> dict[str, Any]:
    """Same t+1 fill / PIT universe / conservative exit / slippage as v4,
    but with NO gross/sector/cluster caps AND no "one position per symbol"
    exclusivity -- a NEW signal for a symbol that already has an open
    position is allowed to open an ADDITIONAL position (closer to
    production's dollar-cap-only, position-count-unlimited behavior).

    Each symbol can have multiple concurrently-open positions (list, not
    a single dict entry), each tracked and exited independently -- mirrors
    production's per-lot tracking (see pnl_state.json's multi-lot symbols
    like LRCX/IBM, confirmed 2026-08-26).
    """
    price_data = load_price_data(symbols)
    if not price_data:
        raise RuntimeError(f"No cached price data found in {CACHE_DIR}; run r11_fetch_historical_data.py first")

    intro_dates = load_universe_intro_dates() if enforce_point_in_time_universe else {}
    slippage_factor = slippage_bps / 10_000.0

    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(
        f"Simulating {len(symbols)} symbols over {len(all_dates)} trading days "
        f"({all_dates[0]} -> {all_dates[-1]}); NO symbol exclusivity, NO caps; "
        f"point_in_time_universe={enforce_point_in_time_universe}; "
        f"slippage_bps={slippage_bps}; entry_filter={'yes' if entry_filter else 'none (baseline)'}"
    )

    entry_strategy = BreakoutMomentumStrategy(
        min_momentum=min_momentum, min_signal_strength=min_signal_strength
    )
    exit_strategy = load_exit_strategy()

    # KEY CHANGE: open_positions is now list[Position] per symbol, not one
    # Position per symbol -- multiple concurrent lots allowed.
    open_positions: dict[str, list[Position]] = {}
    closed_trades: list[dict[str, Any]] = []
    pending_entries: list[dict[str, Any]] = []  # KEY CHANGE: list, not dict keyed by symbol
    filter_dropped_count = 0

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        base._freeze(current_dt)
        try:
            # --- Fill ALL pending entries at today's open (no capacity gate) ---
            for pending in pending_entries:
                sym = pending["symbol"]
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None or bar.get("open", 0) <= 0:
                    continue
                raw_entry_price = bar["open"]
                entry_price = raw_entry_price * (1 + slippage_factor)
                qty = notional / entry_price
                open_positions.setdefault(sym, []).append(Position(
                    symbol=sym, entry_date=current_dt, entry_price=entry_price,
                    qty=qty, entry_signal_strength=pending["signal_strength"],
                    signal_date=pending["signal_date"],
                ))
            pending_entries = []

            window_start_idx = max(0, i - BAR_LIMIT + 1)
            window_dates = all_dates[window_start_idx : i + 1]

            eligible_symbols = set(price_data.keys())
            if enforce_point_in_time_universe:
                eligible_symbols = {
                    sym for sym in eligible_symbols
                    if intro_dates.get(sym, "1970-01-01") <= date_str
                }

            features_by_symbol: dict[str, list[CanonicalRecord]] = {}
            for sym in eligible_symbols:
                bars = price_data.get(sym, {})
                recs = [make_record(sym, d, bars[d]) for d in window_dates if d in bars]
                if recs:
                    features_by_symbol[sym] = recs

            momentum_feat = PriceMomentumFeature(period_days=BAR_LIMIT)

            # --- Check exits for ALL open positions (each lot independently) ---
            for sym, positions in list(open_positions.items()):
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None:
                    continue
                still_open = []
                for pos in positions:
                    hold_days = (current_dt - pos.entry_date).days
                    exit_result = _check_conservative_exit_for_day(
                        exit_strategy, pos, bar, hold_days,
                        volatility_multiplier=1.0,
                        conservative_ohlc=conservative_ohlc,
                    )
                    if exit_result is None:
                        still_open.append(pos)
                        continue
                    raw_exit_price = exit_result["exit_price"]
                    exit_price = raw_exit_price * (1 - slippage_factor)
                    pnl = (exit_price - pos.entry_price) * pos.qty
                    return_pct = (exit_price - pos.entry_price) / pos.entry_price
                    closed_trades.append({
                        "symbol": sym, "signal_date": pos.signal_date,
                        "entry_date": pos.entry_date.date().isoformat(),
                        "entry_price": pos.entry_price, "exit_date": date_str,
                        "exit_price": exit_price, "qty": pos.qty, "pnl": pnl,
                        "return_pct": return_pct, "holding_days": hold_days,
                        "exit_reason": exit_result["exit_reason"],
                        "entry_signal_strength": pos.entry_signal_strength,
                    })
                if still_open:
                    open_positions[sym] = still_open
                else:
                    del open_positions[sym]

            # --- Entry candidate generation: NO check for existing position ---
            candidate_records = []
            for sym, recs in features_by_symbol.items():
                candidate_records.extend(recs)
            if candidate_records:
                candidate_momentum = momentum_feat.compute(candidate_records)
                buy_signals = entry_strategy.generate(candidate_momentum)
                for sig in buy_signals:
                    sym = sig.symbol
                    # KEY CHANGE: no "already open/pending" skip -- a symbol
                    # with an existing position can still receive a NEW
                    # signal and open an additional lot (mirrors production's
                    # lack of a position-count exclusivity gate).
                    if entry_filter is not None and not entry_filter(sym, date_str):
                        filter_dropped_count += 1
                        continue
                    pending_entries.append({
                        "symbol": sym,
                        "signal_strength": sig.signal_strength,
                        "signal_date": date_str,
                    })
        finally:
            base._unfreeze()

        if (i + 1) % 200 == 0:
            open_count = sum(len(v) for v in open_positions.values())
            print(f"  {i+1}/{len(all_dates)} days, {len(closed_trades)} closed, "
                  f"{open_count} open (lots), {filter_dropped_count} filter-dropped")

    final_date = all_dates[-1]
    for sym, positions in open_positions.items():
        bar = price_data.get(sym, {}).get(final_date)
        if bar is None:
            continue
        for pos in positions:
            raw_exit_price = bar["close"]
            exit_price = raw_exit_price * (1 - slippage_factor)
            pnl = (exit_price - pos.entry_price) * pos.qty
            return_pct = (exit_price - pos.entry_price) / pos.entry_price
            hold_days = (datetime.fromisoformat(final_date).replace(tzinfo=timezone.utc) - pos.entry_date).days
            closed_trades.append({
                "symbol": sym, "signal_date": pos.signal_date,
                "entry_date": pos.entry_date.date().isoformat(), "exit_date": final_date,
                "entry_price": pos.entry_price, "exit_price": exit_price, "qty": pos.qty,
                "pnl": pnl, "return_pct": return_pct, "holding_days": hold_days,
                "exit_reason": "backtest_end_forced_close",
                "entry_signal_strength": pos.entry_signal_strength,
            })

    return {
        "trades": closed_trades,
        "date_range": [all_dates[0], all_dates[-1]],
        "symbols": symbols,
        "notional_per_trade": notional,
        "point_in_time_universe": enforce_point_in_time_universe,
        "conservative_ohlc": conservative_ohlc,
        "slippage_bps": slippage_bps,
        "filter_dropped_count": filter_dropped_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="R11-C RSI-reversed: no symbol exclusivity (production-like)")
    parser.add_argument("--notional", type=float, default=10_000.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--threshold", type=float, default=75.0)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    registry = load_symbol_registry(REGISTRY_PATH)
    cached_symbols = {p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_")}
    symbols = sorted(set(registry.keys()) & cached_symbols)
    print(f"Universe: {len(symbols)} symbols (registry \u2229 cached price data)")

    print("\nRunning BASELINE (no filter, no symbol exclusivity, no caps)...")
    baseline_result = run_backtest_no_exclusivity(
        symbols=symbols, notional=args.notional, entry_filter=None,
        enforce_point_in_time_universe=True, conservative_ohlc=True,
        slippage_bps=args.slippage_bps,
    )
    baseline_summary = summarize(baseline_result["trades"], "baseline_no_exclusivity")
    print(json.dumps(baseline_summary, indent=2, default=str))

    print(f"\nRunning RSI-reversed (threshold={args.threshold}, no symbol exclusivity, no caps)...")
    entry_filter = build_rsi_reversed_filter(symbols, threshold=args.threshold)
    filtered_result = run_backtest_no_exclusivity(
        symbols=symbols, notional=args.notional, entry_filter=entry_filter,
        enforce_point_in_time_universe=True, conservative_ohlc=True,
        slippage_bps=args.slippage_bps,
    )
    filtered_summary = summarize(filtered_result["trades"], f"rsi_{args.threshold}_no_exclusivity")
    filtered_summary["filter_dropped_count"] = filtered_result["filter_dropped_count"]
    print(json.dumps(filtered_summary, indent=2, default=str))

    print(f"\n{'='*90}\nCOMPARISON (production-like: no symbol exclusivity, dollar-cap-only regime NOT modeled)\n{'='*90}")
    for key in ("n", "win_rate", "profit_factor", "net_pnl", "avg_return_pct"):
        b = baseline_summary.get(key)
        c = filtered_summary.get(key)
        print(f"  {key:16} baseline={b!s:>12}  rsi_filtered={c!s:>12}")

    all_results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "v4-derived engine WITHOUT one-position-per-symbol exclusivity "
                        "and WITHOUT gross/sector/cluster caps -- isolates RSI filter's "
                        "direct effect from the entry-timing-shift artifact found in "
                        "r11c_rsi_threshold_grid_rolling_wf.py. Still a simplification: "
                        "production's actual dollar-based position_limit_pct cap is NOT "
                        "modeled here either (documented limitation).",
        "threshold": args.threshold,
        "slippage_bps": args.slippage_bps,
        "baseline": baseline_summary,
        "rsi_filtered": filtered_summary,
    }

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r11c_rsi_no_symbol_exclusivity_20260826"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "results.json"
        out_path.write_text(json.dumps(all_results, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
