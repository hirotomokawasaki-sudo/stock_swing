#!/usr/bin/env python3
"""R15 follow-up (2026-08-27): does the intraday-boost effect measured in
r15_intraday_backtest_engine.py (+0.83% PF, +1.19% net_pnl on the v4
engine WITH its "one position per symbol" exclusivity rule) survive when
combined with the newer, more rigorous "no symbol exclusivity" engine
(scripts/r11c_rsi_no_symbol_exclusivity.py / r14_no_symbol_exclusivity_check.py,
2026-08-26), which found that exclusivity was itself an artifact-generator
for a DIFFERENT candidate (RSI mean-reversion filter) the same day?

WHY THIS MATTERS: 08-26 established a general anti-pattern -- "an entry/
exit-adjacent backtest mechanism can look like it works because it
interacts with the engine's one-position-per-symbol cap, not because of
its own real effect." The original R15 intraday-boost check (08-27,
earlier the same day) was run on the WITH-exclusivity v4 engine and never
cross-checked against the no-exclusivity engine. This closes that gap
before treating the "+0.83% PF, small but real, positive" R15 conclusion
as final.

Reuses r15_intraday_backtest_engine.py's compute_intraday_boost() (import,
not reimplementation) and r11c_rsi_no_symbol_exclusivity.py's
run_backtest_no_exclusivity() structure, merged so intraday boost can be
applied at signal-generation time even when a symbol already has open
lot(s).

This does NOT modify any production file. Read-only research artifact.

Usage:
    python scripts/r15_intraday_no_exclusivity_check.py --save
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

from stock_swing.core.types import CanonicalRecord  # noqa: E402
from stock_swing.feature_engine.price_momentum_feature import PriceMomentumFeature  # noqa: E402
from stock_swing.strategy_engine.breakout_momentum_strategy import BreakoutMomentumStrategy  # noqa: E402

import r11_backtest_engine as base  # noqa: E402
from r11_backtest_engine import load_exit_strategy, load_price_data, make_record, summarize  # noqa: E402
from r11_backtest_engine_v2 import load_universe_intro_dates  # noqa: E402
from r11_backtest_engine_v3 import Position, _check_conservative_exit_for_day  # noqa: E402
from r11_backtest_engine_v4 import CACHE_DIR, BAR_LIMIT  # noqa: E402
from r15_intraday_backtest_engine import (  # noqa: E402
    INTRADAY_CACHE_DIR,
    bars_for_date,
    compute_intraday_boost,
    load_intraday_bars,
    load_intraday_config,
)


def run_backtest_no_exclusivity_intraday(
    symbols: list[str],
    notional: float,
    use_intraday_boost: bool,
    min_momentum: float = 0.05,
    min_signal_strength: float = 0.40,
    enforce_point_in_time_universe: bool = True,
    conservative_ohlc: bool = True,
    slippage_bps: float = 5.0,
) -> dict[str, Any]:
    """r11c_rsi_no_symbol_exclusivity.py's engine (no position-count cap,
    no gross/sector/cluster caps, multi-lot per symbol) + production's
    real intraday-boost mechanism applied at signal time."""
    price_data = load_price_data(symbols)
    if not price_data:
        raise RuntimeError(f"No cached price data in {CACHE_DIR}")

    intraday_bars_by_symbol = load_intraday_bars(symbols) if use_intraday_boost else {}
    intraday_cfg = load_intraday_config()
    intro_dates = load_universe_intro_dates() if enforce_point_in_time_universe else {}
    slippage_factor = slippage_bps / 10_000.0

    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(
        f"Simulating {len(symbols)} symbols over {len(all_dates)} days "
        f"({all_dates[0]} -> {all_dates[-1]}); NO exclusivity/caps; "
        f"use_intraday_boost={use_intraday_boost}"
    )

    entry_strategy = BreakoutMomentumStrategy(min_momentum=min_momentum, min_signal_strength=min_signal_strength)
    exit_strategy = load_exit_strategy()

    open_positions: dict[str, list[Position]] = {}
    closed_trades: list[dict[str, Any]] = []
    pending_entries: list[dict[str, Any]] = []
    boosted_count = 0
    boost_eligible_count = 0

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        base._freeze(current_dt)
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
            eligible_symbols = set(price_data.keys())
            if enforce_point_in_time_universe:
                eligible_symbols = {s for s in eligible_symbols if intro_dates.get(s, "1970-01-01") <= date_str}

            features_by_symbol: dict[str, list[CanonicalRecord]] = {}
            for sym in eligible_symbols:
                bars = price_data.get(sym, {})
                recs = [make_record(sym, d, bars[d]) for d in window_dates if d in bars]
                if recs:
                    features_by_symbol[sym] = recs

            momentum_feat = PriceMomentumFeature(period_days=BAR_LIMIT)

            for sym, positions in list(open_positions.items()):
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None:
                    continue
                still_open = []
                for pos in positions:
                    hold_days = (current_dt - pos.entry_date).days
                    exit_result = _check_conservative_exit_for_day(
                        exit_strategy, pos, bar, hold_days, volatility_multiplier=1.0, conservative_ohlc=conservative_ohlc,
                    )
                    if exit_result is None:
                        still_open.append(pos)
                        continue
                    raw_exit_price = exit_result["exit_price"]
                    exit_price = raw_exit_price * (1 - slippage_factor)
                    pnl = (exit_price - pos.entry_price) * pos.qty
                    return_pct = (exit_price - pos.entry_price) / pos.entry_price
                    closed_trades.append({
                        "symbol": sym, "signal_date": pos.signal_date, "entry_date": pos.entry_date.date().isoformat(),
                        "entry_price": pos.entry_price, "exit_date": date_str, "exit_price": exit_price, "qty": pos.qty,
                        "pnl": pnl, "return_pct": return_pct, "holding_days": hold_days,
                        "exit_reason": exit_result["exit_reason"], "entry_signal_strength": pos.entry_signal_strength,
                    })
                if still_open:
                    open_positions[sym] = still_open
                else:
                    del open_positions[sym]

            candidate_records = []
            for sym, recs in features_by_symbol.items():
                candidate_records.extend(recs)
            if candidate_records:
                candidate_momentum = momentum_feat.compute(candidate_records)
                buy_signals = entry_strategy.generate(candidate_momentum)
                for sig in buy_signals:
                    sym = sig.symbol
                    final_strength = sig.signal_strength
                    if use_intraday_boost:
                        day_bars = bars_for_date(intraday_bars_by_symbol.get(sym, {}), date_str)
                        if day_bars:
                            boost_eligible_count += 1
                            should_boost, _, _ = compute_intraday_boost(
                                day_bars,
                                intraday_cfg["lookback_bars"], intraday_cfg["smoothing_window"],
                                intraday_cfg["vwap_threshold"], intraday_cfg["momentum_threshold"],
                            )
                            if should_boost:
                                final_strength = min(sig.signal_strength * 1.2, 1.0)
                                boosted_count += 1
                    pending_entries.append({"symbol": sym, "signal_strength": final_strength, "signal_date": date_str})
        finally:
            base._unfreeze()

        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(all_dates)} days, {len(closed_trades)} closed, "
                  f"boosted={boosted_count}/{boost_eligible_count}")

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
                "symbol": sym, "signal_date": pos.signal_date, "entry_date": pos.entry_date.date().isoformat(),
                "exit_date": final_date, "entry_price": pos.entry_price, "exit_price": exit_price, "qty": pos.qty,
                "pnl": pnl, "return_pct": return_pct, "holding_days": hold_days,
                "exit_reason": "backtest_end_forced_close", "entry_signal_strength": pos.entry_signal_strength,
            })

    return {"trades": closed_trades, "boosted_count": boosted_count, "boost_eligible_count": boost_eligible_count}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notional", type=float, default=10_000.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    intraday_symbols = sorted(p.stem for p in INTRADAY_CACHE_DIR.glob("*.json") if not p.stem.startswith("_"))
    print(f"Universe (has intraday cache): {len(intraday_symbols)} symbols\n")

    common = dict(symbols=intraday_symbols, notional=args.notional, slippage_bps=args.slippage_bps)

    print("=" * 90)
    print("NO-exclusivity, daily-only baseline")
    print("=" * 90)
    daily_result = run_backtest_no_exclusivity_intraday(use_intraday_boost=False, **common)
    daily_summary = summarize(daily_result["trades"], "no_excl_daily_only")
    print(json.dumps(daily_summary, indent=2, default=str))

    print("\n" + "=" * 90)
    print("NO-exclusivity, intraday-aware")
    print("=" * 90)
    intraday_result = run_backtest_no_exclusivity_intraday(use_intraday_boost=True, **common)
    intraday_summary = summarize(intraday_result["trades"], "no_excl_intraday_aware")
    print(json.dumps(intraday_summary, indent=2, default=str))
    if intraday_result["boost_eligible_count"] > 0:
        rate = intraday_result["boosted_count"] / intraday_result["boost_eligible_count"]
        print(f"Boost rate: {rate:.1%} ({intraday_result['boosted_count']}/{intraday_result['boost_eligible_count']})")

    print("\n" + "=" * 90)
    print("COMPARISON (no-exclusivity engine)")
    print("=" * 90)
    for key in ("n", "win_rate", "profit_factor", "net_pnl", "avg_return_pct"):
        d = daily_summary.get(key)
        i_ = intraday_summary.get(key)
        print(f"  {key:16} daily_only={d!s:>14}  intraday_aware={i_!s:>14}")

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r15_intraday_backtest_20260827"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "no_exclusivity_results.json").write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "methodology": "no-symbol-exclusivity engine (r11c_rsi_no_symbol_exclusivity.py "
                            "structure, multi-lot per symbol, no gross/sector/cluster caps) + "
                            "production's real intraday-boost mechanism, cross-checking whether "
                            "R15's original +0.83% PF finding (measured on the WITH-exclusivity "
                            "v4 engine) survives on the corrected no-exclusivity baseline.",
            "universe_size": len(intraday_symbols),
            "no_excl_daily_only": daily_summary,
            "no_excl_intraday_aware": intraday_summary,
            "boost_eligible_count": intraday_result["boost_eligible_count"],
            "boosted_count": intraday_result["boosted_count"],
        }, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved: {out_dir}/no_exclusivity_results.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
