"""2026-08-14: Daily-path historical validation of volatility_adjusted_stop_enabled.

Addresses the two structural gaps in scripts/simulate_volatility_adjusted_stop.py
(the earlier, coarser simulation):

  1. Exit priority order was NOT respected there -- it evaluated stop_loss in
     isolation. In production, SimpleExitV2Strategy.generate() checks
     trailing_stop first, then breakeven_stop, then stop_loss, then
     time_based (max_hold_days). Widening the stop_loss threshold for a
     position could mean it actually gets exited by trailing_stop or
     time_based instead of "just holds to day 60" as the earlier sim assumed.

  2. Only the 60 trades that ALREADY fired stop_loss were analyzed. The
     "tightened threshold" direction is a one-sided view: it cannot detect
     whether a *tighter* stop would create NEW false-positive exits among
     the 168 OTHER closed trades (trailing_stop / breakeven_stop / time_based
     / winners) that never touched the original stop_loss threshold at all.

This script fixes both gaps by re-running SimpleExitV2Strategy's actual
priority-ordered exit logic day-by-day over real historical daily closes,
for ALL 228 closed trades (not just the 60 stop_loss ones), comparing:
  - baseline: volatility_multiplier=1.0 (today's production behavior)
  - adjusted: volatility_multiplier computed once per trade from ATR% at
    entry (approximation -- see caveats below)

Reuses SimpleExitV2Strategy's own methods (_resolve_trailing_rule,
_resolve_breakeven_floor, _effective_min_hold_days,
compute_volatility_multiplier) rather than reimplementing the logic, so the
simulation stays faithful to the actual production exit code.

Approximation caveats (documented, not hidden):
  - ATR% is computed ONCE per trade at entry_time (14-day trailing window)
    and held constant through the simulated holding period. In production,
    ATR is recomputed fresh on every paper_demo run (so it drifts slowly
    day to day), but re-fetching/recomputing ATR for every simulated day of
    every trade would multiply the yfinance call volume ~20x for a mostly
    slow-moving quantity; a single entry-time snapshot is a reasonable
    approximation for a directional validation pass.
  - universe_avg_atr_pct is approximated per trade using the ATR% of all
    OTHER trades that entered within +/-3 calendar days of this trade's
    entry (a proxy for "symbols considered in a similar time window"),
    rather than the exact same-run universe the live pipeline would have
    seen.
  - entry_signal_strength conviction tier is read directly from the trade
    record when available (accurate); when missing, falls back to the
    standard/base tier (-7% stop, +8% trailing), same approximation as the
    coarser simulation.
  - Daily bars only (no intraday). A position that would trigger and
    reverse intraday is not distinguishable at this resolution -- same
    limitation as the live system's own daily-bar-based feature pipeline
    for most of the day.

Usage:
    python scripts/simulate_daily_path_volatility_stop.py
        [--multiplier-min 0.5] [--multiplier-max 1.75] [--atr-window 14]
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

# ── Production config (config/strategy/simple_exit_v2.yaml, 2026-08-14) ────
PROD_CONFIG = dict(
    stop_loss_pct=-0.07,
    breakeven_activation_pct=0.05,
    trailing_activation_pct=0.08,
    trailing_stop_pct=0.04,
    staged_trailing_enabled=True,
    staged_trailing_levels=[
        {"activation_pct": 0.05, "trailing_stop_pct": 0.035},
        {"activation_pct": 0.08, "trailing_stop_pct": 0.03},
        {"activation_pct": 0.12, "trailing_stop_pct": 0.025},
    ],
    max_hold_days=20,
    broker_recon_graduation_days=5,
    min_hold_days_enabled=True,
    min_hold_days=1,
    emergency_stop_bypass_pct=-0.12,
    tiered_min_hold_enabled=True,
    tiered_min_hold_levels=[
        {"offset_pct": -2.0, "min_hold_days": 7},
        {"offset_pct": -5.0, "min_hold_days": 3},
    ],
    staged_breakeven_enabled=True,
    staged_breakeven_levels=[
        {"activation_pct": 0.05, "floor_pct": 0.0},
        {"activation_pct": 0.08, "floor_pct": 0.03},
        {"activation_pct": 0.12, "floor_pct": 0.06},
    ],
)


def load_all_closed_trades() -> list[dict]:
    state_path = ROOT / "data" / "tracking" / "pnl_state.json"
    with open(state_path) as f:
        state = json.load(f)
    return [t for t in state.get("trades", []) if t.get("status") == "closed"]


_price_cache: dict[str, dict[str, float]] = {}


def fetch_daily_closes(symbol: str, start: str, end: str) -> dict[str, float]:
    """Fetch and cache daily closes for symbol over [start, end] (ISO dates)."""
    cache_key = f"{symbol}:{start}:{end}"
    if cache_key in _price_cache:
        return _price_cache[cache_key]
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start, end=end, interval="1d")
        result = {}
        if not hist.empty:
            for idx, row in hist.iterrows():
                date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                result[date_str] = float(row["Close"])
        _price_cache[cache_key] = result
        return result
    except Exception as e:
        print(f"    [WARN] price fetch failed for {symbol}: {e}", file=sys.stderr)
        _price_cache[cache_key] = {}
        return {}


def compute_atr_pct_at_entry(symbol: str, entry_date: str, window: int = 14) -> float | None:
    end = (datetime.fromisoformat(entry_date).date() + timedelta(days=1)).isoformat()
    start = (datetime.fromisoformat(entry_date).date() - timedelta(days=window * 3)).isoformat()
    hist_closes = fetch_daily_closes(symbol, start, end)
    if len(hist_closes) < 2:
        return None
    # Need High/Low too -- refetch with full OHLC (fetch_daily_closes only kept Close).
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start, end=end, interval="1d")
        if hist.empty or len(hist) < 2:
            return None
        hist = hist.tail(window + 1)
        closes = hist["Close"].tolist()
        highs = hist["High"].tolist()
        lows = hist["Low"].tolist()
        if not closes or closes[-1] <= 0:
            return None
        true_ranges = []
        prev_close = None
        for h, l, c in zip(highs, lows, closes):
            tr = (h - l) if prev_close is None else max(h - l, abs(h - prev_close), abs(l - prev_close))
            true_ranges.append(tr)
            prev_close = c
        atr = sum(true_ranges) / len(true_ranges)
        return atr / closes[-1]
    except Exception as e:
        print(f"    [WARN] ATR fetch failed for {symbol}@{entry_date}: {e}", file=sys.stderr)
        return None


def replay_exit(
    strat: SimpleExitV2Strategy,
    entry_price: float,
    entry_signal_strength: float | None,
    daily_closes: list[tuple[str, float]],  # sorted (date, close) from entry onward
    volatility_multiplier: float,
) -> dict:
    """Replay SimpleExitV2Strategy's priority-ordered exit logic day-by-day
    against a real historical daily-close path, starting the day after entry.

    Returns {"exit_date", "exit_price", "exit_reason", "hold_days"} for the
    first day an exit condition is met, or a "still_open" marker if the path
    runs out (data ends) without triggering any exit.
    """
    eff_stop_loss_pct, eff_trailing_activation_pct = strat._resolve_thresholds(
        entry_signal_strength, hold_days=999,  # assume graduated; simplification for path replay
        volatility_multiplier=volatility_multiplier,
    )

    peak_price = entry_price
    for day_idx, (date_str, close) in enumerate(daily_closes, start=1):
        hold_days = day_idx  # approx: 1 trading day per bar
        if close > peak_price:
            peak_price = close
        return_pct = (close - entry_price) / entry_price
        peak_return_pct = (peak_price - entry_price) / entry_price

        trailing_active, _, active_trailing_stop_pct, staged_level = strat._resolve_trailing_rule(
            peak_return_pct, eff_trailing_activation_pct
        )

        if trailing_active:
            trailing_stop_price = peak_price * (1 - active_trailing_stop_pct)
            if close <= trailing_stop_price:
                return {
                    "exit_date": date_str, "exit_price": close,
                    "exit_reason": "trailing_stop", "hold_days": hold_days,
                }
            continue

        be_activated, be_floor_pct, _ = strat._resolve_breakeven_floor(
            peak_return_pct, strat.breakeven_activation_pct
        )
        if be_activated:
            if return_pct <= be_floor_pct:
                return {
                    "exit_date": date_str, "exit_price": close,
                    "exit_reason": "breakeven_stop", "hold_days": hold_days,
                }
            continue

        if return_pct <= eff_stop_loss_pct:
            eff_min_hold = strat._effective_min_hold_days(return_pct, eff_stop_loss_pct=eff_stop_loss_pct)
            if (
                strat.min_hold_days_enabled
                and hold_days < eff_min_hold
                and return_pct > strat.emergency_stop_bypass_pct
            ):
                pass  # suppressed by min_hold, keep going
            else:
                return {
                    "exit_date": date_str, "exit_price": close,
                    "exit_reason": "stop_loss", "hold_days": hold_days,
                }
            continue

        if hold_days >= strat.max_hold_days:
            return {
                "exit_date": date_str, "exit_price": close,
                "exit_reason": "time_based", "hold_days": hold_days,
            }

    return {"exit_date": None, "exit_price": None, "exit_reason": "still_open", "hold_days": len(daily_closes)}


def simulate_all_trades(
    trades: list[dict],
    multiplier_min: float = 0.5,
    multiplier_max: float = 1.75,
    atr_window: int = 14,
    extra_days_beyond_actual_exit: int = 30,
) -> list[dict]:
    strat_baseline = SimpleExitV2Strategy(**PROD_CONFIG, volatility_adjusted_stop_enabled=False)
    strat_adjusted = SimpleExitV2Strategy(
        **PROD_CONFIG, volatility_adjusted_stop_enabled=True,
        volatility_multiplier_min=multiplier_min, volatility_multiplier_max=multiplier_max,
    )

    # First pass: compute ATR% for every trade's symbol at its entry date,
    # to build a "same time window" universe average.
    trade_atr: list[tuple[dict, float | None]] = []
    for t in trades:
        entry_date = (t.get("entry_time") or "")[:10]
        if not entry_date:
            trade_atr.append((t, None))
            continue
        atr_pct = compute_atr_pct_at_entry(t["symbol"], entry_date, window=atr_window)
        trade_atr.append((t, atr_pct))

    results = []
    for t, symbol_atr_pct in trade_atr:
        entry_date = (t.get("entry_time") or "")[:10]
        exit_date = (t.get("exit_time") or "")[:10]
        entry_price = t.get("entry_price")
        qty = t.get("qty")
        if not entry_date or not exit_date or not entry_price or not qty:
            continue

        # Universe average: ATR% of all OTHER trades entered within +/-3
        # calendar days of this trade's entry date.
        entry_dt = datetime.fromisoformat(entry_date)
        window_atrs = []
        for t2, atr2 in trade_atr:
            e2 = (t2.get("entry_time") or "")[:10]
            if not e2 or atr2 is None:
                continue
            try:
                d2 = datetime.fromisoformat(e2)
            except ValueError:
                continue
            if abs((d2 - entry_dt).days) <= 3:
                window_atrs.append(atr2)
        universe_avg = (sum(window_atrs) / len(window_atrs)) if window_atrs else None

        volatility_multiplier = SimpleExitV2Strategy.compute_volatility_multiplier(
            symbol_atr_pct=symbol_atr_pct,
            universe_avg_atr_pct=universe_avg,
            min_multiplier=multiplier_min,
            max_multiplier=multiplier_max,
        )

        # Fetch daily closes from entry to well beyond the actual exit date,
        # so a widened threshold has room to show a later exit.
        fetch_end = (
            datetime.fromisoformat(exit_date).date()
            + timedelta(days=extra_days_beyond_actual_exit + 10)
        ).isoformat()
        closes = fetch_daily_closes(t["symbol"], entry_date, fetch_end)
        sorted_dates = sorted(d for d in closes if d > entry_date)
        daily_path = [(d, closes[d]) for d in sorted_dates]
        if not daily_path:
            continue

        entry_signal_strength = t.get("entry_signal_strength")

        baseline_result = replay_exit(strat_baseline, entry_price, entry_signal_strength, daily_path, 1.0)
        adjusted_result = replay_exit(strat_adjusted, entry_price, entry_signal_strength, daily_path, volatility_multiplier)

        def _pnl(exit_price):
            if exit_price is None:
                return None
            return qty * (exit_price - entry_price)

        baseline_pnl = _pnl(baseline_result["exit_price"])
        adjusted_pnl = _pnl(adjusted_result["exit_price"])

        results.append({
            "symbol": t["symbol"],
            "entry_date": entry_date,
            "actual_exit_date": exit_date,
            "actual_exit_reason": t.get("exit_reason"),
            "actual_pnl": t.get("pnl"),
            "same_day_entry_exit": entry_date == exit_date,
            "symbol_atr_pct": symbol_atr_pct,
            "universe_avg_atr_pct": universe_avg,
            "volatility_multiplier": round(volatility_multiplier, 3),
            "baseline_exit_reason": baseline_result["exit_reason"],
            "baseline_exit_date": baseline_result["exit_date"],
            "baseline_pnl": baseline_pnl,
            "adjusted_exit_reason": adjusted_result["exit_reason"],
            "adjusted_exit_date": adjusted_result["exit_date"],
            "adjusted_pnl": adjusted_pnl,
            "pnl_diff": (adjusted_pnl - baseline_pnl) if (adjusted_pnl is not None and baseline_pnl is not None) else None,
            "reason_changed": baseline_result["exit_reason"] != adjusted_result["exit_reason"],
        })

    return results


def print_report(results: list[dict]) -> None:
    print("=" * 90)
    print("Daily-Path Historical Validation — Volatility-Adjusted Stop Loss")
    print("=" * 90)
    print()
    print(f"Total trades simulated: {len(results)}")

    same_day = [r for r in results if r["same_day_entry_exit"]]
    print(f"  Same-day entry/exit (excluded from replay -- this daily-close-bar")
    print(f"  method has no data point to start evaluating from until the day")
    print(f"  AFTER entry, so a same-day exit cannot be replayed at all): "
          f"{len(same_day)}")

    with_pnl = [
        r for r in results
        if r["pnl_diff"] is not None and not r["same_day_entry_exit"]
    ]
    print(f"With comparable PnL (excl. same-day): {len(with_pnl)}")
    print()

    # Sanity check: baseline replay vs actual production outcome
    # (excludes same-day trades, which can never match by construction --
    # see the same_day_entry_exit exclusion above)
    comparable = [r for r in results if not r["same_day_entry_exit"]]
    reason_match = sum(1 for r in comparable if r["baseline_exit_reason"] == r["actual_exit_reason"])
    print(f"[Sanity check] baseline replay exit_reason matches actual production: "
          f"{reason_match}/{len(comparable)} ({reason_match/len(comparable)*100:.0f}%)")
    print("  (Mismatches are expected -- this replay uses only daily closes, not")
    print("   the live system's intraday price feed/broker fills/ATR-at-run-time,")
    print("   so exact-day/reason parity is not expected. This check exists to")
    print("   confirm the replay logic is in the right ballpark, not to validate")
    print("   it perfectly reproduces history.)")
    print()

    changed = [r for r in with_pnl if r["reason_changed"]]
    print(f"Trades where the exit reason changed (baseline vs volatility-adjusted): {len(changed)}/{len(with_pnl)}")
    print()

    total_baseline = sum(r["baseline_pnl"] for r in with_pnl)
    total_adjusted = sum(r["adjusted_pnl"] for r in with_pnl)
    net_diff = total_adjusted - total_baseline

    print("─" * 90)
    print("AGGREGATE RESULT (primary metric)")
    print("─" * 90)
    print(f"  Baseline (current production logic) total PnL over replayed paths: ${total_baseline:,.2f}")
    print(f"  Volatility-adjusted total PnL over replayed paths:                 ${total_adjusted:,.2f}")
    print(f"  Net diff (adjusted - baseline):                                    ${net_diff:+,.2f}")
    print(f"    (positive = volatility adjustment would have been NET BETTER)")
    print()

    improved = [r for r in with_pnl if r["pnl_diff"] > 0]
    worsened = [r for r in with_pnl if r["pnl_diff"] < 0]
    unchanged = [r for r in with_pnl if r["pnl_diff"] == 0]
    print(f"  Trades improved:  {len(improved):3d}  (sum ${sum(r['pnl_diff'] for r in improved):+,.2f})")
    print(f"  Trades worsened:  {len(worsened):3d}  (sum ${sum(r['pnl_diff'] for r in worsened):+,.2f})")
    print(f"  Trades unchanged: {len(unchanged):3d}")
    print()

    # Critical check: did previously-fine (non-stop_loss) trades get newly
    # broken by a tightened threshold?
    newly_broken = [
        r for r in with_pnl
        if r["actual_exit_reason"] != "stop_loss"
        and r["adjusted_exit_reason"] == "stop_loss"
        and r["baseline_exit_reason"] != "stop_loss"
        and r["pnl_diff"] < 0
    ]
    print("─" * 90)
    print(f"[KEY RISK CHECK] Previously-non-stop_loss trades newly stopped out "
          f"by tightened threshold: {len(newly_broken)}")
    print("─" * 90)
    if newly_broken:
        for r in sorted(newly_broken, key=lambda x: x["pnl_diff"])[:10]:
            print(
                f"    {r['symbol']:8s} {r['entry_date']}  actual_reason={r['actual_exit_reason']:14s} "
                f"mult={r['volatility_multiplier']:.2f}  "
                f"baseline=${r['baseline_pnl']:+9.2f}({r['baseline_exit_reason']})  "
                f"adjusted=${r['adjusted_pnl']:+9.2f}({r['adjusted_exit_reason']})  diff=${r['pnl_diff']:+9.2f}"
            )
    else:
        print("  None found -- tightening did not create new false-positive stops")
        print("  among trades that were not originally stop_loss exits in the")
        print("  baseline replay.")
    print()

    print("─" * 90)
    print("Top 10 biggest improvements (widened threshold avoided a bad exit)")
    print("─" * 90)
    for r in sorted(with_pnl, key=lambda x: -x["pnl_diff"])[:10]:
        print(
            f"    {r['symbol']:8s} {r['entry_date']}  mult={r['volatility_multiplier']:.2f}  "
            f"baseline=${r['baseline_pnl']:+9.2f}({r['baseline_exit_reason']})  "
            f"adjusted=${r['adjusted_pnl']:+9.2f}({r['adjusted_exit_reason']})  diff=${r['pnl_diff']:+9.2f}"
        )
    print()
    print("─" * 90)
    print("Top 10 biggest regressions (adjustment made things worse)")
    print("─" * 90)
    for r in sorted(with_pnl, key=lambda x: x["pnl_diff"])[:10]:
        print(
            f"    {r['symbol']:8s} {r['entry_date']}  mult={r['volatility_multiplier']:.2f}  "
            f"baseline=${r['baseline_pnl']:+9.2f}({r['baseline_exit_reason']})  "
            f"adjusted=${r['adjusted_pnl']:+9.2f}({r['adjusted_exit_reason']})  diff=${r['pnl_diff']:+9.2f}"
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Daily-path historical validation of volatility_adjusted_stop_enabled")
    parser.add_argument("--multiplier-min", type=float, default=0.5)
    parser.add_argument("--multiplier-max", type=float, default=1.75)
    parser.add_argument("--atr-window", type=int, default=14)
    parser.add_argument("--extra-days", type=int, default=30,
                         help="Extra days of price data to fetch beyond the actual exit date")
    args = parser.parse_args()

    trades = load_all_closed_trades()
    print(f"Loaded {len(trades)} closed trades. Running daily-path replay (this will take a few minutes)...\n")

    results = simulate_all_trades(
        trades,
        multiplier_min=args.multiplier_min,
        multiplier_max=args.multiplier_max,
        atr_window=args.atr_window,
        extra_days_beyond_actual_exit=args.extra_days,
    )
    print_report(results)
