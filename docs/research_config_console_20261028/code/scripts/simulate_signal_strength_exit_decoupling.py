"""R13-B (2026-08-23): Daily-path historical validation of decoupling
signal_strength (entry_signal_strength) from exit-threshold tiering.

Background (docs/console_improvement_tasks.md R13-B): `reports/
signal_strength_decile.json`'s decile-level expectancy is completely
non-monotonic (decile 3 best at +$78, decile 9 worst at -$1,503 -- no
"higher score is better" relationship). Re-checked here on the attributable
cohort specifically (n=49, the same population where R13-A's motivating
asymmetry was found): confidence tiers derived from entry_signal_strength
are ALSO non-monotonic (mid tier worst at expectancy=-$179, high tier
n=11 at +$155 but with only 36.4% win rate, low tier best at +$103).
Despite this, SimpleExitV2Strategy._resolve_thresholds() currently widens
the stop_loss threshold and delays trailing_stop activation for
high-signal-strength positions (-9% stop / +6% trailing) and does the
opposite for low-signal-strength positions (-5% stop / +10% trailing) --
i.e. risk is being adjusted based on a signal that does not reliably
predict outcome quality.

This script tests Option (B) from R13-B ("decouple" -- signal_strength no
longer affects exit thresholds; every position uses the STANDARD
conviction tier's thresholds, -7% stop / +8% trailing, regardless of
entry_signal_strength) against the CURRENT production tiered behavior,
using the same daily-path replay methodology as R13-A's
simulate_stop_loss_deepening.py (itself modeled on
simulate_daily_path_volatility_stop.py, 2026-08-14): the full
priority-ordered exit logic (trailing_stop -> breakeven_stop -> stop_loss
-> time_based) is replayed day-by-day using SimpleExitV2Strategy's own
methods, over real historical daily closes, for every closed trade with a
known entry_signal_strength.

This script does NOT test Option (A) (cross-sectional-percentile-based
sizing) -- that changes SIZING (dollar amount put at risk), not EXIT
thresholds, and cannot be backtested against fixed historical qty values
the way exit-threshold changes can (the qty was already fixed at trade
time under the OLD sizing rule; simulating a different sizing rule would
require re-deriving what the confidence_multiplier bug fix would have
sized each trade to, which is a separate, larger analysis). Option (A) and
the confidence_multiplier no-op bug fix remain PLANNED, pending this
exit-threshold result and separate sizing-focused validation.

Usage:
    python scripts/simulate_signal_strength_exit_decoupling.py
        [--attributable-only] [--since 2026-08-05] [--extra-days 30]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yfinance as yf

from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy

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
    volatility_adjusted_stop_enabled=True,
    volatility_multiplier_min=0.5,
    volatility_multiplier_max=1.75,
)


class UniformThresholdSimpleExitV2Strategy(SimpleExitV2Strategy):
    """R13-B Option (B): ignore entry_signal_strength entirely for exit
    threshold selection -- every position uses the STANDARD tier
    (self.stop_loss_pct / self.trailing_activation_pct from config), as if
    entry_signal_strength were always in the mid band. Volatility
    adjustment and all other exit logic (trailing/breakeven/min-hold) is
    left untouched -- this isolates ONLY the signal-strength-tiering
    effect, not a re-litigation of already-validated mechanisms.
    """

    def _resolve_thresholds(
        self,
        entry_signal_strength: float | None,
        hold_days: float | None = None,
        volatility_multiplier: float = 1.0,
    ) -> tuple[float, float]:
        # Force the STANDARD tier unconditionally (bypasses the
        # entry_signal_strength / graduation branching in the parent
        # entirely), then still apply volatility adjustment via the
        # parent's own choke point for an apples-to-apples comparison.
        return (
            self._apply_volatility_multiplier(self.stop_loss_pct, volatility_multiplier),
            self.trailing_activation_pct,
        )


_UNTRACKED_ORIGIN_IDS = {"broker_reconstructed", "reconciled_from_broker"}


def load_trades_with_signal_strength(since: str | None = None, attributable_only: bool = False) -> list[dict]:
    state_path = ROOT / "data" / "tracking" / "pnl_state.json"
    with open(state_path) as f:
        state = json.load(f)
    trades = [
        t for t in state.get("trades", [])
        if t.get("status") == "closed" and t.get("entry_signal_strength") is not None
    ]
    if since:
        trades = [t for t in trades if (t.get("exit_time") or "")[:10] >= since]
    if attributable_only:
        trades = [
            t for t in trades
            if (t.get("original_strategy_id") or t.get("strategy_id")) not in _UNTRACKED_ORIGIN_IDS
        ]
    return trades


_price_cache: dict[str, dict[str, float]] = {}


def fetch_daily_closes(symbol: str, start: str, end: str) -> dict[str, float]:
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
    daily_closes: list[tuple[str, float]],
    volatility_multiplier: float,
) -> dict:
    eff_stop_loss_pct, eff_trailing_activation_pct = strat._resolve_thresholds(
        entry_signal_strength, hold_days=999,
        volatility_multiplier=volatility_multiplier,
    )

    peak_price = entry_price
    for day_idx, (date_str, close) in enumerate(daily_closes, start=1):
        hold_days = day_idx
        if close > peak_price:
            peak_price = close
        return_pct = (close - entry_price) / entry_price
        peak_return_pct = (peak_price - entry_price) / entry_price

        trailing_active, _, active_trailing_stop_pct, _ = strat._resolve_trailing_rule(
            peak_return_pct, eff_trailing_activation_pct
        )
        if trailing_active:
            trailing_stop_price = peak_price * (1 - active_trailing_stop_pct)
            if close <= trailing_stop_price:
                return {"exit_date": date_str, "exit_price": close, "exit_reason": "trailing_stop", "hold_days": hold_days}
            continue

        be_activated, be_floor_pct, _ = strat._resolve_breakeven_floor(
            peak_return_pct, strat.breakeven_activation_pct
        )
        if be_activated:
            if return_pct <= be_floor_pct:
                return {"exit_date": date_str, "exit_price": close, "exit_reason": "breakeven_stop", "hold_days": hold_days}
            continue

        if return_pct <= eff_stop_loss_pct:
            eff_min_hold = strat._effective_min_hold_days(return_pct, eff_stop_loss_pct=eff_stop_loss_pct)
            if (
                strat.min_hold_days_enabled
                and hold_days < eff_min_hold
                and return_pct > strat.emergency_stop_bypass_pct
            ):
                pass
            else:
                return {"exit_date": date_str, "exit_price": close, "exit_reason": "stop_loss", "hold_days": hold_days}
            continue

        if hold_days >= strat.max_hold_days:
            return {"exit_date": date_str, "exit_price": close, "exit_reason": "time_based", "hold_days": hold_days}

    return {"exit_date": None, "exit_price": None, "exit_reason": "still_open", "hold_days": len(daily_closes)}


def simulate_all_trades(
    trades: list[dict],
    atr_window: int = 14,
    extra_days_beyond_actual_exit: int = 30,
) -> list[dict]:
    strat_tiered = SimpleExitV2Strategy(**PROD_CONFIG)
    strat_uniform = UniformThresholdSimpleExitV2Strategy(**PROD_CONFIG)

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
        entry_signal_strength = t.get("entry_signal_strength")
        if not entry_date or not exit_date or not entry_price or not qty:
            continue

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
            min_multiplier=PROD_CONFIG["volatility_multiplier_min"],
            max_multiplier=PROD_CONFIG["volatility_multiplier_max"],
        )

        fetch_end = (
            datetime.fromisoformat(exit_date).date()
            + timedelta(days=extra_days_beyond_actual_exit + 10)
        ).isoformat()
        closes = fetch_daily_closes(t["symbol"], entry_date, fetch_end)
        sorted_dates = sorted(d for d in closes if d > entry_date)
        daily_path = [(d, closes[d]) for d in sorted_dates]
        if not daily_path:
            continue

        tiered_result = replay_exit(strat_tiered, entry_price, entry_signal_strength, daily_path, volatility_multiplier)
        uniform_result = replay_exit(strat_uniform, entry_price, entry_signal_strength, daily_path, volatility_multiplier)

        def _pnl(exit_price):
            if exit_price is None:
                return None
            return qty * (exit_price - entry_price)

        tiered_pnl = _pnl(tiered_result["exit_price"])
        uniform_pnl = _pnl(uniform_result["exit_price"])

        conviction_tier = (
            "high" if entry_signal_strength >= SimpleExitV2Strategy.HIGH_STRENGTH_THRESHOLD
            else "low" if entry_signal_strength < SimpleExitV2Strategy.LOW_STRENGTH_THRESHOLD
            else "standard"
        )

        results.append({
            "symbol": t["symbol"],
            "entry_date": entry_date,
            "actual_exit_date": exit_date,
            "actual_exit_reason": t.get("exit_reason"),
            "actual_pnl": t.get("pnl"),
            "same_day_entry_exit": entry_date == exit_date,
            "entry_signal_strength": entry_signal_strength,
            "conviction_tier": conviction_tier,
            "tiered_exit_reason": tiered_result["exit_reason"],
            "tiered_pnl": tiered_pnl,
            "uniform_exit_reason": uniform_result["exit_reason"],
            "uniform_pnl": uniform_pnl,
            "pnl_diff": (uniform_pnl - tiered_pnl) if (uniform_pnl is not None and tiered_pnl is not None) else None,
            "reason_changed": tiered_result["exit_reason"] != uniform_result["exit_reason"],
        })

    return results


def _max_drawdown_of_path(pnls_in_order: list[float], baseline_equity: float) -> float:
    running = baseline_equity
    peak = baseline_equity
    max_dd = 0.0
    for pnl in pnls_in_order:
        running += pnl
        if running > peak:
            peak = running
        if peak > 0:
            dd = (peak - running) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _cvar(pnls: list[float], alpha: float = 0.10) -> float | None:
    if not pnls:
        return None
    sorted_pnls = sorted(pnls)
    n_tail = max(1, int(len(sorted_pnls) * alpha))
    return sum(sorted_pnls[:n_tail]) / n_tail


def print_report(results: list[dict], baseline_equity: float = 1_000_000.0) -> None:
    print("=" * 90)
    print("R13-B: Daily-Path Historical Validation — Decoupling signal_strength from Exit Thresholds")
    print("Comparing: current tiered thresholds (-5/-7/-9% by conviction) vs uniform -7% for all")
    print("=" * 90)
    print()
    print(f"Total trades simulated: {len(results)}")

    same_day = [r for r in results if r["same_day_entry_exit"]]
    print(f"  Same-day entry/exit (excluded): {len(same_day)}")

    with_pnl = [r for r in results if r["pnl_diff"] is not None and not r["same_day_entry_exit"]]
    print(f"With comparable PnL (excl. same-day): {len(with_pnl)}")
    print()

    print("─" * 90)
    print("By conviction tier (current production tiering)")
    print("─" * 90)
    from collections import defaultdict
    by_tier = defaultdict(list)
    for r in with_pnl:
        by_tier[r["conviction_tier"]].append(r)
    for tier_name in ("low", "standard", "high"):
        tier_trades = by_tier.get(tier_name, [])
        if not tier_trades:
            continue
        tiered_sum = sum(r["tiered_pnl"] for r in tier_trades)
        uniform_sum = sum(r["uniform_pnl"] for r in tier_trades)
        print(f"  {tier_name:10s} n={len(tier_trades):3d}  tiered=${tiered_sum:+10,.2f}  "
              f"uniform=${uniform_sum:+10,.2f}  diff=${uniform_sum-tiered_sum:+10,.2f}")
    print()

    changed = [r for r in with_pnl if r["reason_changed"]]
    print(f"Trades where exit reason changed (tiered vs uniform): {len(changed)}/{len(with_pnl)}")
    print()

    total_tiered = sum(r["tiered_pnl"] for r in with_pnl)
    total_uniform = sum(r["uniform_pnl"] for r in with_pnl)
    net_diff = total_uniform - total_tiered

    print("─" * 90)
    print("AGGREGATE RESULT (primary metric: net PnL over replayed paths)")
    print("─" * 90)
    print(f"  Tiered (current production, signal_strength-linked) total PnL: ${total_tiered:,.2f}")
    print(f"  Uniform (decoupled, Option B) total PnL:                       ${total_uniform:,.2f}")
    print(f"  Net diff (uniform - tiered):                                   ${net_diff:+,.2f}")
    print(f"    (positive = decoupling would have been NET BETTER)")
    print()

    improved = [r for r in with_pnl if r["pnl_diff"] > 0]
    worsened = [r for r in with_pnl if r["pnl_diff"] < 0]
    unchanged = [r for r in with_pnl if r["pnl_diff"] == 0]
    print(f"  Trades improved:  {len(improved):3d}  (sum ${sum(r['pnl_diff'] for r in improved):+,.2f})")
    print(f"  Trades worsened:  {len(worsened):3d}  (sum ${sum(r['pnl_diff'] for r in worsened):+,.2f})")
    print(f"  Trades unchanged: {len(unchanged):3d}")
    print()

    print("─" * 90)
    print("RISK METRICS")
    print("─" * 90)
    tiered_pnls_ordered = [r["tiered_pnl"] for r in sorted(with_pnl, key=lambda x: x["actual_exit_date"] or "")]
    uniform_pnls_ordered = [r["uniform_pnl"] for r in sorted(with_pnl, key=lambda x: x["actual_exit_date"] or "")]
    tiered_dd = _max_drawdown_of_path(tiered_pnls_ordered, baseline_equity)
    uniform_dd = _max_drawdown_of_path(uniform_pnls_ordered, baseline_equity)
    tiered_cvar = _cvar([r["tiered_pnl"] for r in with_pnl])
    uniform_cvar = _cvar([r["uniform_pnl"] for r in with_pnl])
    print(f"  Max drawdown on replayed path (baseline equity ${baseline_equity:,.0f}):")
    print(f"    Tiered: {tiered_dd*100:.2f}%   Uniform: {uniform_dd*100:.2f}%   Delta: {(uniform_dd-tiered_dd)*100:+.2f}pp")
    if tiered_cvar is not None and uniform_cvar is not None:
        print(f"  CVaR (avg of worst 10% of trade outcomes):")
        print(f"    Tiered: ${tiered_cvar:+,.2f}   Uniform: ${uniform_cvar:+,.2f}   Delta: ${uniform_cvar-tiered_cvar:+,.2f}")
    print()

    print("─" * 90)
    print("Top 10 biggest improvements (decoupling would have helped)")
    print("─" * 90)
    for r in sorted(with_pnl, key=lambda x: -x["pnl_diff"])[:10]:
        print(
            f"    {r['symbol']:8s} {r['entry_date']}  tier={r['conviction_tier']:8s} ss={r['entry_signal_strength']:.3f}  "
            f"tiered=${r['tiered_pnl']:+9.2f}({r['tiered_exit_reason']})  "
            f"uniform=${r['uniform_pnl']:+9.2f}({r['uniform_exit_reason']})  diff=${r['pnl_diff']:+9.2f}"
        )
    print()
    print("─" * 90)
    print("Top 10 biggest regressions (decoupling would have hurt)")
    print("─" * 90)
    for r in sorted(with_pnl, key=lambda x: x["pnl_diff"])[:10]:
        print(
            f"    {r['symbol']:8s} {r['entry_date']}  tier={r['conviction_tier']:8s} ss={r['entry_signal_strength']:.3f}  "
            f"tiered=${r['tiered_pnl']:+9.2f}({r['tiered_exit_reason']})  "
            f"uniform=${r['uniform_pnl']:+9.2f}({r['uniform_exit_reason']})  diff=${r['pnl_diff']:+9.2f}"
        )
    print()

    print("─" * 90)
    print("VERDICT")
    print("─" * 90)
    dd_worse = (uniform_dd - tiered_dd) > 0.005
    cvar_worse = (tiered_cvar is not None and uniform_cvar is not None and tiered_cvar != 0
                  and uniform_cvar < tiered_cvar * 1.05)
    if net_diff > 0 and not dd_worse and not cvar_worse:
        print("  ✅ Net PnL improved AND no material DD/CVaR regression -> supports proceeding to paper A/B.")
    elif net_diff > 0 and (dd_worse or cvar_worse):
        print("  ⚠️  Net PnL improved BUT DD and/or CVaR worsened materially -> weigh tail risk before A/B.")
    else:
        print("  ❌ Net PnL did not improve -> decoupling (Option B) does not look favorable on this data;")
        print("      consider Option (A, cross-sectional percentile) instead, or hold.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="R13-B: daily-path historical validation of signal_strength/exit decoupling")
    parser.add_argument("--since", type=str, default=None, help="Only trades exited on/after YYYY-MM-DD")
    parser.add_argument("--extra-days", type=int, default=30)
    parser.add_argument("--atr-window", type=int, default=14)
    parser.add_argument("--attributable-only", action="store_true",
                         help="Restrict to attributable-cohort trades (real decision provenance)")
    args = parser.parse_args()

    trades = load_trades_with_signal_strength(since=args.since, attributable_only=args.attributable_only)
    print(f"Loaded {len(trades)} closed trades with entry_signal_strength" +
          (f" (since {args.since})" if args.since else "") +
          (" (attributable-only)" if args.attributable_only else "") +
          ". Running daily-path replay (this will take a few minutes)...\n")

    results = simulate_all_trades(
        trades,
        atr_window=args.atr_window,
        extra_days_beyond_actual_exit=args.extra_days,
    )
    print_report(results)
