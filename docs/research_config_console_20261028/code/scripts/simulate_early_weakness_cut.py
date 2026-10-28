"""R13-A2 (2026-09-05): Daily-path historical validation of an "early weakness cut".

Background (docs/console_improvement_tasks.md R13 group): paper results
(pnl_state.json, 5/12-09/05, 357 closed) show stop_loss as the dominant
bleed (-$216k over 147 trades), and within that, stops held >= 5 days are
the main source (57 trades, -$125.6k). Since 2026-07-16, d5+ stops ran
n=21 / -$48.6k with a median exit of -8.1% -- gaps/slippage blow through
the -7% threshold. Hypothesis: positions that (1) never developed any
meaningful unrealized gain and (2) are already clearly under water are
statistically unlikely to recover to trailing_stop territory, so cutting
them EARLY at a shallower loss (before the hard stop is hit days later,
deeper) should reduce the bleed without giving up eventual winners.

Counterfactual rule under test ("early weakness cut"):
    From holding day K onward, at each daily close:
        if  max unrealized gain since entry < +2%
        and current return <= -3%
        then exit at that day's close (evaluated BEFORE the hard stop_loss).
    Variants: K in {3, 4, 5}.

Note on priority placement: the rule only ever fires while peak return is
< +2%, i.e. strictly below every trailing/breakeven activation level (+5%
minimum), so trailing_stop and breakeven_stop can never be active on a day
the rule fires. Inserting the check immediately before the stop_loss
branch is therefore exactly equivalent to "evaluated before the hard stop"
as specified.

Methodology (mirrors scripts/simulate_stop_loss_deepening.py's 2026-08-23
daily-path replay design, itself derived from
scripts/simulate_daily_path_volatility_stop.py, 2026-08-14):
  1. Exit priority order is respected: trailing_stop -> breakeven_stop ->
     [early_weakness_cut] -> stop_loss -> time_based, replayed day-by-day
     using SimpleExitV2Strategy's own methods (not a reimplementation).
  2. ALL closed trades are replayed (not just the stop_loss ones), so the
     rule's opportunity cost -- cutting a trade that would have recovered
     to a profitable exit -- is directly measurable, not assumed away.

Both baseline and cut variants use the CURRENT production config
(config/strategy/simple_exit_v2.yaml as of 2026-09-05, including
volatility_adjusted_stop_enabled=True), applied identically to both sides,
so the measured PnL difference isolates ONLY the early-weakness-cut rule.
(per_lot_time_based_exit_enabled is default-off in production and this
replay is single-lot per trade by construction, so it is not modeled.)

Cohorts reported (variants x cohorts):
  (a) full:         all closed trades
  (b) recent:       exit_time >= 2026-07-16
  (c) attributable: (original_strategy_id or strategy_id) not in
                    {broker_reconstructed, reconciled_from_broker} --
                    same classification as simulate_stop_loss_deepening.py
                    / PnLTracker.get_attribution_quality_breakdown().

Approximation caveats (same as the two predecessor scripts):
  - ATR% computed once per trade at entry_time and held constant.
  - universe_avg_atr_pct approximated from trades entered within +/-3
    calendar days (computed over the FULL trade set once, then reused for
    every cohort slice -- cohorts are views over one replay pass).
  - Daily bars only (no intraday); same-day entry/exit trades excluded.
  - This is a read-only research script. It does not modify
    config/strategy/simple_exit_v2.yaml or any production state.

Usage:
    python scripts/simulate_early_weakness_cut.py
        [--k-days 3 4 5] [--min-peak-gain 0.02] [--cut-return -0.03]
        [--recent-since 2026-07-16] [--extra-days 30] [--dump-json PATH]
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

# ── Current production config (config/strategy/simple_exit_v2.yaml, 2026-09-05) ──
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

_UNTRACKED_ORIGIN_IDS = {"broker_reconstructed", "reconciled_from_broker"}


def load_all_closed_trades() -> list[dict]:
    state_path = ROOT / "data" / "tracking" / "pnl_state.json"
    with open(state_path) as f:
        state = json.load(f)
    return [t for t in state.get("trades", []) if t.get("status") == "closed"]


def is_attributable(trade: dict) -> bool:
    return (trade.get("original_strategy_id") or trade.get("strategy_id")) not in _UNTRACKED_ORIGIN_IDS


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
    early_cut_k: int | None = None,
    early_cut_min_peak_gain: float = 0.02,
    early_cut_return: float = -0.03,
) -> dict:
    """Replay SimpleExitV2Strategy's priority-ordered exit logic day-by-day.

    Identical in structure to simulate_stop_loss_deepening.py's replay_exit()
    (kept as a self-contained copy for auditability, same as that script did
    vs. its own predecessor), plus one optional counterfactual branch: when
    early_cut_k is set, an "early_weakness_cut" exit is evaluated immediately
    before the stop_loss branch (see module docstring for why that placement
    is exactly equivalent to "before the hard stop").
    """
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

        # ── Counterfactual: early weakness cut (before the hard stop) ──
        if (
            early_cut_k is not None
            and hold_days >= early_cut_k
            and peak_return_pct < early_cut_min_peak_gain
            and return_pct <= early_cut_return
        ):
            return {"exit_date": date_str, "exit_price": close, "exit_reason": "early_weakness_cut", "hold_days": hold_days}

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
    k_variants: list[int],
    min_peak_gain: float,
    cut_return: float,
    atr_window: int = 14,
    extra_days_beyond_actual_exit: int = 30,
) -> list[dict]:
    """One replay pass over ALL trades: baseline + one variant per K.

    Cohorts are sliced later from the returned rows (each row carries
    actual_exit_date and attributable), so price/ATR data is fetched once.
    """
    strat = SimpleExitV2Strategy(**PROD_CONFIG)

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

        entry_signal_strength = t.get("entry_signal_strength")

        def _pnl(exit_price):
            if exit_price is None:
                return None
            return qty * (exit_price - entry_price)

        baseline_result = replay_exit(
            strat, entry_price, entry_signal_strength, daily_path,
            volatility_multiplier, early_cut_k=None,
        )
        baseline_pnl = _pnl(baseline_result["exit_price"])

        row = {
            "symbol": t["symbol"],
            "entry_date": entry_date,
            "actual_exit_date": exit_date,
            "actual_exit_reason": t.get("exit_reason"),
            "actual_pnl": t.get("pnl"),
            "attributable": is_attributable(t),
            "same_day_entry_exit": entry_date == exit_date,
            "volatility_multiplier": round(volatility_multiplier, 3),
            "baseline_exit_reason": baseline_result["exit_reason"],
            "baseline_exit_date": baseline_result["exit_date"],
            "baseline_hold_days": baseline_result["hold_days"],
            "baseline_pnl": baseline_pnl,
            "variants": {},
        }
        for k in k_variants:
            v = replay_exit(
                strat, entry_price, entry_signal_strength, daily_path,
                volatility_multiplier, early_cut_k=k,
                early_cut_min_peak_gain=min_peak_gain, early_cut_return=cut_return,
            )
            v_pnl = _pnl(v["exit_price"])
            row["variants"][str(k)] = {
                "exit_reason": v["exit_reason"],
                "exit_date": v["exit_date"],
                "hold_days": v["hold_days"],
                "pnl": v_pnl,
                "pnl_diff": (v_pnl - baseline_pnl) if (v_pnl is not None and baseline_pnl is not None) else None,
            }
        results.append(row)

    return results


def _profit_factor(pnls: list[float]) -> float | None:
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = sum(-p for p in pnls if p < 0)
    if gross_loss == 0:
        return None  # undefined (no losses)
    return gross_profit / gross_loss


def _max_drawdown_of_path(pnls_in_order: list[float], baseline_equity: float = 1_000_000.0) -> float:
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


def _fmt_pf(pf: float | None) -> str:
    return f"{pf:.3f}" if pf is not None else "n/a(no losses)"


def summarize_cohort(rows: list[dict], cohort_label: str, k_variants: list[int]) -> list[dict]:
    """Print the per-cohort report and return summary dicts (one per K)."""
    usable = [
        r for r in rows
        if not r["same_day_entry_exit"] and r["baseline_pnl"] is not None
        and all(r["variants"][str(k)]["pnl_diff"] is not None for k in k_variants)
    ]
    excluded = len(rows) - len(usable)

    print("=" * 90)
    print(f"COHORT: {cohort_label}")
    print("=" * 90)
    print(f"  Trades in cohort: {len(rows)}  (excluded from replay -- same-day entry/exit "
          f"or missing replay data: {excluded})")

    actual_pnls = [r["actual_pnl"] for r in usable if r["actual_pnl"] is not None]
    baseline_pnls = [r["baseline_pnl"] for r in usable]
    baseline_total = sum(baseline_pnls)
    baseline_pf = _profit_factor(baseline_pnls)
    baseline_dd = _max_drawdown_of_path(
        [r["baseline_pnl"] for r in sorted(usable, key=lambda x: x["baseline_exit_date"] or "")]
    )
    print(f"  Actual recorded PnL (reference):      ${sum(actual_pnls):+,.2f}  "
          f"(PF {_fmt_pf(_profit_factor(actual_pnls))})")
    print(f"  Baseline replay PnL (comparison base): ${baseline_total:+,.2f}  "
          f"(PF {_fmt_pf(baseline_pf)}, maxDD {baseline_dd*100:.2f}%)")

    reason_match = sum(1 for r in usable if r["baseline_exit_reason"] == r["actual_exit_reason"])
    print(f"  [Sanity check] baseline replay exit_reason matches actual: "
          f"{reason_match}/{len(usable)} ({reason_match/len(usable)*100:.0f}%)"
          if usable else "  [Sanity check] no usable trades")
    print("    (Daily-close-only replay vs. live intraday/broker fills -- mismatches expected;")
    print("     confirms ballpark fidelity, not exact reproduction.)")
    print()

    summaries = []
    for k in k_variants:
        key = str(k)
        v_pnls = [r["variants"][key]["pnl"] for r in usable]
        v_total = sum(v_pnls)
        v_pf = _profit_factor(v_pnls)
        v_dd = _max_drawdown_of_path(
            [r["variants"][key]["pnl"] for r in sorted(usable, key=lambda x: x["variants"][key]["exit_date"] or "")]
        )
        net_diff = v_total - baseline_total

        affected = [r for r in usable if r["variants"][key]["exit_reason"] == "early_weakness_cut"]
        affected_diff = sum(r["variants"][key]["pnl_diff"] for r in affected)
        # Opportunity loss: the cut fired, but the baseline path went on to a
        # PROFITABLE exit -- profit this rule would have forfeited.
        missed = [r for r in affected if r["baseline_pnl"] > 0]
        missed_forgone = sum(r["baseline_pnl"] - r["variants"][key]["pnl"] for r in missed)

        print("─" * 90)
        print(f"  VARIANT K={k} (cut from day {k} onward: peak gain < +2% AND return <= -3%)")
        print("─" * 90)
        print(f"    Variant replay PnL:        ${v_total:+,.2f}  (PF {_fmt_pf(v_pf)}, maxDD {v_dd*100:.2f}%)")
        print(f"    Net PnL diff vs baseline:  ${net_diff:+,.2f}   "
              f"(PF {_fmt_pf(baseline_pf)} -> {_fmt_pf(v_pf)}, "
              f"maxDD delta {(v_dd-baseline_dd)*100:+.2f}pp)")
        print(f"    Trades cut by the rule:    {len(affected)}"
              + (f"  (avg improvement per affected trade ${affected_diff/len(affected):+,.2f})" if affected else ""))
        print(f"    Opportunity loss (cut trades whose baseline path ended PROFITABLE): "
              f"{len(missed)} trade(s), forgone ${missed_forgone:+,.2f}")
        if missed:
            for r in sorted(missed, key=lambda x: -(x["baseline_pnl"] - x["variants"][key]["pnl"]))[:10]:
                vv = r["variants"][key]
                print(f"      {r['symbol']:8s} {r['entry_date']}  cut@{vv['exit_date']}(${vv['pnl']:+,.2f})  "
                      f"baseline={r['baseline_exit_reason']}@{r['baseline_exit_date']}(${r['baseline_pnl']:+,.2f})  "
                      f"forgone=${r['baseline_pnl']-vv['pnl']:+,.2f}")
        if affected:
            print(f"    Top 5 improvements among cut trades:")
            for r in sorted(affected, key=lambda x: -x["variants"][key]["pnl_diff"])[:5]:
                vv = r["variants"][key]
                print(f"      {r['symbol']:8s} {r['entry_date']}  cut@{vv['exit_date']}(${vv['pnl']:+,.2f})  "
                      f"baseline={r['baseline_exit_reason']}(${r['baseline_pnl']:+,.2f})  diff=${vv['pnl_diff']:+,.2f}")
        print()

        summaries.append({
            "cohort": cohort_label,
            "k": k,
            "n_usable": len(usable),
            "baseline_pnl": round(baseline_total, 2),
            "variant_pnl": round(v_total, 2),
            "net_diff": round(net_diff, 2),
            "baseline_pf": round(baseline_pf, 4) if baseline_pf is not None else None,
            "variant_pf": round(v_pf, 4) if v_pf is not None else None,
            "baseline_max_dd_pct": round(baseline_dd * 100, 2),
            "variant_max_dd_pct": round(v_dd * 100, 2),
            "affected_trades": len(affected),
            "avg_improvement_per_affected": round(affected_diff / len(affected), 2) if affected else None,
            "opportunity_loss_count": len(missed),
            "opportunity_loss_forgone": round(missed_forgone, 2),
        })
    print()
    return summaries


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="R13-A2: daily-path historical validation of an early weakness cut rule")
    parser.add_argument("--k-days", type=int, nargs="+", default=[3, 4, 5],
                        help="K variants: cut is evaluated from holding day K onward (default: 3 4 5)")
    parser.add_argument("--min-peak-gain", type=float, default=0.02,
                        help="Rule condition: max unrealized gain since entry must be BELOW this (default 0.02 = +2%%)")
    parser.add_argument("--cut-return", type=float, default=-0.03,
                        help="Rule condition: current return must be AT OR BELOW this (default -0.03 = -3%%)")
    parser.add_argument("--recent-since", type=str, default="2026-07-16",
                        help="Cohort (b) filter: exit_time >= this date (default 2026-07-16)")
    parser.add_argument("--extra-days", type=int, default=30,
                        help="Extra days of price data to fetch beyond the actual exit date")
    parser.add_argument("--atr-window", type=int, default=14)
    parser.add_argument("--dump-json", type=str, default=None,
                        help="Optional path to dump per-trade replay rows + cohort summaries as JSON")
    args = parser.parse_args()

    trades = load_all_closed_trades()
    print(f"Loaded {len(trades)} closed trades. Running daily-path replay "
          f"(baseline + K={args.k_days}; this will take a few minutes)...\n")

    rows = simulate_all_trades(
        trades,
        k_variants=args.k_days,
        min_peak_gain=args.min_peak_gain,
        cut_return=args.cut_return,
        atr_window=args.atr_window,
        extra_days_beyond_actual_exit=args.extra_days,
    )

    print("=" * 90)
    print("R13-A2: Daily-Path Historical Validation — Early Weakness Cut")
    print(f"Rule: from day K onward, exit at close if peak gain < {args.min_peak_gain*100:+.0f}% "
          f"AND return <= {args.cut_return*100:.0f}%  (K in {args.k_days})")
    print("=" * 90)
    print()

    cohorts = [
        ("(a) full: all closed trades", rows),
        (f"(b) recent: exit_time >= {args.recent_since}", [r for r in rows if r["actual_exit_date"] >= args.recent_since]),
        ("(c) attributable only", [r for r in rows if r["attributable"]]),
    ]
    all_summaries = []
    for label, cohort_rows in cohorts:
        all_summaries.extend(summarize_cohort(cohort_rows, label, args.k_days))

    print("=" * 90)
    print("SUMMARY TABLE (variant x cohort)")
    print("=" * 90)
    print(f"{'cohort':38s} {'K':>2s} {'n':>4s} {'netPnL diff':>12s} {'PF before->after':>18s} "
          f"{'cut':>4s} {'oppLoss n':>9s} {'forgone':>10s} {'maxDD delta':>11s}")
    for s in all_summaries:
        print(f"{s['cohort'][:38]:38s} {s['k']:2d} {s['n_usable']:4d} "
              f"{s['net_diff']:+12,.2f} "
              f"{(_fmt_pf(s['baseline_pf']) + '->' + _fmt_pf(s['variant_pf'])):>18s} "
              f"{s['affected_trades']:4d} {s['opportunity_loss_count']:9d} "
              f"{s['opportunity_loss_forgone']:+10,.2f} "
              f"{s['variant_max_dd_pct']-s['baseline_max_dd_pct']:+10.2f}pp")

    if args.dump_json:
        out = Path(args.dump_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"summaries": all_summaries, "trades": rows}, indent=2), encoding="utf-8")
        print(f"\n[saved] {out}", file=sys.stderr)
