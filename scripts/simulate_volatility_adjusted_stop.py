"""2026-08-14: Historical simulation of volatility_adjusted_stop_enabled.

Answers: "if the ATR-based volatility adjustment (SimpleExitV2Strategy.
compute_volatility_multiplier()) had been active for every historical
stop_loss trade, would it have changed the outcome, and was that change
net-positive?"

This does NOT require enabling volatility_adjusted_stop_enabled in paper
trading. It reconstructs, for each historical stop_loss trade:
  1. The symbol's ATR% at entry time (same "simple ATR from available OHLC
     bars" approximation used by PriceMomentumFeature -- true range averaged
     over a trailing window of daily bars, divided by the latest close).
  2. The cross-sectional universe average ATR% across all symbols that had
     an open position on that trade's entry date (approximating the
     per-run universe average used in the live code path).
  3. The resulting volatility_multiplier and adjusted stop threshold.
  4. Whether the adjusted threshold would have fired earlier, later, or
     not at all vs. the trade's actual eff_stop_loss_pct, and the
     counterfactual PnL impact of that difference (reusing
     analyze_stop_loss_post_exit.py's counterfactual machinery: "what if we
     had held until the adjusted threshold fired instead of the actual one").

Approximation caveats (documented, not hidden):
  - Real eff_stop_loss_pct (conviction-tier-adjusted, e.g. -5/-7/-9%) is not
    reliably recoverable from historical trade records for older trades
    (entry_signal_strength is only populated for ~34/73 stop_loss trades).
    We use the strategy's *base* stop_loss_pct (-7%, config default) as the
    "actual" threshold for trades missing entry_signal_strength, which is a
    reasonable approximation since -7% is also the graduated/standard tier
    the majority of positions land on.
  - "Universe" ATR average is computed from the same-day open positions in
    pnl_state.json, which is the best available proxy for "all symbols
    considered in that day's run" without re-running the full historical
    pipeline.
  - Bar-level ATR here uses yfinance daily OHLC (14-bar trailing window,
    matching PriceMomentumFeature's default bar_limit=20 approximately) as
    of the entry date, not the exact intraday snapshot the live system saw.

Usage:
    python scripts/simulate_volatility_adjusted_stop.py [--multiplier-min 0.5]
        [--multiplier-max 1.75] [--atr-window 14]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yfinance as yf

from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy

sys.path.insert(0, str(ROOT / "scripts"))
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("analyze_stop_loss_post_exit", ROOT / "scripts" / "analyze_stop_loss_post_exit.py")
_post_exit_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_post_exit_mod)

BASE_STOP_LOSS_PCT = -0.07  # config/strategy/simple_exit_v2.yaml default


def load_all_stop_loss_trades() -> list[dict]:
    state_path = ROOT / "data" / "tracking" / "pnl_state.json"
    with open(state_path) as f:
        state = json.load(f)
    trades = state.get("trades", [])
    return [
        t for t in trades
        if t.get("status") == "closed" and t.get("exit_reason") == "stop_loss" and t.get("pnl", 0) < 0
    ]


def compute_atr_pct_asof(symbol: str, asof_date: str, window: int = 14) -> float | None:
    """Return ATR% (true-range average / latest close) for symbol as of
    asof_date, using a trailing window of daily bars -- same approximation
    style as PriceMomentumFeature. Returns None on any data issue.
    """
    try:
        end = datetime.fromisoformat(asof_date).date() + timedelta(days=1)
        start = end - timedelta(days=window * 3)  # buffer for weekends/holidays
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start.isoformat(), end=end.isoformat(), interval="1d")
        if hist.empty or len(hist) < 2:
            return None
        hist = hist.tail(window + 1)  # +1 so we have `window` true-range computations
        closes = hist["Close"].tolist()
        highs = hist["High"].tolist()
        lows = hist["Low"].tolist()
        if not closes:
            return None
        latest_close = closes[-1]
        if latest_close <= 0:
            return None

        true_ranges = []
        prev_close = None
        for h, l, c in zip(highs, lows, closes):
            if prev_close is None:
                tr = h - l
            else:
                tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
            true_ranges.append(tr)
            prev_close = c
        if not true_ranges:
            return None
        atr = sum(true_ranges) / len(true_ranges)
        return atr / latest_close
    except Exception as e:
        print(f"    [WARN] ATR fetch failed for {symbol}@{asof_date}: {e}", file=sys.stderr)
        return None


def group_trades_by_entry_date(trades: list[dict]) -> dict[str, list[dict]]:
    by_date: dict[str, list[dict]] = {}
    for t in trades:
        entry_date = (t.get("entry_time") or "")[:10]
        if entry_date:
            by_date.setdefault(entry_date, []).append(t)
    return by_date


def simulate(
    trades: list[dict],
    multiplier_min: float = 0.5,
    multiplier_max: float = 1.75,
    atr_window: int = 14,
    lookforward_days: int = 60,
) -> list[dict]:
    by_date = group_trades_by_entry_date(trades)
    results = []

    # Cache ATR% per (symbol, date) to avoid duplicate fetches within a date group.
    atr_cache: dict[tuple[str, str], float | None] = {}

    for entry_date, day_trades in by_date.items():
        # Universe ATR% for this date: ATR% of every symbol that had a stop_loss
        # trade entered on this date (approximates that day's active universe;
        # a broader universe would require re-running collect_data historically,
        # which is out of scope for this validation pass).
        day_atr_pcts: dict[str, float] = {}
        for t in day_trades:
            sym = t["symbol"]
            key = (sym, entry_date)
            if key not in atr_cache:
                atr_cache[key] = compute_atr_pct_asof(sym, entry_date, window=atr_window)
            if atr_cache[key] is not None:
                day_atr_pcts[sym] = atr_cache[key]

        universe_avg = (sum(day_atr_pcts.values()) / len(day_atr_pcts)) if day_atr_pcts else None

        for t in day_trades:
            sym = t["symbol"]
            symbol_atr_pct = day_atr_pcts.get(sym)
            multiplier = SimpleExitV2Strategy.compute_volatility_multiplier(
                symbol_atr_pct=symbol_atr_pct,
                universe_avg_atr_pct=universe_avg,
                min_multiplier=multiplier_min,
                max_multiplier=multiplier_max,
            )

            # Determine "actual" effective stop threshold used historically.
            strength = t.get("entry_signal_strength")
            if strength is not None:
                if strength >= SimpleExitV2Strategy.HIGH_STRENGTH_THRESHOLD:
                    actual_stop = -0.09
                elif strength < SimpleExitV2Strategy.LOW_STRENGTH_THRESHOLD:
                    actual_stop = -0.05
                else:
                    actual_stop = BASE_STOP_LOSS_PCT
            else:
                actual_stop = BASE_STOP_LOSS_PCT  # graduated/standard approximation

            adjusted_stop = actual_stop * multiplier
            actual_ret_pct = t.get("return_pct") or 0.0

            # Would the adjusted threshold have fired at all, given the
            # trade's actual realized return_pct at exit? (Approximation:
            # we don't have full daily path here, just entry/exit; "would
            # have fired" means actual_ret_pct <= adjusted_stop, i.e. the
            # exit point still breaches the new threshold.)
            would_still_fire = actual_ret_pct <= adjusted_stop

            results.append({
                "symbol": sym,
                "entry_date": entry_date,
                "exit_date": (t.get("exit_time") or "")[:10],
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "actual_pnl": t.get("pnl"),
                "qty": t.get("qty"),
                "actual_ret_pct": actual_ret_pct,
                "symbol_atr_pct": symbol_atr_pct,
                "universe_avg_atr_pct": universe_avg,
                "volatility_multiplier": round(multiplier, 3),
                "actual_stop_pct": actual_stop,
                "adjusted_stop_pct": round(adjusted_stop, 4),
                "would_still_fire_at_actual_exit": would_still_fire,
                "widened": multiplier > 1.0,
                "tightened": multiplier < 1.0,
            })

    return results


def print_report(results: list[dict]) -> None:
    print("=" * 78)
    print("Volatility-Adjusted Stop Loss — Historical Simulation")
    print("=" * 78)
    print()
    print(f"Total stop_loss trades analyzed: {len(results)}")

    no_atr = [r for r in results if r["symbol_atr_pct"] is None]
    with_atr = [r for r in results if r["symbol_atr_pct"] is not None]
    print(f"  With ATR data:    {len(with_atr)}")
    print(f"  Missing ATR data: {len(no_atr)} (neutral multiplier=1.0, no change)")
    print()

    widened = [r for r in with_atr if r["widened"]]
    tightened = [r for r in with_atr if r["tightened"]]
    neutral = [r for r in with_atr if not r["widened"] and not r["tightened"]]
    print(f"  Widened threshold (higher-vol symbol):   {len(widened)}")
    print(f"  Tightened threshold (lower-vol symbol):  {len(tightened)}")
    print(f"  Neutral (~universe average):             {len(neutral)}")
    print()

    # Widened trades that would NOT have fired at the actual exit point
    # (i.e. the widened stop suppressed this exit -- position would have kept running)
    suppressed = [r for r in widened if not r["would_still_fire_at_actual_exit"]]
    print("─" * 78)
    print(f"Widened-threshold trades that would NOT have fired (n={len(suppressed)}/{len(widened)})")
    print("─" * 78)
    print("  These positions would have kept running past the actual exit point.")
    print("  (Full counterfactual PnL for these requires post-exit price data --")
    print("   see the --with-counterfactual flag for a live-fetched follow-up.)")
    for r in sorted(suppressed, key=lambda x: x["actual_pnl"])[:10]:
        print(
            f"    {r['symbol']:8s} {r['entry_date']}  "
            f"atr%={r['symbol_atr_pct']*100:.1f} vs universe={r['universe_avg_atr_pct']*100:.1f}  "
            f"mult={r['volatility_multiplier']:.2f}  "
            f"actual_stop={r['actual_stop_pct']*100:.1f}%->adj={r['adjusted_stop_pct']*100:.1f}%  "
            f"actual_ret={r['actual_ret_pct']*100:.1f}%  actual_pnl=${r['actual_pnl']:+.2f}"
        )
    print()

    # Tightened trades that WOULD have fired earlier (before actual exit point)
    tightened_earlier = [r for r in tightened if r["would_still_fire_at_actual_exit"]]
    print("─" * 78)
    print(f"Tightened-threshold trades (n={len(tightened)}) — would fire at a smaller loss")
    print("─" * 78)
    for r in sorted(tightened, key=lambda x: x["volatility_multiplier"])[:10]:
        print(
            f"    {r['symbol']:8s} {r['entry_date']}  "
            f"atr%={r['symbol_atr_pct']*100:.1f} vs universe={r['universe_avg_atr_pct']*100:.1f}  "
            f"mult={r['volatility_multiplier']:.2f}  "
            f"actual_stop={r['actual_stop_pct']*100:.1f}%->adj={r['adjusted_stop_pct']*100:.1f}%  "
            f"actual_ret={r['actual_ret_pct']*100:.1f}%  actual_pnl=${r['actual_pnl']:+.2f}"
        )
    print()

    print("─" * 78)
    print("Summary")
    print("─" * 78)
    print(f"  {len(suppressed)} trade(s) would have been suppressed (widened threshold, symbol runs hotter than universe avg)")
    print(f"  {len(tightened)} trade(s) would fire at a tighter/earlier threshold (lower-vol symbols)")
    print(f"  Run with --with-counterfactual to fetch post-exit prices and quantify PnL impact of the {len(suppressed)} suppressed trades")


def print_counterfactual_for_suppressed(results: list[dict], lookforward_days: int = 60) -> None:
    """For trades that the widened threshold would have suppressed, fetch
    post-exit prices (reusing analyze_stop_loss_post_exit.py's fetcher) and
    compute what the actual PnL would have been if held until the adjusted
    threshold (or lookforward_days, whichever is sooner) instead of exiting
    at the historical exit point.
    """
    suppressed = [r for r in results if r["widened"] and not r["would_still_fire_at_actual_exit"]]
    if not suppressed:
        print("No suppressed trades to analyze.")
        return

    print("=" * 78)
    print(f"Counterfactual PnL for {len(suppressed)} suppressed trade(s) "
          f"(held {lookforward_days}d instead of stopping at actual exit)")
    print("=" * 78)

    total_actual = 0.0
    total_cf = 0.0
    rows = []
    for r in suppressed:
        exit_time_guess = r["exit_date"] + "T20:00:00Z"
        prices = _post_exit_mod.fetch_post_exit_prices(r["symbol"], exit_time_guess, days=lookforward_days + 5)
        if not prices:
            continue
        sorted_dates = sorted(prices.keys())[:lookforward_days]
        if not sorted_dates:
            continue
        last_price = prices[sorted_dates[-1]]
        qty = r["qty"] or 0
        cf_pnl = qty * (last_price - r["entry_price"]) if qty else None
        if cf_pnl is None:
            continue
        diff = r["actual_pnl"] - cf_pnl
        total_actual += r["actual_pnl"]
        total_cf += cf_pnl
        rows.append((r["symbol"], r["entry_date"], r["actual_pnl"], cf_pnl, diff))

    if not rows:
        print("  (no post-exit price data available for suppressed trades)")
        return

    print(f"\n  Actual PnL (n={len(rows)}):        ${total_actual:,.2f}")
    print(f"  Counterfactual PnL (widened, held): ${total_cf:,.2f}")
    print(f"  Net diff (actual - counterfactual): ${total_actual - total_cf:+,.2f}")
    print(f"    (negative = widened threshold would have been BETTER; positive = WORSE)\n")
    for sym, entry_date, actual, cf, diff in sorted(rows, key=lambda x: x[4]):
        print(f"    {sym:8s} {entry_date}  actual=${actual:+9.2f}  counterfactual=${cf:+9.2f}  diff=${diff:+9.2f}")


def print_tightened_side_analysis(results: list[dict]) -> None:
    """For trades whose threshold would have been tightened, estimate the
    counterfactual PnL under a simplifying monotonic-decline assumption:
    the position would have stopped out exactly at adjusted_stop_pct
    (a smaller-magnitude loss than what actually fired), rather than
    continuing to the deeper actual_ret_pct.

    IMPORTANT CAVEAT (must be read alongside the numbers): this only
    analyzes trades that ALREADY fired stop_loss at the original threshold.
    It does NOT examine the (much larger) universe of trades that never
    breached the original threshold at all -- some of those might breach a
    *tightened* synthetic threshold and become NEW false stops on positions
    that would otherwise have recovered or been winners. This one-sided
    view will structurally look positive (tightening a stop that already
    fired can only reduce the realized loss on that specific trade), but it
    cannot by itself prove that tightening improves aggregate outcomes --
    that requires re-running the full historical decision pipeline against
    ALL positions (open and closed), not just the ones that already
    triggered a stop. Treat this as a directional/exploratory data point,
    not a conclusive verdict.
    """
    tightened = [r for r in results if r["tightened"]]
    if not tightened:
        print("No tightened-threshold trades to analyze.")
        return

    print("=" * 78)
    print(f"Tightened-side analysis (n={len(tightened)}) — monotonic-decline approximation")
    print("=" * 78)
    print(
        "CAVEAT: one-sided view (only trades that already fired the original\n"
        "stop). Does not check whether tightening creates NEW false stops on\n"
        "positions that never breached the original threshold. Directional\n"
        "data point only -- see docstring in print_tightened_side_analysis().\n"
    )

    total_actual = 0.0
    total_cf = 0.0
    rows = []
    for r in tightened:
        qty = r["qty"] or 0
        if not qty:
            continue
        cf_pnl = qty * r["entry_price"] * r["adjusted_stop_pct"]
        actual = r["actual_pnl"]
        diff = actual - cf_pnl
        total_actual += actual
        total_cf += cf_pnl
        rows.append((r["symbol"], r["entry_date"], actual, cf_pnl, diff))

    print(f"  Actual PnL (n={len(rows)}):                    ${total_actual:,.2f}")
    print(f"  Counterfactual PnL (tightened, monotonic approx): ${total_cf:,.2f}")
    print(f"  Net diff (actual - counterfactual):            ${total_actual - total_cf:+,.2f}")
    print(f"    (negative = tightened threshold would have been BETTER; positive = WORSE)\n")
    for sym, entry_date, actual, cf, diff in sorted(rows, key=lambda x: x[4])[:15]:
        print(f"    {sym:8s} {entry_date}  actual=${actual:+9.2f}  tightened_approx=${cf:+9.2f}  diff=${diff:+9.2f}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Historical simulation of volatility_adjusted_stop_enabled")
    parser.add_argument("--multiplier-min", type=float, default=0.5)
    parser.add_argument("--multiplier-max", type=float, default=1.75)
    parser.add_argument("--atr-window", type=int, default=14)
    parser.add_argument("--with-counterfactual", action="store_true",
                         help="Fetch post-exit prices for suppressed trades and quantify PnL impact")
    parser.add_argument("--lookforward-days", type=int, default=60)
    args = parser.parse_args()

    trades = load_all_stop_loss_trades()
    print(f"Loaded {len(trades)} historical stop_loss trades. Fetching ATR data...\n")

    results = simulate(
        trades,
        multiplier_min=args.multiplier_min,
        multiplier_max=args.multiplier_max,
        atr_window=args.atr_window,
    )
    print_report(results)

    if args.with_counterfactual:
        print()
        print_counterfactual_for_suppressed(results, lookforward_days=args.lookforward_days)
        print()
        print_tightened_side_analysis(results)
