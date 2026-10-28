"""Tiered min_hold v2 (offset_pct-based): full-history retrospective simulation.

Purpose
-------
2026-08-05 (commit not tracked here, see docs/daily_logs/2026-08-05.md)
re-enabled tiered_min_hold using an offset_pct design (relative to the
*effective*, conviction-adjusted stop threshold) instead of the broken v1
absolute-return design. The original 2026-07-27 simulation evidence
(+$41,054 improvement) was for v1 (absolute-return tiers) and has never
been re-run for v2. Since 08-05, only 3 live stop_loss trades have
accumulated (all from the same NBIS incident, effectively n=1 for review
purposes) -- nowhere near enough to validate v2 ahead of the 2026-08-19
mid-review.

This script closes that gap by re-running the same post-exit drift
methodology (scripts/analyze_stop_loss_post_exit.py) against **every**
historical stop_loss trade (not just the 3 since 08-05), but scoring exit
timing using the v2 offset_pct tier logic
(SimpleExitV2Strategy._effective_min_hold_days) instead of the old absolute
thresholds. This reuses actual entry_signal_strength (when available) to
resolve each trade's effective stop threshold the same way the live
strategy does (_resolve_thresholds), so the offset_pct tiering is applied
exactly as it would be in production.

Method
------
For each historical stop_loss trade:
  1. Resolve eff_stop_loss_pct from entry_signal_strength (same logic as
     _resolve_thresholds; broker_reconstructed / unknown-strength trades
     use the -5% low-conviction default, matching production behavior).
  2. Compute offset_pct = (actual_return_pct - eff_stop_loss_pct) * 100.
  3. Look up the v2 tier (from config/strategy/simple_exit_v2.yaml's
     tiered_min_hold_levels) this offset falls into, and thus what
     min_hold_days *would* have applied.
  4. If the trade's actual holding_days < that min_hold_days, tiered v2
     would have suppressed the stop and held the position longer -- fetch
     daily OHLC (yfinance) forward from the actual exit date to
     entry_date + min_hold_days, and evaluate what price the position
     would have exited at (still using the *same* effective stop_loss_pct,
     re-checked daily) once the extended min_hold window elapses.
  5. If actual holding_days >= min_hold_days already, tiered v2 would not
     have changed this trade's outcome at all (already reported "no
     change").

This is READ-ONLY / retrospective analysis. It does not change any live
config or code. Output is a console report only (no state mutation),
consistent with the existing analyze_stop_loss_post_exit.py /
analyze_breakeven_staged_floor.py scripts.

Caveats (same as prior yfinance-based scripts in this codebase):
  - Daily-close approximation, not intraday; may differ from actual system
    execution cadence/price source.
  - config values are read from the currently-live simple_exit_v2.yaml,
    not from whatever was configured at each historical trade's actual
    exit time (thresholds like stop_loss_pct=-0.07 have been stable since
    at least 2026-05-27 per MEMORY.md though).
"""

from __future__ import annotations

import json
import sys
import yaml
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yfinance as yf

HIGH_STRENGTH_THRESHOLD = 0.7  # matches SimpleExitV2Strategy.HIGH_STRENGTH_THRESHOLD
LOW_STRENGTH_THRESHOLD = 0.4   # matches SimpleExitV2Strategy.LOW_STRENGTH_THRESHOLD
STANDARD_STOP_LOSS_PCT = -0.07


def load_config():
    cfg_path = ROOT / "config" / "strategy" / "simple_exit_v2.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def resolve_eff_stop_loss_pct(entry_signal_strength: float | None) -> float:
    """Mirror SimpleExitV2Strategy._resolve_thresholds()'s stop-loss half."""
    if entry_signal_strength is None:
        return -0.05  # low-conviction default for unknown-provenance positions
    try:
        s = float(entry_signal_strength)
    except (TypeError, ValueError):
        return -0.05
    if s >= HIGH_STRENGTH_THRESHOLD:
        return -0.09
    if s < LOW_STRENGTH_THRESHOLD:
        return -0.05
    return STANDARD_STOP_LOSS_PCT


def resolve_v2_min_hold_days(
    return_pct: float, eff_stop_loss_pct: float, tiered_levels: list[dict]
) -> int:
    offset_pct = (return_pct - eff_stop_loss_pct) * 100.0
    sorted_levels = sorted(tiered_levels, key=lambda lv: -float(lv["offset_pct"]))
    for lv in sorted_levels:
        if offset_pct > float(lv["offset_pct"]):
            return int(lv["min_hold_days"])
    return 1  # base min_hold_days


def load_stop_loss_trades() -> list[dict]:
    state_path = ROOT / "data" / "tracking" / "pnl_state.json"
    with open(state_path) as f:
        state = json.load(f)
    trades = state.get("trades", [])
    return [
        t for t in trades
        if t.get("status") == "closed" and t.get("exit_reason") == "stop_loss"
    ]


def fetch_daily_closes(symbol: str, start_date, end_date) -> dict[str, float]:
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(
            start=start_date.isoformat(), end=end_date.isoformat(), interval="1d"
        )
        if hist.empty:
            return {}
        result = {}
        for idx, row in hist.iterrows():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            result[date_str] = float(row["Close"])
        return result
    except Exception as e:
        print(f"    [WARN] {symbol}: {e}", file=sys.stderr)
        return {}


def main():
    cfg = load_config()
    tiered_enabled = cfg.get("tiered_min_hold_enabled", False)
    tiered_levels = cfg.get("tiered_min_hold_levels", [])
    emergency_bypass_pct = cfg.get("emergency_stop_bypass_pct", -0.12)

    print("=" * 78)
    print("Tiered min_hold v2 (offset_pct) — Full-History Retrospective Simulation")
    print("=" * 78)
    print(f"tiered_min_hold_enabled (live config): {tiered_enabled}")
    print(f"tiered_min_hold_levels: {tiered_levels}")
    print(f"emergency_stop_bypass_pct: {emergency_bypass_pct}")
    print()

    trades = load_stop_loss_trades()
    print(f"Total historical stop_loss closed trades: {len(trades)}")
    print()

    n_no_data = 0
    n_unchanged = 0
    n_extended = 0
    total_actual_pnl = 0.0
    total_v2_pnl_for_extended = 0.0
    total_actual_pnl_for_extended = 0.0
    n_improved = 0
    n_worse = 0
    n_same = 0

    rows = []

    for t in trades:
        symbol = t.get("symbol", "?")
        entry_price = t.get("entry_price") or 0
        entry_time = t.get("entry_time") or ""
        exit_time = t.get("exit_time") or ""
        actual_pnl = t.get("pnl") or 0
        ret_pct = t.get("return_pct") or 0
        qty = t.get("qty") or 0
        strength = t.get("entry_signal_strength")
        holding_days = t.get("holding_days")

        total_actual_pnl += actual_pnl

        if not entry_time or not exit_time or entry_price == 0 or holding_days is None:
            n_no_data += 1
            continue

        eff_stop = resolve_eff_stop_loss_pct(strength)

        if ret_pct <= emergency_bypass_pct:
            # Emergency bypass always exits immediately regardless of tier -- no change.
            n_unchanged += 1
            rows.append((symbol, exit_time[:10], actual_pnl, "emergency_bypass", None))
            continue

        v2_min_hold = resolve_v2_min_hold_days(ret_pct, eff_stop, tiered_levels)

        if holding_days >= v2_min_hold:
            # Position was already held long enough; v2 tiering would not
            # have suppressed this exit at all.
            n_unchanged += 1
            rows.append((symbol, exit_time[:10], actual_pnl, "no_change", None))
            continue

        # v2 would have suppressed this stop -- simulate holding until
        # entry_date + v2_min_hold business-ish days (use calendar days +
        # buffer, then pick the close on/after the target date).
        entry_date = datetime.fromisoformat(entry_time.replace("Z", "+00:00")).date()
        target_date = entry_date + timedelta(days=int(v2_min_hold * 1.6) + 3)  # buffer for weekends
        fetch_end = target_date + timedelta(days=5)
        closes = fetch_daily_closes(symbol, entry_date, fetch_end)
        if not closes:
            n_no_data += 1
            rows.append((symbol, exit_time[:10], actual_pnl, "no_price_data", None))
            continue

        sorted_dates = sorted(closes.keys())
        # Find the trading day count from entry to reach v2_min_hold trading days.
        if len(sorted_dates) <= v2_min_hold:
            n_no_data += 1
            rows.append((symbol, exit_time[:10], actual_pnl, "insufficient_history", None))
            continue
        exit_date_str = sorted_dates[v2_min_hold]
        v2_exit_price = closes[exit_date_str]
        v2_ret_pct = (v2_exit_price - entry_price) / entry_price
        v2_pnl = v2_ret_pct * entry_price * qty

        n_extended += 1
        total_v2_pnl_for_extended += v2_pnl
        total_actual_pnl_for_extended += actual_pnl
        diff = v2_pnl - actual_pnl
        if diff > 1:
            n_improved += 1
        elif diff < -1:
            n_worse += 1
        else:
            n_same += 1
        rows.append((symbol, exit_time[:10], actual_pnl, f"extended_to_{exit_date_str}", v2_pnl))

    print(f"{'Symbol':8s} {'ActExit':10s} {'ActPnL':>10s} | {'Outcome':22s} {'V2PnL':>10s}")
    print("-" * 78)
    for symbol, exit_date, actual_pnl, outcome, v2_pnl in rows:
        v2_str = f"${v2_pnl:+9.2f}" if v2_pnl is not None else "n/a"
        print(f"{symbol:8s} {exit_date:10s} ${actual_pnl:+9.2f} | {outcome:22s} {v2_str:>10s}")

    print("-" * 78)
    print()
    print("=" * 78)
    print("サマリー")
    print("=" * 78)
    print(f"総 stop_loss トレード数: {len(trades)}")
    print(f"  データ不足でスキップ: {n_no_data}")
    print(f"  変化なし（既にmin_hold以上保有 or emergency bypass）: {n_unchanged}")
    print(f"  v2により保有延長がシミュレートされた: {n_extended}")
    print()
    if n_extended:
        print(f"延長シミュレート対象 {n_extended} 件のうち:")
        print(f"  改善（v2 PnL > 実績PnL）: {n_improved}件")
        print(f"  悪化（v2 PnL < 実績PnL）: {n_worse}件")
        print(f"  ほぼ同じ: {n_same}件")
        print()
        print(f"実績PnL合計（延長対象のみ）      : ${total_actual_pnl_for_extended:+,.2f}")
        print(f"v2シミュレーションPnL合計（延長対象のみ）: ${total_v2_pnl_for_extended:+,.2f}")
        diff_total = total_v2_pnl_for_extended - total_actual_pnl_for_extended
        print(f"見込み改善額（v2 - 実績、延長対象のみ）: ${diff_total:+,.2f}")
    print()
    print(f"全stop_lossトレード実績PnL合計（参考、全{len(trades)}件）: ${total_actual_pnl:+,.2f}")


if __name__ == "__main__":
    main()
