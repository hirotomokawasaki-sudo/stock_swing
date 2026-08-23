#!/usr/bin/env python3
"""R13-C (2026-08-23): R11 backtest engine v2 -- fixes the two highest-
priority flaws identified in the R13-C roadmap item for the original
r11_backtest_engine.py:

  (1) Same-bar look-ahead bias: the v1 engine used day t's close as BOTH
      the input to the momentum/signal calculation AND the entry fill
      price for a position opened "on" day t -- i.e. it enters at a price
      that was only knowable at the close, using information that was
      only knowable at that same close. This engine computes the signal
      from data through day t's close, then fills the entry at day t+1's
      OPEN price (the earliest price actually tradeable after the signal
      could have been acted on). This mirrors, at daily-bar resolution,
      the same t -> t+1 execution lag real intraday paper trading has
      (paper_demo.py's cron runs after the trading day's activity window
      begins, never inside the same instant the qualifying bar closed).

  (2) Survivorship bias: the v1 engine applied the CURRENT (as of
      2026-08-23) 80-symbol config/reference/symbol_registry.yaml universe
      to the ENTIRE 2-year historical window, letting symbols that were
      only added to the live config in 2026-07/2026-08 (after the system
      had already observed how they performed) "trade" as far back as
      2024-08. This engine gates each symbol's eligibility per simulated
      day using scripts/r11_symbol_universe_intro_dates.py's derived
      per-symbol introduction dates (data/r11_price_cache/
      _symbol_universe_intro_dates.json) -- a symbol cannot generate an
      entry signal before the date it first appeared in this system's
      actual git history. See that script's docstring for the honest
      limitation of this proxy (it does not correct for symbol-SELECTION
      bias, only for post-hoc backdating of a symbol's tradeable window).

Deliberately NOT in scope for this v2 (see roadmap items 3-7, larger
follow-up effort if 1+2 change the headline result materially):
  - conservative OHLC-path stop/trailing re-simulation (still uses
    same-day close for exit decisions, unchanged from v1)
  - cash / gross exposure / sector cap enforcement
  - spread / slippage / market impact
  - rolling walk-forward + embargo
  - full parameter-search trial registry

Everything else (delegating actual trading-logic decisions to the real
production BreakoutMomentumStrategy / SimpleExitV2Strategy classes, fixed
notional per trade, one open position per symbol) is unchanged from v1 --
see r11_backtest_engine.py's module docstring for that rationale.

Usage:
    python scripts/r11_backtest_engine_v2.py [--symbols AAPL,MSFT] [--notional 10000] [--save]
    python scripts/r11_backtest_engine_v2.py --compare-v1   # also runs v1 engine on the
                                                              # same universe/dates for a
                                                              # side-by-side diff
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.core.types import CanonicalRecord  # noqa: E402
from stock_swing.feature_engine.price_momentum_feature import (  # noqa: E402
    PriceMomentumFeature,
)
import stock_swing.feature_engine.price_momentum_feature as _pmf_module  # noqa: E402
from stock_swing.strategy_engine.breakout_momentum_strategy import (  # noqa: E402
    BreakoutMomentumStrategy,
)
from stock_swing.strategy_engine.simple_exit_v2_strategy import (  # noqa: E402
    SimpleExitV2Strategy,
)
import stock_swing.strategy_engine.simple_exit_v2_strategy as _sev2_module  # noqa: E402

# Reuse v1's summarize/decile helpers and frozen-clock/config-loading
# machinery verbatim -- only run_backtest() itself changes.
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from r11_backtest_engine import (  # noqa: E402
    _freeze,
    _unfreeze,
    decile_summary,
    load_exit_strategy,
    load_price_data,
    make_record,
    summarize,
)

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
INTRO_DATES_PATH = CACHE_DIR / "_symbol_universe_intro_dates.json"
BAR_LIMIT = 20  # matches paper_demo.py --bar-limit default


def load_universe_intro_dates() -> dict[str, str]:
    if not INTRO_DATES_PATH.exists():
        raise RuntimeError(
            f"{INTRO_DATES_PATH} not found; run "
            "scripts/r11_symbol_universe_intro_dates.py --save first"
        )
    with open(INTRO_DATES_PATH) as f:
        return json.load(f)


class Position:
    __slots__ = ("symbol", "entry_date", "entry_price", "qty", "peak_price",
                 "entry_signal_strength", "signal_date")

    def __init__(self, symbol, entry_date, entry_price, qty, entry_signal_strength, signal_date):
        self.symbol = symbol
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.qty = qty
        self.peak_price = entry_price
        self.entry_signal_strength = entry_signal_strength
        self.signal_date = signal_date  # the day the signal was actually generated (t), vs entry_date (t+1 fill)


def run_backtest_v2(
    symbols: list[str],
    notional: float,
    min_momentum: float = 0.05,
    min_signal_strength: float = 0.40,
    enforce_point_in_time_universe: bool = True,
) -> dict[str, Any]:
    """Point-in-time universe + t+1 open fill variant of run_backtest().

    Loop structure per simulated day t (t = 0..N-2, since entries need a
    t+1 bar to fill against):
      1. Freeze clock to day t's close.
      2. Check exits for open positions using day t's close (unchanged
         from v1 -- exit-side look-ahead fix is a SEPARATE, larger roadmap
         item, not in this v2's scope).
      3. Compute momentum features from data through day t (only for
         symbols whose universe intro_date <= t, when point-in-time
         gating is enabled).
      4. Generate entry candidate signals from day t's data.
      5. For each qualifying signal, if day t+1 has an available OPEN
         price for that symbol, open the position AT DAY T+1'S OPEN
         (not day t's close) -- this is the core look-ahead fix.
    """
    price_data = load_price_data(symbols)
    if not price_data:
        raise RuntimeError(f"No cached price data found in {CACHE_DIR}; run r11_fetch_historical_data.py first")

    intro_dates = load_universe_intro_dates() if enforce_point_in_time_universe else {}

    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(f"Simulating {len(symbols)} symbols over {len(all_dates)} trading days "
          f"({all_dates[0]} -> {all_dates[-1]}); "
          f"point_in_time_universe={enforce_point_in_time_universe}")

    entry_strategy = BreakoutMomentumStrategy(
        min_momentum=min_momentum, min_signal_strength=min_signal_strength
    )
    exit_strategy = load_exit_strategy()

    open_positions: dict[str, Position] = {}
    closed_trades: list[dict[str, Any]] = []
    pending_entries: dict[str, dict[str, Any]] = {}  # symbol -> {signal_strength, signal_date}
    universe_gated_signal_count = 0

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        _freeze(current_dt)
        try:
            # --- 0. Fill any pending entries from yesterday's signal at TODAY's open ---
            for sym, pending in list(pending_entries.items()):
                if sym in open_positions:
                    del pending_entries[sym]
                    continue
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None or bar.get("open", 0) <= 0:
                    # No bar today (e.g. trading halt/holiday for this
                    # symbol) -- drop the stale signal rather than fill on
                    # a much later, stale price.
                    del pending_entries[sym]
                    continue
                entry_price = bar["open"]
                qty = notional / entry_price
                open_positions[sym] = Position(
                    symbol=sym,
                    entry_date=current_dt,
                    entry_price=entry_price,
                    qty=qty,
                    entry_signal_strength=pending["signal_strength"],
                    signal_date=pending["signal_date"],
                )
                del pending_entries[sym]

            # Build a rolling BAR_LIMIT-day window of records per symbol,
            # restricted to symbols whose universe intro_date has already
            # passed as of today (point-in-time universe gate).
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
            all_records: list[CanonicalRecord] = []
            for recs in features_by_symbol.values():
                all_records.extend(recs)
            momentum_results = momentum_feat.compute(all_records)

            # --- 1. Check exits for open positions (same-day close, v1-equivalent) ---
            if open_positions:
                current_positions_payload = {}
                for sym, pos in open_positions.items():
                    bar = price_data.get(sym, {}).get(date_str)
                    if bar is None:
                        continue
                    close_px = bar["close"]
                    pos.peak_price = max(pos.peak_price, close_px)
                    current_positions_payload[sym] = {
                        "qty": pos.qty,
                        "avg_entry_price": pos.entry_price,
                        "current_price": close_px,
                        "peak_price": pos.peak_price,
                        "created_at": pos.entry_date.isoformat(),
                        "entry_signal_strength": pos.entry_signal_strength,
                    }

                if current_positions_payload:
                    exit_signals = exit_strategy.generate(
                        features=list(momentum_results),
                        current_positions=current_positions_payload,
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
                            "symbol": sym,
                            "signal_date": pos.signal_date,
                            "entry_date": pos.entry_date.date().isoformat(),
                            "entry_price": pos.entry_price,
                            "exit_date": date_str,
                            "exit_price": exit_price,
                            "qty": pos.qty,
                            "pnl": pnl,
                            "return_pct": return_pct,
                            "holding_days": hold_days,
                            "exit_reason": sig.metadata.get("exit_trigger", "unknown"),
                            "entry_signal_strength": pos.entry_signal_strength,
                        })
                        del open_positions[sym]

            # --- 2. Generate entry candidate signals from TODAY's data; ---
            # --- fill happens tomorrow at tomorrow's open (see step 0). ---
            candidate_records = []
            for sym, recs in features_by_symbol.items():
                if sym not in open_positions and sym not in pending_entries:
                    candidate_records.extend(recs)
            if candidate_records:
                candidate_momentum = momentum_feat.compute(candidate_records)
                buy_signals = entry_strategy.generate(candidate_momentum)
                for sig in buy_signals:
                    sym = sig.symbol
                    if sym in open_positions or sym in pending_entries:
                        continue
                    pending_entries[sym] = {
                        "signal_strength": sig.signal_strength,
                        "signal_date": date_str,
                    }
        finally:
            _unfreeze()

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(all_dates)} days simulated, "
                  f"{len(closed_trades)} closed, {len(open_positions)} open, "
                  f"{len(pending_entries)} pending fill")

    # Drop any signals still pending at the end of history (no next-day bar
    # to fill against) and force-close remaining open positions.
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
            "symbol": sym,
            "signal_date": pos.signal_date,
            "entry_date": pos.entry_date.date().isoformat(),
            "exit_date": final_date,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "qty": pos.qty,
            "pnl": pnl,
            "return_pct": return_pct,
            "holding_days": hold_days,
            "exit_reason": "backtest_end_forced_close",
            "entry_signal_strength": pos.entry_signal_strength,
        })

    return {
        "trades": closed_trades,
        "date_range": [all_dates[0], all_dates[-1]],
        "symbols": symbols,
        "notional_per_trade": notional,
        "min_momentum": min_momentum,
        "min_signal_strength": min_signal_strength,
        "point_in_time_universe": enforce_point_in_time_universe,
        "dropped_pending_at_end": len(pending_entries),
    }


def print_comparison(v1_trades: list[dict], v2_trades: list[dict]) -> None:
    print("\n" + "=" * 90)
    print("R13-C: v1 (look-ahead + survivorship bias) vs v2 (t+1 fill + point-in-time universe)")
    print("=" * 90)
    s1 = summarize(v1_trades, "v1")
    s2 = summarize(v2_trades, "v2")
    print(f"\n  v1: n={s1['n']:4d}  WR={s1.get('win_rate')}  PF={s1.get('profit_factor')}  "
          f"net=${s1.get('net_pnl')}  avg_return={s1.get('avg_return_pct')}")
    print(f"  v2: n={s2['n']:4d}  WR={s2.get('win_rate')}  PF={s2.get('profit_factor')}  "
          f"net=${s2.get('net_pnl')}  avg_return={s2.get('avg_return_pct')}")

    if v1_trades:
        d1 = sorted(t["entry_date"] for t in v1_trades)
        mid1 = d1[len(d1) // 2]
        p1a = [t for t in v1_trades if t["entry_date"] < mid1]
        p1b = [t for t in v1_trades if t["entry_date"] >= mid1]
        sa = summarize(p1a, "v1_period1")
        sb = summarize(p1b, "v1_period2")
        print(f"\n  v1 walk-forward split at {mid1}:")
        print(f"    period1: n={sa['n']:4d} PF={sa.get('profit_factor')} net=${sa.get('net_pnl')}")
        print(f"    period2: n={sb['n']:4d} PF={sb.get('profit_factor')} net=${sb.get('net_pnl')}")
    if v2_trades:
        d2 = sorted(t["entry_date"] for t in v2_trades)
        mid2 = d2[len(d2) // 2]
        p2a = [t for t in v2_trades if t["entry_date"] < mid2]
        p2b = [t for t in v2_trades if t["entry_date"] >= mid2]
        sa2 = summarize(p2a, "v2_period1")
        sb2 = summarize(p2b, "v2_period2")
        print(f"\n  v2 walk-forward split at {mid2}:")
        print(f"    period1: n={sa2['n']:4d} PF={sa2.get('profit_factor')} net=${sa2.get('net_pnl')}")
        print(f"    period2: n={sb2['n']:4d} PF={sb2.get('profit_factor')} net=${sb2.get('net_pnl')}")

    print("\n" + "-" * 90)
    print("Symbols traded in v1 but excluded from v2 in their pre-intro-date window")
    print("(this is the survivorship-bias correction in action)")
    print("-" * 90)
    intro_dates = load_universe_intro_dates()
    v1_pre_intro = [
        t for t in v1_trades
        if t["entry_date"] < intro_dates.get(t["symbol"], "1970-01-01")
    ]
    print(f"  v1 trades that occurred BEFORE the symbol's actual universe intro date: {len(v1_pre_intro)}")
    if v1_pre_intro:
        pnl_sum = sum(t["pnl"] for t in v1_pre_intro)
        print(f"    Their combined PnL in v1: ${pnl_sum:,.2f}  (n={len(v1_pre_intro)})")
        by_symbol: dict[str, float] = {}
        for t in v1_pre_intro:
            by_symbol[t["symbol"]] = by_symbol.get(t["symbol"], 0.0) + t["pnl"]
        for sym, pnl in sorted(by_symbol.items(), key=lambda x: -abs(x[1]))[:10]:
            print(f"      {sym:8s} intro={intro_dates.get(sym)}  pnl=${pnl:+,.2f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None, help="Comma-separated; default = all cached")
    parser.add_argument("--notional", type=float, default=10000.0)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--no-point-in-time-universe", action="store_true",
                         help="Disable universe gating (isolates the t+1-fill effect alone)")
    parser.add_argument("--compare-v1", action="store_true",
                         help="Also run the original v1 engine for a side-by-side diff")
    args = parser.parse_args()

    if args.symbols:
        symbols = args.symbols.split(",")
    else:
        symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_"))

    result = run_backtest_v2(
        symbols,
        notional=args.notional,
        enforce_point_in_time_universe=not args.no_point_in_time_universe,
    )
    trades = result["trades"]
    print(f"\nTotal v2 trades: {len(trades)} (dropped_pending_at_end={result['dropped_pending_at_end']})")

    overall = summarize(trades, "overall")
    print(f"\nOverall (v2): n={overall['n']} WR={overall.get('win_rate')} "
          f"PF={overall.get('profit_factor')} net=${overall.get('net_pnl')}")

    if trades:
        dates_sorted = sorted(t["entry_date"] for t in trades)
        mid = dates_sorted[len(dates_sorted) // 2]
        period1 = [t for t in trades if t["entry_date"] < mid]
        period2 = [t for t in trades if t["entry_date"] >= mid]
        s1 = summarize(period1, f"period1 (< {mid})")
        s2 = summarize(period2, f"period2 (>= {mid})")
        print(f"\nWalk-forward split at {mid}:")
        print(f"  {s1}")
        print(f"  {s2}")

        deciles = decile_summary(trades)
        print("\nDecile breakdown (by entry_signal_strength):")
        for row in deciles:
            print(f"  {row}")
    else:
        s1 = s2 = {}
        deciles = []

    v1_trades = None
    if args.compare_v1:
        from r11_backtest_engine import run_backtest as run_backtest_v1
        v1_result = run_backtest_v1(symbols, notional=args.notional)
        v1_trades = v1_result["trades"]
        print_comparison(v1_trades, trades)

    if args.save:
        out_path = PROJECT_ROOT / "reports" / "r11_backtest_v2_results.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "config": {
                    "symbols": symbols,
                    "notional_per_trade": args.notional,
                    "date_range": result["date_range"],
                    "point_in_time_universe": result["point_in_time_universe"],
                },
                "overall": overall,
                "period1": s1,
                "period2": s2,
                "decile_summary": deciles,
                "trades": trades,
                **({"v1_overall": summarize(v1_trades, "v1_overall")} if v1_trades is not None else {}),
            }, f, indent=2, ensure_ascii=False)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
