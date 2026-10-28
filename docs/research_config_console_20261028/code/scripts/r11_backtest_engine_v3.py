#!/usr/bin/env python3
"""R13-C (2026-08-23): R11 backtest engine v3 -- adds roadmap items 3
(conservative OHLC-path exit re-simulation) and 5 (slippage) on top of v2's
t+1-fill + point-in-time-universe fixes.

WHY THESE TWO MATTER TOGETHER: v2's headline result (PF=2.069 overall,
PF=1.448 restricted to the actual live-trading window) was explicitly
flagged as likely optimistic because (a) exit decisions still only looked
at each day's CLOSE price, and (b) fills were assumed frictionless (no
spread/slippage). Both biases point the SAME direction -- toward
overstating profitability -- so this v3 measures how much of v2's PF
survives once both are corrected.

(3) Conservative OHLC-path exits: v1/v2 both tracked peak_price using only
the day's CLOSE and checked stop_loss/trailing_stop/breakeven against the
day's CLOSE return_pct. This is optimistic in two ways simultaneously:
  - A day where the LOW dipped through a stop/trailing threshold but the
    CLOSE recovered above it would incorrectly show as "still held" in
    v1/v2, when a real stop-order (or an intraday paper_demo cron check
    that happened to run near the day's low) would have exited that day.
  - Peak tracking off CLOSE misses higher intraday HIGHs, understating how
    far a position ran before pulling back, which (for staged
    trailing/breakeven, where the floor ratchets up with peak_return_pct)
    understates how tight the effective trailing/breakeven floor should
    already be.
v3 fixes both: peak_price is updated from the day's HIGH (not close), and
stop_loss/trailing_stop/breakeven downside breaches are checked against the
day's LOW; if breached, the exit fills AT THE THRESHOLD PRICE (not the low
itself, modeling a stop order triggering at its trigger price) rather than
waiting for a close-based check. Time-based exits are unaffected (they are
a hold-duration count, not a price level) and still use the close for their
reported exit price.

NOTE ON REALISM: this does not claim to reproduce paper_demo.py's actual
execution timing (which checks prices at ~4 scheduled cron windows/day
using whatever price resolves at that moment -- not a continuous intraday
stop order, and not literally "the day's low"). Given only daily OHLC bars
are cached (no intraday history), using the day's low/high range is the
standard, well-understood way to bound the WORST CASE within a day without
requiring intraday granularity data -- it is deliberately conservative
(biased toward MORE and EARLIER exits, i.e. worse performance), not a
precise replica of the live execution schedule.

(5) Slippage: v1/v2 assumed frictionless fills at the exact computed
price (t+1 open for entries, threshold/close price for exits). Since all
observed production orders are MARKET orders (ProposedOrder.order_type ==
"market" -- see decision_engine.py), a real fill would cross the bid-ask
spread and may move the market slightly (impact). This is modeled as a
single one-way slippage_bps parameter applied unfavorably on BOTH legs:
entry fills at price*(1+slippage_bps/10000) (pay more to buy), exit fills
at price*(1-slippage_bps/10000) (receive less to sell). This matches the
existing cost-sensitivity convention already used in docs/
console_improvement_tasks.md's 2026-08-15 R11 analysis (0/10/20/30bp
ROUND-TRIP) when slippage_bps is set to half the round-trip figure (e.g.
round_trip=20bp -> slippage_bps=10 applied on each leg).

Everything else (BreakoutMomentumStrategy entry-signal generation off
daily closes, one open position per symbol, fixed notional per trade,
point-in-time universe gate, t+1-open entry fill) is unchanged from v2 --
see r11_backtest_engine_v2.py's module docstring for that rationale.

Still NOT in scope (roadmap items 4, 6, 7): cash/gross exposure/sector cap
enforcement, rolling walk-forward + embargo, full parameter-trial registry.

Usage:
    python scripts/r11_backtest_engine_v3.py [--slippage-bps 10] [--save]
    python scripts/r11_backtest_engine_v3.py --compare-v2   # side-by-side vs v2 (no slippage, close-only exits)
    python scripts/r11_backtest_engine_v3.py --isolate       # also runs slippage-only and
                                                               # conservative-exit-only variants
                                                               # to attribute the effect of each
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
from stock_swing.strategy_engine.simple_exit_v2_strategy import (  # noqa: E402
    SimpleExitV2Strategy,
)

from r11_backtest_engine import (  # noqa: E402
    _freeze,
    _unfreeze,
    decile_summary,
    load_exit_strategy,
    load_price_data,
    make_record,
    summarize,
)
from r11_backtest_engine_v2 import load_universe_intro_dates  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
BAR_LIMIT = 20


class Position:
    __slots__ = (
        "symbol", "entry_date", "entry_price", "qty", "peak_price",
        "entry_signal_strength", "signal_date",
    )

    def __init__(self, symbol, entry_date, entry_price, qty, entry_signal_strength, signal_date):
        self.symbol = symbol
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.qty = qty
        self.peak_price = entry_price
        self.entry_signal_strength = entry_signal_strength
        self.signal_date = signal_date


def _check_conservative_exit_for_day(
    strat: SimpleExitV2Strategy,
    pos: Position,
    bar: dict[str, float],
    hold_days: int,
    volatility_multiplier: float,
    conservative_ohlc: bool,
) -> dict[str, Any] | None:
    """Check one day's exit conditions for an open position.

    When conservative_ohlc=True: peak tracked via day's HIGH; stop_loss/
    trailing_stop/breakeven downside breaches checked against day's LOW and
    fill AT THE THRESHOLD PRICE if breached. Priority order matches
    SimpleExitV2Strategy's real precedence: trailing_stop -> breakeven_stop
    -> stop_loss -> time_based (see simulate_stop_loss_deepening.py /
    simulate_signal_strength_exit_decoupling.py, same priority ordering
    reused here for consistency across R13-A/B/C).

    When conservative_ohlc=False: behaves like v1/v2 -- everything keyed off
    the day's close only. This flag exists so v3 can reproduce v2's
    close-only exit behavior exactly for isolated A/B comparison.

    Returns an exit dict {exit_price, exit_reason} or None if the position
    should remain open past this day.
    """
    close = bar["close"]
    high = bar["high"] if conservative_ohlc else close
    low = bar["low"] if conservative_ohlc else close

    # Peak tracking: HIGH-based when conservative, close-based otherwise.
    if high > pos.peak_price:
        pos.peak_price = high

    eff_stop_loss_pct, eff_trailing_activation_pct = strat._resolve_thresholds(
        pos.entry_signal_strength, hold_days=hold_days,
        volatility_multiplier=volatility_multiplier,
    )
    peak_return_pct = (pos.peak_price - pos.entry_price) / pos.entry_price

    # --- 1. Trailing stop (highest priority) ---
    trailing_active, _, active_trailing_stop_pct, _ = strat._resolve_trailing_rule(
        peak_return_pct, eff_trailing_activation_pct
    )
    if trailing_active:
        trailing_stop_price = pos.peak_price * (1 - active_trailing_stop_pct)
        if low <= trailing_stop_price:
            # Conservative: fill at the trigger price, not the (worse) low,
            # modeling a stop order executing at its trigger level.
            fill_price = trailing_stop_price if conservative_ohlc else close
            return {"exit_price": fill_price, "exit_reason": "trailing_stop"}

    # --- 2. Breakeven stop ---
    be_activated, be_floor_pct, _ = strat._resolve_breakeven_floor(
        peak_return_pct, strat.breakeven_activation_pct
    )
    if be_activated:
        be_floor_price = pos.entry_price * (1 + be_floor_pct)
        if low <= be_floor_price:
            fill_price = be_floor_price if conservative_ohlc else close
            return {"exit_price": fill_price, "exit_reason": "breakeven_stop"}
        # When breakeven is active but not breached, v1/v2 semantics
        # short-circuit here (stop_loss is not re-checked the same day) --
        # preserved for behavioral parity.
        return None

    # --- 3. Stop loss ---
    stop_loss_price = pos.entry_price * (1 + eff_stop_loss_pct)
    if low <= stop_loss_price:
        return_pct_at_close = (close - pos.entry_price) / pos.entry_price
        eff_min_hold = strat._effective_min_hold_days(return_pct_at_close, eff_stop_loss_pct=eff_stop_loss_pct)
        if (
            strat.min_hold_days_enabled
            and hold_days < eff_min_hold
            and return_pct_at_close > strat.emergency_stop_bypass_pct
        ):
            pass  # min-hold override: stay in position despite the breach
        else:
            fill_price = stop_loss_price if conservative_ohlc else close
            return {"exit_price": fill_price, "exit_reason": "stop_loss"}

    # --- 4. Time-based (hold-duration only, always close-priced) ---
    if hold_days >= strat.max_hold_days:
        return {"exit_price": close, "exit_reason": "time_based"}

    return None


def run_backtest_v3(
    symbols: list[str],
    notional: float,
    min_momentum: float = 0.05,
    min_signal_strength: float = 0.40,
    enforce_point_in_time_universe: bool = True,
    conservative_ohlc: bool = True,
    slippage_bps: float = 0.0,
) -> dict[str, Any]:
    price_data = load_price_data(symbols)
    if not price_data:
        raise RuntimeError(f"No cached price data found in {CACHE_DIR}; run r11_fetch_historical_data.py first")

    intro_dates = load_universe_intro_dates() if enforce_point_in_time_universe else {}
    slippage_factor = slippage_bps / 10_000.0

    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(
        f"Simulating {len(symbols)} symbols over {len(all_dates)} trading days "
        f"({all_dates[0]} -> {all_dates[-1]}); point_in_time_universe="
        f"{enforce_point_in_time_universe}; conservative_ohlc={conservative_ohlc}; "
        f"slippage_bps={slippage_bps} (one-way)"
    )

    entry_strategy = BreakoutMomentumStrategy(
        min_momentum=min_momentum, min_signal_strength=min_signal_strength
    )
    exit_strategy = load_exit_strategy()

    open_positions: dict[str, Position] = {}
    closed_trades: list[dict[str, Any]] = []
    pending_entries: dict[str, dict[str, Any]] = {}

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        _freeze(current_dt)
        try:
            # --- 0. Fill pending entries at today's open (+ slippage) ---
            for sym, pending in list(pending_entries.items()):
                if sym in open_positions:
                    del pending_entries[sym]
                    continue
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None or bar.get("open", 0) <= 0:
                    del pending_entries[sym]
                    continue
                raw_entry_price = bar["open"]
                entry_price = raw_entry_price * (1 + slippage_factor)  # pay more to buy
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

            # --- 1. Check exits for open positions (conservative OHLC path) ---
            for sym, pos in list(open_positions.items()):
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None:
                    continue
                hold_days = (current_dt - pos.entry_date).days
                atr_pct = None  # volatility_adjusted_stop disabled in this
                # simplified per-symbol loop (v1/v2 also computed it from a
                # cross-sectional universe average; the production config's
                # volatility_adjusted_stop_enabled flag is preserved via
                # load_exit_strategy(), but the per-day, per-symbol ATR
                # cross-section used in v1/v2's generate() call is not
                # reconstructed step-by-step here since exits are now
                # evaluated per-position directly against OHLC, not via a
                # batched feature-based generate() call. volatility_multiplier
                # defaults to 1.0 (no adjustment) -- documented limitation,
                # consistent with this v3's stated scope (items 3+5 only).
                exit_result = _check_conservative_exit_for_day(
                    exit_strategy, pos, bar, hold_days,
                    volatility_multiplier=1.0,
                    conservative_ohlc=conservative_ohlc,
                )
                if exit_result is None:
                    continue
                raw_exit_price = exit_result["exit_price"]
                exit_price = raw_exit_price * (1 - slippage_factor)  # receive less to sell
                pnl = (exit_price - pos.entry_price) * pos.qty
                return_pct = (exit_price - pos.entry_price) / pos.entry_price
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
                    "exit_reason": exit_result["exit_reason"],
                    "entry_signal_strength": pos.entry_signal_strength,
                })
                del open_positions[sym]

            # --- 2. Generate entry candidate signals from TODAY's close ---
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

    final_date = all_dates[-1]
    for sym, pos in open_positions.items():
        bar = price_data.get(sym, {}).get(final_date)
        if bar is None:
            continue
        raw_exit_price = bar["close"]
        exit_price = raw_exit_price * (1 - slippage_factor)
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
        "conservative_ohlc": conservative_ohlc,
        "slippage_bps": slippage_bps,
        "dropped_pending_at_end": len(pending_entries),
    }


def _live_window_summary(trades: list[dict], label: str, cutoff: str = "2026-05-12") -> None:
    live = [t for t in trades if t["entry_date"] >= cutoff]
    if not live:
        print(f"  {label}: no trades in live window")
        return
    s = summarize(live, label)
    print(f"  {label} (entry_date >= {cutoff}): n={s['n']} WR={s.get('win_rate')} "
          f"PF={s.get('profit_factor')} net=${s.get('net_pnl')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None, help="Comma-separated; default = all cached")
    parser.add_argument("--notional", type=float, default=10000.0)
    parser.add_argument("--slippage-bps", type=float, default=10.0,
                         help="One-way slippage in bps applied unfavorably on both entry and exit "
                              "(default 10bp = 20bp round-trip, matching the existing cost-sensitivity "
                              "analysis's middle scenario)")
    parser.add_argument("--no-conservative-ohlc", action="store_true",
                         help="Disable OHLC-based exit checking (close-only, v2-equivalent exit behavior)")
    parser.add_argument("--no-point-in-time-universe", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--compare-v2", action="store_true",
                         help="Also run v2 (no slippage, close-only exits) for a side-by-side diff")
    parser.add_argument("--isolate", action="store_true",
                         help="Also run slippage-only and conservative-exit-only variants "
                              "to attribute each effect separately")
    args = parser.parse_args()

    if args.symbols:
        symbols = args.symbols.split(",")
    else:
        symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_"))

    result = run_backtest_v3(
        symbols,
        notional=args.notional,
        enforce_point_in_time_universe=not args.no_point_in_time_universe,
        conservative_ohlc=not args.no_conservative_ohlc,
        slippage_bps=args.slippage_bps,
    )
    trades = result["trades"]
    overall = summarize(trades, "v3_full")
    print(f"\nTotal v3 trades: {len(trades)} (dropped_pending_at_end={result['dropped_pending_at_end']})")
    print(f"Overall (v3, conservative_ohlc={result['conservative_ohlc']}, "
          f"slippage_bps={result['slippage_bps']}): n={overall['n']} "
          f"WR={overall.get('win_rate')} PF={overall.get('profit_factor')} net=${overall.get('net_pnl')}")
    _live_window_summary(trades, "v3_full live-window-only")

    deciles = decile_summary(trades)
    print("\nDecile breakdown (by entry_signal_strength):")
    for row in deciles:
        print(f"  {row}")

    variants: dict[str, list[dict]] = {"v3_full (conservative_ohlc + slippage)": trades}

    if args.isolate:
        print("\n" + "=" * 90)
        print("ISOLATION: attributing the effect of conservative_ohlc vs slippage separately")
        print("=" * 90)
        slippage_only = run_backtest_v3(
            symbols, notional=args.notional,
            enforce_point_in_time_universe=not args.no_point_in_time_universe,
            conservative_ohlc=False, slippage_bps=args.slippage_bps,
        )["trades"]
        conservative_only = run_backtest_v3(
            symbols, notional=args.notional,
            enforce_point_in_time_universe=not args.no_point_in_time_universe,
            conservative_ohlc=True, slippage_bps=0.0,
        )["trades"]
        variants["slippage_only (no conservative exit)"] = slippage_only
        variants["conservative_ohlc_only (no slippage)"] = conservative_only

    if args.compare_v2:
        from r11_backtest_engine_v2 import run_backtest_v2
        v2_trades = run_backtest_v2(
            symbols, notional=args.notional,
            enforce_point_in_time_universe=not args.no_point_in_time_universe,
        )["trades"]
        variants["v2 (no slippage, close-only exits)"] = v2_trades

    if len(variants) > 1:
        print("\n" + "=" * 90)
        print("VARIANT COMPARISON")
        print("=" * 90)
        for label, ts in variants.items():
            s = summarize(ts, label)
            print(f"\n  {label}:")
            print(f"    all:         n={s['n']:4d} WR={s.get('win_rate')} PF={s.get('profit_factor')} net=${s.get('net_pnl')}")
            _live_window_summary(ts, "    live-window")

    if args.save:
        out_path = PROJECT_ROOT / "reports" / "r11_backtest_v3_results.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "config": {
                    "symbols": symbols,
                    "notional_per_trade": args.notional,
                    "date_range": result["date_range"],
                    "point_in_time_universe": result["point_in_time_universe"],
                    "conservative_ohlc": result["conservative_ohlc"],
                    "slippage_bps": result["slippage_bps"],
                },
                "overall": overall,
                "decile_summary": deciles,
                "trades": trades,
            }, f, indent=2, ensure_ascii=False)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
