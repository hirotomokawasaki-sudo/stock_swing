"""
Breakeven Stop: Staged Floor Simulation
=========================================

Post-exit drift analysis for breakeven_stop 発火トレードに対し、現行ルール
（peak_return>=activation_pct 到達後、return<=0%で即exit）と、Trailing Stop
と同じ発想の「段階的floor」（peakからの利益を一定割合だけ保持するfloorに
段階的に引き上げる）を daily OHLC で forward-simulate し、見込み効果を測定する。

現行ルール（simple_exit_v2_strategy.py 実装）:
  peak_return_pct >= breakeven_activation_pct (現在 5%) に到達した後、
  return_pct <= 0% で即座に exit（floor = 0% 固定）。

段階的floor案（今回シミュレーション対象）:
  peak_return_pct が上がるほど floor を引き上げる（Trailing Stopの
  staged_trailing と同じ設計思想）。例:
    peak +5% 到達  → floor = 0%   （現行と同じ、まだ保護なし）
    peak +8% 到達  → floor = +3%  （利益の一部を確保）
    peak +12% 到達 → floor = +6%  （さらに確保）
  floor は「一度上がったら下がらない」（ratchet）。

シミュレーション方法:
  各トレードについて entry_time〜exit_time+buffer の日次終値を取得し、
  日次ベースで peak_price を更新しながら、
    (a) 現行ルール: 到達済みfloorに基づき exit 判定
    (b) 段階的floorルール: 上記の staged floor で exit 判定
  をそれぞれ独立にシミュレートし、実際に確定したexit日/価格と比較。
  段階的floorの方が「同じ日以降に、より高い価格で」exitできた場合、その差分を
  改善額として集計する。

注意: 日次終値ベースの近似であり、実際のシステムは日中の複数回チェック・
別の価格ソースを使う場合がある。よってここでの数値は「方向性の参考値」で
あり、精緻なバックテストの代替ではない。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yfinance as yf

# Current rule params (from config/strategy/simple_exit_v2.yaml)
# IMPORTANT: breakeven_activation_pct was changed from 3% -> 5% on 2026-07-29
# (commit 0ae1ce6). Most of the 43 historical breakeven_stop trades analyzed
# here exited BEFORE that date, so they were actually governed by the OLD
# 3% activation, not today's 5%. Using "today's" value for historical trades
# would silently distort the comparison (fewer/later activations than what
# actually happened), so we select the activation_pct that was in effect at
# each trade's exit date.
ACTIVATION_PCT_CHANGE_DATE = "2026-07-29"
ACTIVATION_PCT_BEFORE = 0.03
ACTIVATION_PCT_AFTER = 0.05
CURRENT_FLOOR_PCT = 0.0        # fixed 0% once activated (unchanged across the config change)

# Staged floor proposal (mirrors Trailing Stop's staged design).
# The first level intentionally matches whichever activation_pct was in
# effect for that trade (so the staged rule is a strict improvement/superset
# of the current rule, never a regression at the entry level).
def _staged_levels_for(activation_pct: float) -> list[tuple[float, float]]:
    return [
        (activation_pct, 0.0),        # same activation as current rule -> floor 0%
        (activation_pct + 0.03, 0.03),  # +3pp further -> floor +3%
        (activation_pct + 0.07, 0.06),  # +7pp further -> floor +6%
    ]


def _activation_pct_for_date(exit_date_str: str) -> float:
    return ACTIVATION_PCT_BEFORE if exit_date_str < ACTIVATION_PCT_CHANGE_DATE else ACTIVATION_PCT_AFTER


def load_breakeven_trades() -> list[dict]:
    state_path = ROOT / "data" / "tracking" / "pnl_state.json"
    with open(state_path) as f:
        state = json.load(f)
    trades = state.get("trades", [])
    return [
        t for t in trades
        if t.get("status") == "closed" and t.get("exit_reason") == "breakeven_stop"
    ]


def fetch_daily_ohlc(symbol: str, entry_date_str: str, exit_date_str: str,
                      buffer_days: int = 10) -> dict[str, tuple[float, float, float]]:
    """entry_date から exit_date+buffer までの日次 (High, Low, Close)。

    終値のみでは日中の値動き（peak到達やfloor割れ）を見逃す可能性が高いため、
    High/Lowも使って日中の極値を近似する。
    """
    entry_date = datetime.fromisoformat(entry_date_str.replace("Z", "+00:00")).date()
    exit_date = datetime.fromisoformat(exit_date_str.replace("Z", "+00:00")).date()
    start = entry_date
    end = exit_date + timedelta(days=buffer_days + 5)
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start.isoformat(), end=end.isoformat(), interval="1d")
        if hist.empty:
            return {}
        result = {}
        for idx, row in hist.iterrows():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            result[date_str] = (float(row["High"]), float(row["Low"]), float(row["Close"]))
        return result
    except Exception as e:
        print(f"    [WARN] {symbol}: {e}", file=sys.stderr)
        return {}


def resolve_staged_floor(peak_return_pct: float, staged_levels: list[tuple[float, float]]) -> float | None:
    """Return the highest activated floor for the given peak_return_pct, or None if not yet activated."""
    floor = None
    for activation_pct, floor_pct in staged_levels:
        if peak_return_pct >= activation_pct:
            floor = floor_pct
    return floor


def resolve_current_floor(peak_return_pct: float, activation_pct: float) -> float | None:
    if peak_return_pct >= activation_pct:
        return CURRENT_FLOOR_PCT
    return None


def simulate_trade(entry_price: float, ohlc_series: list[tuple[str, float, float, float]],
                    activation_pct: float) -> dict:
    """Simulate both rules day-by-day over the given OHLC series.

    ohlc_series: sorted list of (date_str, high, low, close), starting from entry date.
    Within each day, peak_price is updated using the day's High (intraday peak
    approximation), and exit is checked using both the day's Low (worst-case
    intraday floor breach) and the day's Close (end-of-day check, matching how
    paper_demo actually evaluates exits once per run). We report the Close-based
    exit as the primary (conservative, matches actual system cadence) result,
    and note the Low-based (intraday) result separately for context.

    Returns dict with simulated exit info for both rules (close-based).
    """
    peak_price = entry_price
    current_exit = None
    staged_exit = None

    for date_str, high, low, close in ohlc_series:
        # Update peak using the day's high (intraday peak, conservative for
        # "how much upside did this trade actually see").
        if high > peak_price:
            peak_price = high
        peak_return_pct = (peak_price - entry_price) / entry_price

        # End-of-day (close) check — matches actual system cadence (checked
        # once per scheduled run, using latest close/quote).
        close_return_pct = (close - entry_price) / entry_price

        if current_exit is None:
            floor = resolve_current_floor(peak_return_pct, activation_pct)
            if floor is not None and close_return_pct <= floor:
                current_exit = (date_str, close, close_return_pct)

        if staged_exit is None:
            floor = resolve_staged_floor(peak_return_pct, _staged_levels_for(activation_pct))
            if floor is not None and close_return_pct <= floor:
                staged_exit = (date_str, close, close_return_pct)

        if current_exit is not None and staged_exit is not None:
            break

    return {
        "current_exit": current_exit,
        "staged_exit": staged_exit,
        "peak_price_reached": peak_price,
    }


def main():
    trades = load_breakeven_trades()
    print(f"Total breakeven_stop closed trades: {len(trades)}")
    print("Fetching daily price history for simulation (this may take 1-2 minutes)...\n")

    results = []
    no_data = []

    for t in trades:
        symbol = t.get("symbol", "?")
        entry_price = t.get("entry_price") or 0
        entry_time = t.get("entry_time") or ""
        exit_time = t.get("exit_time") or ""
        actual_pnl = t.get("pnl") or 0
        actual_ret = (t.get("return_pct") or 0) * 100
        qty = t.get("qty") or 0

        if not entry_time or not exit_time or entry_price == 0:
            no_data.append(symbol)
            continue

        ohlc = fetch_daily_ohlc(symbol, entry_time, exit_time)
        if not ohlc:
            no_data.append(f"{symbol}(no data)")
            continue

        sorted_series = [(d, h, l, c) for d, (h, l, c) in sorted(ohlc.items())]
        activation_pct = _activation_pct_for_date(exit_time[:10])
        sim = simulate_trade(entry_price, sorted_series, activation_pct)

        result = {
            "symbol": symbol,
            "entry_date": entry_time[:10],
            "exit_date": exit_time[:10],
            "entry_price": entry_price,
            "actual_exit_price": t.get("exit_price"),
            "actual_pnl": actual_pnl,
            "actual_ret_pct": actual_ret,
            "qty": qty,
            "activation_pct": activation_pct,
            **sim,
        }
        results.append(result)

    print_report(results, no_data)


def print_report(results: list[dict], no_data: list[str]):
    print("=" * 78)
    print("Breakeven Stop: Staged Floor Simulation Report")
    print("=" * 78)
    print()
    print(f"Analyzed: {len(results)}  No data: {len(no_data)} -> {no_data}")
    print()

    total_actual_pnl = 0.0
    total_current_sim_pnl = 0.0
    total_staged_sim_pnl = 0.0
    n_staged_better = 0
    n_staged_worse = 0
    n_staged_same = 0
    n_current_never_fired = 0
    n_staged_never_fired = 0

    print(f"{'Symbol':8s} {'Exit':10s} {'qty':>6s} {'ActPnL':>10s} | "
          f"{'CurExit':10s} {'CurRet%':>8s} {'CurPnL':>10s} | "
          f"{'StgExit':10s} {'StgRet%':>8s} {'StgPnL':>10s} | {'Diff$':>9s}")
    print("-" * 110)

    for r in results:
        qty = r["qty"]
        entry_price = r["entry_price"]

        cur = r["current_exit"]
        stg = r["staged_exit"]

        cur_pnl = (cur[2] * entry_price * qty) if cur else None
        stg_pnl = (stg[2] * entry_price * qty) if stg else None

        if cur_pnl is None:
            n_current_never_fired += 1
        if stg_pnl is None:
            n_staged_never_fired += 1

        # For aggregation, use actual pnl as fallback when a rule never fired
        # within the observed window (treat as "still holding", exclude from
        # PnL diff aggregation to avoid bias, but log it).
        total_actual_pnl += r["actual_pnl"]
        if cur_pnl is not None:
            total_current_sim_pnl += cur_pnl
        if stg_pnl is not None:
            total_staged_sim_pnl += stg_pnl

        if cur_pnl is not None and stg_pnl is not None:
            diff = stg_pnl - cur_pnl
            if diff > 1:
                n_staged_better += 1
            elif diff < -1:
                n_staged_worse += 1
            else:
                n_staged_same += 1
        else:
            diff = None

        cur_str = f"{cur[0]} {cur[2]*100:+6.2f}% ${cur_pnl:+8.2f}" if cur else "NEVER FIRED"
        stg_str = f"{stg[0]} {stg[2]*100:+6.2f}% ${stg_pnl:+8.2f}" if stg else "NEVER FIRED"
        diff_str = f"${diff:+8.2f}" if diff is not None else "n/a"

        print(f"{r['symbol']:8s} {r['exit_date']:10s} {qty:6.0f} ${r['actual_pnl']:+9.2f} | {cur_str:32s} | {stg_str:32s} | {diff_str:>9s}")

    print("-" * 110)
    print()
    print("=" * 78)
    print("サマリー")
    print("=" * 78)
    n = len(results)
    print(f"総トレード数: {n}")
    print(f"  現行ルール: 観測期間内に発火せず（保有継続扱い）: {n_current_never_fired}件")
    print(f"  段階floor : 観測期間内に発火せず（保有継続扱い）: {n_staged_never_fired}件")
    print()
    print(f"両ルールとも発火したトレードの比較（{n - n_current_never_fired - n_staged_never_fired}件超の重複あり）:")
    print(f"  段階floorの方が有利: {n_staged_better}件")
    print(f"  段階floorの方が不利: {n_staged_worse}件")
    print(f"  ほぼ同じ:           {n_staged_same}件")
    print()
    print(f"実績PnL合計（現行、参考）        : ${total_actual_pnl:+,.2f}")
    print(f"シミュレーション PnL合計（現行ルール, 発火分のみ）  : ${total_current_sim_pnl:+,.2f}")
    print(f"シミュレーション PnL合計（段階floor, 発火分のみ）    : ${total_staged_sim_pnl:+,.2f}")
    diff_total = total_staged_sim_pnl - total_current_sim_pnl
    print(f"見込み改善額（段階floor - 現行シミュレーション）: ${diff_total:+,.2f}")


if __name__ == "__main__":
    main()
