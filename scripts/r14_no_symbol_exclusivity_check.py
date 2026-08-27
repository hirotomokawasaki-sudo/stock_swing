#!/usr/bin/env python3
"""R14 dip-buy follow-up (2026-08-26): re-test WITHOUT the "one position per
symbol" exclusivity rule, applying the same self-critique methodology used
for R11-C the same day (see docs/r11c_rsi_no_symbol_exclusivity_20260826/).

Background: r14_dip_buy_meanreversion_phase1.py's own docstring already
explicitly disclosed "one open position per symbol" as a simplification
(Limitations section), but did not measure how much that simplification
affects the headline GO-verdict numbers. Earlier the same day
(2026-08-26), the SAME simplification in the unrelated R11-C RSI-reversed
candidate was found to be responsible for essentially ALL of that
candidate's apparent improvement -- once removed, the effect vanished. This
script checks whether R14's dip-buy GO verdict (PF=1.963 vs momentum
PF=1.854, point-in-time universe, 2026-08-25) is similarly inflated by the
same mechanism, or is robust to it.

WHY THIS MATTERS MORE FOR DIP-BUY SPECIFICALLY: mean-reversion/dip-buying
strategies are structurally more likely than momentum strategies to fire
repeated signals on the SAME symbol across consecutive days during a
sustained decline (e.g. NVDA drops -5% on day 1, is still "bearish" and
still down on day 2, fires again). Under the one-position-per-symbol rule,
only the FIRST such signal can ever open a position; every subsequent
signal for that symbol is silently dropped from candidate_records (see
phase1's `if sym not in open_positions and sym not in pending_entries`
filter) until the first position exits. In production (confirmed
2026-08-26: RiskValidator.validate() ignores current_positions entirely,
paper_demo.py only enforces a DOLLAR cap not a position-count cap), a
security could receive MULTIPLE dip-buy entries while already down and
still declining -- i.e. production would add to a position that's actively
losing, which the Phase 1 backtest cannot see happening at all.

This script removes the exclusivity gate entirely (matching
r11c_rsi_no_symbol_exclusivity.py's approach) so a symbol can accumulate
multiple concurrent dip-buy lots, each tracked and exited independently,
and re-measures PF/WR/net_pnl against both point-in-time-universe and
full-history variants (mirroring Phase 1's own two headline comparisons).

This does NOT modify dip_buy_meanreversion_strategy.py, paper_demo.py, or
any production file. Read-only research artifact.

Usage:
    python scripts/r14_no_symbol_exclusivity_check.py --save
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

from stock_swing.feature_engine.price_momentum_feature import (  # noqa: E402
    PriceMomentumFeature,
)

from r11_backtest_engine import _freeze, _unfreeze, load_exit_strategy, load_price_data, make_record, summarize  # noqa: E402
from r11_backtest_engine_v2 import load_universe_intro_dates  # noqa: E402
from r11_backtest_engine_v3 import BAR_LIMIT, CACHE_DIR, Position, _check_conservative_exit_for_day  # noqa: E402
from r14_dip_buy_meanreversion_phase1 import DipBuyMeanReversionStrategy  # noqa: E402


def run_dip_buy_no_exclusivity(
    symbols: list[str],
    notional: float,
    min_momentum_drop: float,
    min_signal_strength: float,
    slippage_bps: float,
    enforce_point_in_time_universe: bool,
) -> dict[str, Any]:
    """Same fill/exit/cost model as Phase 1's run_dip_buy_backtest(), minus
    the one-position-per-symbol exclusivity gate. A symbol with an open
    position can still receive a NEW dip-buy signal and open an additional
    lot (mirrors production's lack of a position-count exclusivity gate,
    confirmed 2026-08-26 by reading RiskValidator.validate()/paper_demo.py).
    """
    price_data = load_price_data(symbols)
    if not price_data:
        raise RuntimeError(f"No cached price data found in {CACHE_DIR}; run r11_fetch_historical_data.py first")

    intro_dates = load_universe_intro_dates() if enforce_point_in_time_universe else {}
    slippage_factor = slippage_bps / 10_000.0

    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(
        f"Simulating dip-buy (NO symbol exclusivity): {len(symbols)} symbols, {len(all_dates)} days "
        f"({all_dates[0]} -> {all_dates[-1]}), min_momentum_drop={min_momentum_drop}, "
        f"slippage_bps={slippage_bps}, PIT={enforce_point_in_time_universe}"
    )

    dip_strategy = DipBuyMeanReversionStrategy(min_momentum_drop=min_momentum_drop, min_signal_strength=min_signal_strength)
    exit_strategy = load_exit_strategy()

    # KEY CHANGE: multiple concurrent lots per symbol allowed.
    open_positions: dict[str, list[Position]] = {}
    closed_trades: list[dict[str, Any]] = []
    pending_entries: list[dict[str, Any]] = []

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        _freeze(current_dt)
        try:
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

            if enforce_point_in_time_universe:
                eligible_symbols = {
                    sym for sym in price_data.keys()
                    if intro_dates.get(sym, "1970-01-01") <= date_str
                }
            else:
                eligible_symbols = set(price_data.keys())

            features_by_symbol = {}
            for sym in eligible_symbols:
                bars = price_data.get(sym, {})
                recs = [make_record(sym, d, bars[d]) for d in window_dates if d in bars]
                if recs:
                    features_by_symbol[sym] = recs

            momentum_feat = PriceMomentumFeature(period_days=BAR_LIMIT)

            # --- Exits: check every open lot independently ---
            for sym, positions in list(open_positions.items()):
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None:
                    continue
                still_open = []
                for pos in positions:
                    hold_days = (current_dt - pos.entry_date).days
                    exit_result = _check_conservative_exit_for_day(
                        exit_strategy, pos, bar, hold_days, volatility_multiplier=1.0, conservative_ohlc=True,
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
                buy_signals = dip_strategy.generate(candidate_momentum)
                for sig in buy_signals:
                    # KEY CHANGE: no skip for symbols with an existing
                    # position -- a symbol that keeps declining can receive
                    # MULTIPLE dip-buy entries while still down (mirrors
                    # production's lack of position-count exclusivity).
                    pending_entries.append({
                        "symbol": sig.symbol,
                        "signal_strength": sig.signal_strength,
                        "signal_date": date_str,
                    })
        finally:
            _unfreeze()

        if (i + 1) % 100 == 0:
            open_count = sum(len(v) for v in open_positions.values())
            print(f"  {i+1}/{len(all_dates)} days, {len(closed_trades)} closed, {open_count} open (lots)")

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
        "point_in_time_universe": enforce_point_in_time_universe,
        "slippage_bps": slippage_bps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="R14 dip-buy: no symbol exclusivity (production-like) check")
    parser.add_argument("--notional", type=float, default=10_000.0)
    parser.add_argument("--min-momentum-drop", type=float, default=0.05)
    parser.add_argument("--min-signal-strength", type=float, default=0.40)
    parser.add_argument("--slippage-bps", type=float, default=10.0,
                         help="Matches Phase 1's own default (r14_dip_buy_meanreversion_phase1.py)")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    import yaml
    registry_path = PROJECT_ROOT / "config" / "reference" / "symbol_registry.yaml"
    with open(registry_path) as f:
        registry = yaml.safe_load(f)["symbols"]
    cached_symbols = {p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_")}
    symbols = sorted(set(registry.keys()) & cached_symbols)
    print(f"Universe: {len(symbols)} symbols\n")

    all_results: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "Phase1-derived dip-buy engine WITHOUT one-position-per-symbol "
                        "exclusivity -- checks whether Phase 1's GO verdict (PF=1.963 PIT "
                        "/ PF=1.710 full-history) is inflated by the same "
                        "entry-timing-shift/re-entry mechanism found the same day (2026-08-26) "
                        "in the unrelated R11-C RSI-reversed candidate.",
        "variants": {},
    }

    chop_start, chop_end = "2025-11-01", "2026-03-31"
    trades_by_variant: dict[str, list[dict[str, Any]]] = {}

    for pit_label, pit_flag in [("point_in_time_universe", True), ("full_history", False)]:
        print(f"{'='*90}\nVariant: {pit_label} (PIT={pit_flag})\n{'='*90}")
        result = run_dip_buy_no_exclusivity(
            symbols=symbols, notional=args.notional,
            min_momentum_drop=args.min_momentum_drop,
            min_signal_strength=args.min_signal_strength,
            slippage_bps=args.slippage_bps,
            enforce_point_in_time_universe=pit_flag,
        )
        s = summarize(result["trades"], f"dip_buy_no_exclusivity_{pit_label}")
        print(json.dumps(s, indent=2, default=str))
        all_results["variants"][pit_label] = s
        trades_by_variant[pit_label] = result["trades"]

        chop_trades = [t for t in result["trades"] if chop_start <= t["entry_date"] <= chop_end]
        chop_s = summarize(chop_trades, f"dip_buy_no_exclusivity_{pit_label}_chop")
        print(f"  Chop window ({chop_start}~{chop_end}): {json.dumps(chop_s, default=str)}")
        all_results["variants"][f"{pit_label}_chop_window"] = chop_s

    print(f"\n{'='*90}\nCOMPARISON vs Phase 1 headline (WITH exclusivity, 2026-08-25)\n{'='*90}")
    print(f"{'variant':30} {'Phase1 (w/ exclusivity)':>28} {'this run (no exclusivity)':>28}")
    phase1_pit = {"n": 359, "profit_factor": 1.963}
    phase1_full = {"n": 1938, "profit_factor": 1.710}
    this_pit = all_results["variants"]["point_in_time_universe"]
    this_full = all_results["variants"]["full_history"]
    print(f"{'point_in_time_universe':30} n={phase1_pit['n']:>4} PF={phase1_pit['profit_factor']:>6}"
          f"{'':>8} n={this_pit['n']:>4} PF={this_pit.get('profit_factor')!s:>6}")
    print(f"{'full_history':30} n={phase1_full['n']:>4} PF={phase1_full['profit_factor']:>6}"
          f"{'':>8} n={this_full['n']:>4} PF={this_full.get('profit_factor')!s:>6}")

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r14_no_symbol_exclusivity_check_20260826"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "results.json"
        out_path.write_text(json.dumps(all_results, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
