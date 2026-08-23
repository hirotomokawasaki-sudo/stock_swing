"""R13-A (2026-08-23): Daily-path historical validation of stop_loss threshold
deepening (-5/-7/-9% conviction tiers -> -8/-10/-12%).

Background (docs/console_improvement_tasks.md R13-A): attributable-only exit
attribution shows trailing_stop (n=36) at WR=72.2%/PF=11.85/net=+$35,687 vs
stop_loss (n=11) at WR=0%/PF=0.0/net=-$24,638 -- a stark asymmetry on real
trade data. Hypothesis: deepening the stop_loss conviction-tier thresholds
lets more positions survive early noise long enough to reach the
much-better-performing trailing_stop exit, at the cost of larger losses on
positions that were headed for a true breakdown anyway.

Methodology (mirrors scripts/simulate_daily_path_volatility_stop.py's
2026-08-14 daily-path replay design, which itself was built specifically to
fix two structural gaps in an earlier, coarser stop_loss simulation):
  1. Exit priority order is respected: trailing_stop -> breakeven_stop ->
     stop_loss -> time_based, replayed day-by-day using
     SimpleExitV2Strategy's own methods (not a reimplementation), so a
     deepened stop threshold that lets a position survive longer can still
     get caught by trailing_stop/breakeven_stop/time_based instead of
     "just holding to the end" -- exactly the kind of interaction a
     single-condition simulation would miss.
  2. ALL closed trades are replayed (not just the ones that already fired
     stop_loss), so a deepened threshold's risk of creating NEW large
     losses among previously-fine (non-stop_loss) trades is directly
     measurable, not assumed away.

Both baseline and deepened variants use the CURRENT production config
(volatility_adjusted_stop_enabled=True, staged_trailing, staged_breakeven,
tiered_min_hold -- config/strategy/simple_exit_v2.yaml as of 2026-08-23),
so the volatility-multiplier machinery is applied identically to both sides
and the measured PnL difference isolates ONLY the effect of deepening the
conviction-tier stop_loss base thresholds by -3 percentage points
(-5/-7/-9% -> -8/-10/-12%), not a re-litigation of the already-validated
volatility adjustment itself.

Approximation caveats (same as simulate_daily_path_volatility_stop.py):
  - ATR% is computed once per trade at entry_time and held constant.
  - universe_avg_atr_pct is approximated from trades entered within +/-3
    calendar days of this trade's entry.
  - Daily bars only (no intraday).
  - This is a read-only research script. It does not modify
    config/strategy/simple_exit_v2.yaml or any production state.

Usage:
    python scripts/simulate_stop_loss_deepening.py [--deepen-pp -3.0]
        [--since 2026-08-05] [--extra-days 30]
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

# ── Current production config (config/strategy/simple_exit_v2.yaml, 2026-08-23) ──
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
    # 2026-08-23 update: volatility_adjusted_stop_enabled is now live in
    # production (was still under review as of the 2026-08-14 script).
    # Applied identically to baseline and deepened variants below so it
    # does not confound the deepening-specific comparison.
    volatility_adjusted_stop_enabled=True,
    volatility_multiplier_min=0.5,
    volatility_multiplier_max=1.75,
)


class DeepenedStopSimpleExitV2Strategy(SimpleExitV2Strategy):
    """SimpleExitV2Strategy variant with conviction-tier stop_loss base
    thresholds shifted deeper by a fixed percentage-point delta.

    Reuses the parent's full tier-selection/graduation logic unchanged by
    calling super()._resolve_thresholds(..., volatility_multiplier=1.0) to
    obtain the RAW tier-selected base stop (unaffected either way by a 1.0
    multiplier, regardless of self.volatility_adjusted_stop_enabled), then
    applies the deepening delta, then applies the REAL volatility_multiplier
    via the parent's own _apply_volatility_multiplier() choke point. This
    avoids duplicating the tier-selection/graduation branching logic here.
    """

    def __init__(self, deepen_delta_pct: float, **kwargs):
        super().__init__(**kwargs)
        self._deepen_delta_pct = deepen_delta_pct

    def _resolve_thresholds(
        self,
        entry_signal_strength: float | None,
        hold_days: float | None = None,
        volatility_multiplier: float = 1.0,
    ) -> tuple[float, float]:
        base_stop, trailing_pct = super()._resolve_thresholds(
            entry_signal_strength, hold_days, volatility_multiplier=1.0
        )
        deepened_stop = base_stop + self._deepen_delta_pct
        return self._apply_volatility_multiplier(deepened_stop, volatility_multiplier), trailing_pct


# AUDIT CONTEXT (2026-08-23): R13-A's motivating asymmetry (trailing_stop
# WR=72.2%/PF=11.85 vs stop_loss WR=0%/PF=0.0) was found specifically in the
# ATTRIBUTABLE cohort (49 trades with real decision provenance -- see
# PnLTracker.get_attribution_quality_breakdown()), not the full 252-trade
# blended population which is dominated (203/252) by untracked-origin
# ("broker_reconstructed"/"reconciled_from_broker") trades with no signal
# provenance. Support --attributable-only so this simulation can be run on
# the SAME population where the original asymmetry was observed, not just
# the full blended set.
_UNTRACKED_ORIGIN_IDS = {"broker_reconstructed", "reconciled_from_broker"}


def load_all_closed_trades(since: str | None = None, attributable_only: bool = False) -> list[dict]:
    state_path = ROOT / "data" / "tracking" / "pnl_state.json"
    with open(state_path) as f:
        state = json.load(f)
    trades = [t for t in state.get("trades", []) if t.get("status") == "closed"]
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
    """Replay SimpleExitV2Strategy's priority-ordered exit logic day-by-day.
    Identical in structure to simulate_daily_path_volatility_stop.py's
    replay_exit() -- kept as a separate copy (not imported) so this script
    stays self-contained and its own logic is fully visible/auditable
    without cross-referencing another file's internals.
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
    deepen_delta_pct: float,
    atr_window: int = 14,
    extra_days_beyond_actual_exit: int = 30,
) -> list[dict]:
    strat_baseline = SimpleExitV2Strategy(**PROD_CONFIG)
    strat_deepened = DeepenedStopSimpleExitV2Strategy(deepen_delta_pct=deepen_delta_pct, **PROD_CONFIG)

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

        baseline_result = replay_exit(strat_baseline, entry_price, entry_signal_strength, daily_path, volatility_multiplier)
        deepened_result = replay_exit(strat_deepened, entry_price, entry_signal_strength, daily_path, volatility_multiplier)

        def _pnl(exit_price):
            if exit_price is None:
                return None
            return qty * (exit_price - entry_price)

        baseline_pnl = _pnl(baseline_result["exit_price"])
        deepened_pnl = _pnl(deepened_result["exit_price"])

        results.append({
            "symbol": t["symbol"],
            "entry_date": entry_date,
            "actual_exit_date": exit_date,
            "actual_exit_reason": t.get("exit_reason"),
            "actual_pnl": t.get("pnl"),
            "same_day_entry_exit": entry_date == exit_date,
            "volatility_multiplier": round(volatility_multiplier, 3),
            "baseline_exit_reason": baseline_result["exit_reason"],
            "baseline_exit_date": baseline_result["exit_date"],
            "baseline_hold_days": baseline_result["hold_days"],
            "baseline_pnl": baseline_pnl,
            "deepened_exit_reason": deepened_result["exit_reason"],
            "deepened_exit_date": deepened_result["exit_date"],
            "deepened_hold_days": deepened_result["hold_days"],
            "deepened_pnl": deepened_pnl,
            "pnl_diff": (deepened_pnl - baseline_pnl) if (deepened_pnl is not None and baseline_pnl is not None) else None,
            "reason_changed": baseline_result["exit_reason"] != deepened_result["exit_reason"],
        })

    return results


def _max_drawdown_of_path(pnls_in_order: list[float], baseline_equity: float) -> float:
    """Max drawdown (fraction) of the cumulative-PnL-on-baseline-equity path."""
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
    """Conditional Value at Risk: average of the worst alpha-fraction of
    trade outcomes (a simple per-trade CVaR proxy, not a full portfolio-level
    VaR/CVaR -- adequate for an A/B comparison of the same trade set under
    two exit-rule variants)."""
    if not pnls:
        return None
    sorted_pnls = sorted(pnls)
    n_tail = max(1, int(len(sorted_pnls) * alpha))
    tail = sorted_pnls[:n_tail]
    return sum(tail) / len(tail)


def print_report(results: list[dict], deepen_delta_pct: float, baseline_equity: float = 1_000_000.0) -> None:
    print("=" * 90)
    print("R13-A: Daily-Path Historical Validation — Stop Loss Threshold Deepening")
    print(f"Deepening delta: {deepen_delta_pct*100:+.1f}pp on all conviction tiers "
          f"(-5/-7/-9% -> {(-0.05+deepen_delta_pct)*100:.0f}/{(-0.07+deepen_delta_pct)*100:.0f}/{(-0.09+deepen_delta_pct)*100:.0f}%)")
    print("=" * 90)
    print()
    print(f"Total trades simulated: {len(results)}")

    same_day = [r for r in results if r["same_day_entry_exit"]]
    print(f"  Same-day entry/exit (excluded -- no data point exists to replay from "
          f"until the day AFTER entry): {len(same_day)}")

    with_pnl = [r for r in results if r["pnl_diff"] is not None and not r["same_day_entry_exit"]]
    print(f"With comparable PnL (excl. same-day): {len(with_pnl)}")
    print()

    comparable = [r for r in results if not r["same_day_entry_exit"]]
    reason_match = sum(1 for r in comparable if r["baseline_exit_reason"] == r["actual_exit_reason"])
    print(f"[Sanity check] baseline replay exit_reason matches actual production: "
          f"{reason_match}/{len(comparable)} ({reason_match/len(comparable)*100:.0f}% if comparable else n/a)"
          if comparable else "[Sanity check] no comparable trades")
    print("  (Daily-close-only replay vs. live intraday/broker fills -- mismatches expected;")
    print("   this check confirms the replay is in the right ballpark, not a perfect match.)")
    print()

    changed = [r for r in with_pnl if r["reason_changed"]]
    print(f"Trades where exit reason changed (baseline vs deepened): {len(changed)}/{len(with_pnl)}")
    print()

    total_baseline = sum(r["baseline_pnl"] for r in with_pnl)
    total_deepened = sum(r["deepened_pnl"] for r in with_pnl)
    net_diff = total_deepened - total_baseline

    print("─" * 90)
    print("AGGREGATE RESULT (primary metric: net PnL over replayed paths)")
    print("─" * 90)
    print(f"  Baseline (current production stop thresholds) total PnL: ${total_baseline:,.2f}")
    print(f"  Deepened stop thresholds total PnL:                      ${total_deepened:,.2f}")
    print(f"  Net diff (deepened - baseline):                          ${net_diff:+,.2f}")
    print(f"    (positive = deepening would have been NET BETTER)")
    print()

    improved = [r for r in with_pnl if r["pnl_diff"] > 0]
    worsened = [r for r in with_pnl if r["pnl_diff"] < 0]
    unchanged = [r for r in with_pnl if r["pnl_diff"] == 0]
    print(f"  Trades improved:  {len(improved):3d}  (sum ${sum(r['pnl_diff'] for r in improved):+,.2f})")
    print(f"  Trades worsened:  {len(worsened):3d}  (sum ${sum(r['pnl_diff'] for r in worsened):+,.2f})")
    print(f"  Trades unchanged: {len(unchanged):3d}")
    print()

    print("─" * 90)
    print("RISK METRICS (secondary, per R13-A required evaluation: net PnL alone is not sufficient)")
    print("─" * 90)
    baseline_pnls_ordered = [r["baseline_pnl"] for r in sorted(with_pnl, key=lambda x: x["baseline_exit_date"] or "")]
    deepened_pnls_ordered = [r["deepened_pnl"] for r in sorted(with_pnl, key=lambda x: x["deepened_exit_date"] or "")]
    baseline_dd = _max_drawdown_of_path(baseline_pnls_ordered, baseline_equity)
    deepened_dd = _max_drawdown_of_path(deepened_pnls_ordered, baseline_equity)
    baseline_cvar = _cvar([r["baseline_pnl"] for r in with_pnl])
    deepened_cvar = _cvar([r["deepened_pnl"] for r in with_pnl])
    print(f"  Max drawdown on replayed path (baseline equity ${baseline_equity:,.0f}):")
    print(f"    Baseline: {baseline_dd*100:.2f}%   Deepened: {deepened_dd*100:.2f}%   "
          f"Delta: {(deepened_dd-baseline_dd)*100:+.2f}pp")
    print(f"  CVaR (avg of worst 10% of trade outcomes):")
    print(f"    Baseline: ${baseline_cvar:+,.2f}   Deepened: ${deepened_cvar:+,.2f}   "
          f"Delta: ${(deepened_cvar-baseline_cvar):+,.2f}" if baseline_cvar is not None and deepened_cvar is not None else "  n/a")
    print()

    # Critical check: did the deepened threshold create NEW severe losses
    # among trades that were previously fine (non-stop_loss) in the baseline?
    newly_severe_losses = [
        r for r in with_pnl
        if r["baseline_exit_reason"] != "stop_loss"
        and r["deepened_exit_reason"] != "stop_loss"  # not even caught by a later stop_loss
        and r["pnl_diff"] < -1000  # arbitrary but explicit "material regression" bar
    ]
    print("─" * 90)
    print(f"[KEY RISK CHECK] Previously-non-stop_loss trades with >$1,000 WORSE outcome "
          f"under deepening (neither variant classified as stop_loss): {len(newly_severe_losses)}")
    print("─" * 90)
    if newly_severe_losses:
        for r in sorted(newly_severe_losses, key=lambda x: x["pnl_diff"])[:10]:
            print(
                f"    {r['symbol']:8s} {r['entry_date']}  actual_reason={r['actual_exit_reason']:14s} "
                f"baseline=${r['baseline_pnl']:+9.2f}({r['baseline_exit_reason']}, hold={r['baseline_hold_days']}d)  "
                f"deepened=${r['deepened_pnl']:+9.2f}({r['deepened_exit_reason']}, hold={r['deepened_hold_days']}d)  "
                f"diff=${r['pnl_diff']:+9.2f}"
            )
    else:
        print("  None found -- deepening did not create new material losses among trades")
        print("  that avoided stop_loss classification in both variants.")
    print()

    print("─" * 90)
    print("Top 10 biggest improvements (deepened threshold let a position survive to a better exit)")
    print("─" * 90)
    for r in sorted(with_pnl, key=lambda x: -x["pnl_diff"])[:10]:
        print(
            f"    {r['symbol']:8s} {r['entry_date']}  "
            f"baseline=${r['baseline_pnl']:+9.2f}({r['baseline_exit_reason']})  "
            f"deepened=${r['deepened_pnl']:+9.2f}({r['deepened_exit_reason']})  diff=${r['pnl_diff']:+9.2f}"
        )
    print()
    print("─" * 90)
    print("Top 10 biggest regressions (deepening made things worse)")
    print("─" * 90)
    for r in sorted(with_pnl, key=lambda x: x["pnl_diff"])[:10]:
        print(
            f"    {r['symbol']:8s} {r['entry_date']}  "
            f"baseline=${r['baseline_pnl']:+9.2f}({r['baseline_exit_reason']})  "
            f"deepened=${r['deepened_pnl']:+9.2f}({r['deepened_exit_reason']})  diff=${r['pnl_diff']:+9.2f}"
        )
    print()

    print("─" * 90)
    print("VERDICT")
    print("─" * 90)
    dd_worse = (deepened_dd - baseline_dd) > 0.005  # >0.5pp worse DD treated as material
    # AUDIT FIX (self-caught during R13-A validation, 2026-08-23): comparing
    # CVaR (denominated in thousands of dollars) against a fixed $1.00
    # absolute threshold made this check trigger on noise-level differences
    # (e.g. a $22 CVaR change on a ~$4,100 base flagged as "material" on the
    # first run of this script). Use a relative threshold instead: CVaR must
    # worsen by more than 5% of its own baseline magnitude to count as material.
    cvar_worse = (
        baseline_cvar is not None and deepened_cvar is not None and baseline_cvar != 0
        and deepened_cvar < baseline_cvar * 1.05  # more negative by >5% of baseline magnitude
    )
    if net_diff > 0 and not dd_worse and not cvar_worse:
        print("  ✅ Net PnL improved AND no material DD/CVaR regression -> supports proceeding to paper A/B.")
    elif net_diff > 0 and (dd_worse or cvar_worse):
        print("  ⚠️  Net PnL improved BUT DD and/or CVaR worsened materially -> proceed to paper A/B")
        print("      only with explicit acknowledgement of the higher tail risk; consider a smaller")
        print("      deepening delta as an alternative.")
    else:
        print("  ❌ Net PnL did not improve -> do not proceed to paper A/B with this delta as-is;")
        print("      reconsider the deepening magnitude or abandon this direction.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="R13-A: daily-path historical validation of stop_loss threshold deepening")
    parser.add_argument("--deepen-pp", type=float, default=-3.0,
                         help="Percentage-point shift applied to all conviction-tier stop thresholds "
                              "(default -3.0: -5/-7/-9%% -> -8/-10/-12%%)")
    parser.add_argument("--since", type=str, default=None, help="Only trades exited on/after YYYY-MM-DD")
    parser.add_argument("--extra-days", type=int, default=30,
                         help="Extra days of price data to fetch beyond the actual exit date")
    parser.add_argument("--atr-window", type=int, default=14)
    parser.add_argument("--attributable-only", action="store_true",
                         help="Restrict to attributable-cohort trades (real decision provenance) -- "
                              "the same population where R13-A's motivating trailing_stop/stop_loss "
                              "asymmetry was observed, excluding broker_reconstructed/reconciled_from_broker")
    args = parser.parse_args()

    trades = load_all_closed_trades(since=args.since, attributable_only=args.attributable_only)
    print(f"Loaded {len(trades)} closed trades" +
          (f" (since {args.since})" if args.since else "") +
          (" (attributable-only)" if args.attributable_only else "") +
          ". Running daily-path replay (this will take a few minutes)...\n")

    results = simulate_all_trades(
        trades,
        deepen_delta_pct=args.deepen_pp / 100.0,
        atr_window=args.atr_window,
        extra_days_beyond_actual_exit=args.extra_days,
    )
    print_report(results, deepen_delta_pct=args.deepen_pp / 100.0)
