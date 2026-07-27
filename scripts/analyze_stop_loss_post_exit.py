"""
Stop Loss Post-Exit Drift Analysis
====================================
stop_loss 発火後に株価がどう動いたかを分析する。

評価軸:
  - Post-exit drift: exit 後 N 日間の価格変化
  - False stop rate: exit 後に entry_price まで回復したトレードの割合
  - Correct stop rate: exit 後もさらに下落し続けたトレードの割合
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yfinance as yf


# ── Load stop_loss trades ──────────────────────────────────────────────────

def load_stop_loss_trades():
    state_path = ROOT / "data" / "tracking" / "pnl_state.json"
    with open(state_path) as f:
        state = json.load(f)
    trades = state.get("trades", [])
    return [
        t for t in trades
        if t.get("status") == "closed" and t.get("exit_reason") == "stop_loss"
    ]


# ── Fetch post-exit prices via yfinance ──────────────────────────────────

def fetch_post_exit_prices(symbol: str, exit_date_str: str, days: int = 15) -> dict[str, float]:
    """exit_date の翌営業日から days 日分の終値を返す"""
    # exit_date_str は "2026-07-16T..." 形式
    exit_date = datetime.fromisoformat(exit_date_str.replace("Z", "+00:00"))
    start = exit_date.date() + timedelta(days=1)
    end = exit_date.date() + timedelta(days=days + 10)  # バッファ多め

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start.isoformat(), end=end.isoformat(), interval="1d")
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


# ── Analysis ──────────────────────────────────────────────────────────────

def analyze(trades: list[dict], lookforward_days: int = 10) -> dict:
    results = []
    no_data = []

    for t in trades:
        symbol = t.get("symbol", "?")
        exit_time = t.get("exit_time") or ""
        entry_price = t.get("entry_price") or 0
        exit_price = t.get("exit_price") or 0
        pnl = t.get("pnl") or 0
        ret_pct = (t.get("return_pct") or 0) * 100

        if not exit_time or exit_price == 0:
            no_data.append(symbol)
            continue

        prices = fetch_post_exit_prices(symbol, exit_time, days=lookforward_days + 5)
        if not prices:
            no_data.append(f"{symbol}(no data)")
            continue

        sorted_dates = sorted(prices.keys())
        post_prices = {d: prices[d] for d in sorted_dates[:lookforward_days]}
        if not post_prices:
            no_data.append(f"{symbol}(empty)")
            continue

        # 終値リスト
        price_list = list(post_prices.values())
        last_price = price_list[-1]
        min_price = min(price_list)
        max_price = max(price_list)

        # exit 後の変化率（exit_price 基準）
        post_drift = (last_price - exit_price) / exit_price * 100 if exit_price else 0
        post_min_drift = (min_price - exit_price) / exit_price * 100 if exit_price else 0
        post_max_drift = (max_price - exit_price) / exit_price * 100 if exit_price else 0

        # entry_price まで回復したか
        recovered_to_entry = any(p >= entry_price for p in price_list)

        # 止損後も下落が続いたか（exit_price より低値を更新したか）
        continued_down = min_price < exit_price

        result = {
            "symbol": symbol,
            "exit_date": exit_time[:10],
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "ret_pct": ret_pct,
            "post_min_drift_pct": post_min_drift,
            "post_max_drift_pct": post_max_drift,
            "post_last_drift_pct": post_drift,
            "recovered_to_entry": recovered_to_entry,
            "continued_down": continued_down,
            "last_price": last_price,
            "min_price": min_price,
            "max_price": max_price,
            "n_days": len(price_list),
        }
        results.append(result)

    return {"results": results, "no_data": no_data}


# ── Print report ─────────────────────────────────────────────────────────

def print_report(analysis: dict, lookforward_days: int):
    results = analysis["results"]
    no_data = analysis["no_data"]

    if not results:
        print("No results to report.")
        return

    # WR=0 → only real stop losses (negative PnL)
    real_stops = [r for r in results if r["pnl"] < 0]
    odd_wins = [r for r in results if r["pnl"] >= 0]

    print("=" * 70)
    print(f"Stop Loss Post-Exit Drift Analysis (lookforward: {lookforward_days} business days)")
    print("=" * 70)
    print()

    print(f"Total stop_loss trades: {len(results) + len(no_data)}")
    print(f"  Analyzed:    {len(results)}")
    print(f"  No data:     {len(no_data)}  → {no_data}")
    print(f"  Positive PnL (奇妙な勝ちトレード): {len(odd_wins)}")
    print(f"  Negative PnL (真の止損): {len(real_stops)}")
    print()

    # ── 奇妙な「勝ち stop_loss」の調査
    if odd_wins:
        print("─" * 70)
        print("⚠️  Positive-PnL stop_loss trades（帰属ラベル疑い）")
        print("─" * 70)
        for r in sorted(odd_wins, key=lambda x: -x["ret_pct"]):
            print(
                f"  {r['symbol']:8s} {r['exit_date']}  "
                f"entry=${r['entry_price']:7.2f} exit=${r['exit_price']:7.2f}  "
                f"ret={r['ret_pct']:+6.1f}%  pnl=${r['pnl']:+8.2f}"
            )
        print("  → これらは trailing_stop / corporate_action の誤帰属の可能性大")
        print()

    # ── 真の止損：post-exit drift
    print("─" * 70)
    print(f"真の止損（negative PnL）n={len(real_stops)}  Post-exit drift 分析")
    print("─" * 70)

    continued = [r for r in real_stops if r["continued_down"]]
    recovered = [r for r in real_stops if r["recovered_to_entry"]]
    neither = [r for r in real_stops if not r["continued_down"] and not r["recovered_to_entry"]]

    correct_stop_rate = len(continued) / len(real_stops) * 100 if real_stops else 0
    false_stop_rate = len(recovered) / len(real_stops) * 100 if real_stops else 0

    print(f"  正しい止損（exit後さらに下落）  : {len(continued):3d} / {len(real_stops)}  ({correct_stop_rate:.1f}%)")
    print(f"  誤発動（entry_price まで回復）    : {len(recovered):3d} / {len(real_stops)}  ({false_stop_rate:.1f}%)")
    print(f"  どちらでもない（横ばい）          : {len(neither):3d} / {len(real_stops)}")
    print()

    # 平均 post-exit drift
    avg_min = sum(r["post_min_drift_pct"] for r in real_stops) / len(real_stops)
    avg_max = sum(r["post_max_drift_pct"] for r in real_stops) / len(real_stops)
    avg_last = sum(r["post_last_drift_pct"] for r in real_stops) / len(real_stops)

    print(f"  平均 post-exit最安値ドリフト: {avg_min:+.2f}%")
    print(f"  平均 post-exit最高値ドリフト: {avg_max:+.2f}%")
    print(f"  平均 post-exit終値ドリフト  : {avg_last:+.2f}%")
    print()

    # 判定
    print("─" * 70)
    print("判定サマリー")
    print("─" * 70)
    if correct_stop_rate >= 70:
        verdict = "✅ 正常機能（正しい止損が主体）"
    elif correct_stop_rate >= 50:
        verdict = "⚠️ 部分機能（誤発動が一定数あり）"
    else:
        verdict = "❌ 誤発動過多（閾値・timing の見直しが必要）"

    print(f"  正しい止損率: {correct_stop_rate:.1f}%  →  {verdict}")
    print(f"  誤発動率    : {false_stop_rate:.1f}%")
    print()

    # ── 個別詳細
    print("─" * 70)
    print("個別詳細（真の止損のみ）")
    print(f"{'Symbol':8s} {'Exit':10s} {'ret%':>6s} {'PnL':>9s} | {'min_d%':>7s} {'max_d%':>7s} {'last_d%':>7s} | {'回収':5s} {'続落':5s}")
    print("-" * 70)
    for r in sorted(real_stops, key=lambda x: x["exit_date"]):
        rec = "✅" if r["recovered_to_entry"] else "  "
        cont = "↓" if r["continued_down"] else " "
        print(
            f"  {r['symbol']:8s} {r['exit_date']}  "
            f"{r['ret_pct']:+6.1f}%  ${r['pnl']:+9.2f} | "
            f"{r['post_min_drift_pct']:+7.2f}% {r['post_max_drift_pct']:+7.2f}% {r['post_last_drift_pct']:+7.2f}% | "
            f"{rec}  {cont}"
        )

    print()
    print("─" * 70)
    print("凡例: 回収=exit後にentry_priceまで回復（誤発動）  続落=exit後に最安値更新（正しい止損）")


# ── Entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stop loss post-exit drift analysis")
    parser.add_argument("--days", type=int, default=10, help="Lookforward days (default: 10)")
    parser.add_argument("--since", type=str, default=None, help="Only trades exited on/after YYYY-MM-DD")
    args = parser.parse_args()

    trades = load_stop_loss_trades()
    if args.since:
        trades = [t for t in trades if (t.get("exit_time") or "")[:10] >= args.since]
        print(f"Filtered to trades since {args.since}: {len(trades)} trades")

    print(f"Fetching post-exit price data for {len(trades)} stop_loss trades...")
    print("(This may take ~30-60 seconds)\n")

    analysis = analyze(trades, lookforward_days=args.days)
    print_report(analysis, args.days)
