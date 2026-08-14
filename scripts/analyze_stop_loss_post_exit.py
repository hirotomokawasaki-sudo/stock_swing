"""
Stop Loss Post-Exit Drift Analysis
====================================
stop_loss 発火後に株価がどう動いたかを分析する。

評価軸（2026-08-14 改訂: 「役割純化」方針 — stop_loss は短期損失限定戦術であり、
長期資産防衛はポートフォリオガードレールに委ねる。docs/daily_logs/2026-08-14.md
「Stop Loss 再設計」節参照）:
  - 【主指標】Counterfactual cost/benefit: stop_loss しなかった場合
    （lookforward_days 保有した場合）との PnL 差分。これが stop_loss の
    実際の経済的価値を測る唯一の意味のある指標。
  - 【補助指標】Post-exit drift: exit 後 N 日間の価格変化
  - 【補助指標・非推奨】False stop rate / Correct stop rate: 「事後に下落したか」
    だけを見る指標。高ボラティリティ銘柄では統計的にほぼ常に「正しい止損」に
    分類されてしまうため、単独では stop_loss の良し悪しを判断する根拠にならない
    （docs/stop_loss_evaluation_guidelines.md も参照）。cost/benefit と併読する。

2026-08-14 変更点:
  - qty を trade レコードから直接読み込み、反実仮想 PnL（counterfactual PnL）を計算
  - --counterfactual フラグで反実仮想サマリーセクションを追加出力
  - 判定サマリーの主指標を「正しい止損率」→「正味コスト/ベネフィット」に変更
    （正しい止損率は補助指標として引き続き表示するが、主判定には使わない）
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


# ── Counterfactual PnL ──────────────────────────────────────────────────────

def compute_counterfactual_pnl(
    entry_price: float,
    exit_price: float,
    actual_pnl: float,
    last_price: float,
) -> dict[str, float] | None:
    """Return counterfactual metrics for "what if we had held instead of
    stopping out", derived from the trade's own entry/exit/pnl (qty is
    implicit in the entry->exit price move vs actual_pnl, so this does not
    require qty to be passed in separately -- but callers should prefer
    passing qty explicitly when available, see compute_counterfactual_pnl_with_qty).

    Returns None if qty cannot be derived (entry_price == exit_price).
    """
    price_move = exit_price - entry_price
    if price_move == 0:
        return None
    qty = actual_pnl / price_move
    return compute_counterfactual_pnl_with_qty(entry_price, actual_pnl, last_price, qty)


def compute_counterfactual_pnl_with_qty(
    entry_price: float,
    actual_pnl: float,
    last_price: float,
    qty: float,
) -> dict[str, float]:
    """Return {"counterfactual_pnl", "diff", "would_have_been_better"} for a
    single trade, given an explicit qty.

    diff = actual_pnl - counterfactual_pnl:
        diff > 0  → stopping out was better than holding (stop_loss saved money)
        diff < 0  → holding would have been better (stop_loss cost money)
    """
    counterfactual_pnl = qty * (last_price - entry_price)
    diff = actual_pnl - counterfactual_pnl
    return {
        "counterfactual_pnl": counterfactual_pnl,
        "diff": diff,
        "would_have_been_better_to_hold": diff < 0,
    }


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
        qty = t.get("qty")
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

        # 反実仮想 PnL（qty がレコードにあればそれを使う。なければ price move から逆算）
        if qty:
            cf = compute_counterfactual_pnl_with_qty(entry_price, pnl, last_price, float(qty))
        else:
            cf = compute_counterfactual_pnl(entry_price, exit_price, pnl, last_price)

        result = {
            "symbol": symbol,
            "exit_date": exit_time[:10],
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "qty": qty,
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
            "counterfactual_pnl": cf["counterfactual_pnl"] if cf else None,
            "counterfactual_diff": cf["diff"] if cf else None,
        }
        results.append(result)

    return {"results": results, "no_data": no_data}


# ── Print report ─────────────────────────────────────────────────────────

def print_report(analysis: dict, lookforward_days: int, show_counterfactual: bool = False):
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

    # ── 【主指標】Counterfactual cost/benefit ──────────────────────────────
    if show_counterfactual:
        print_counterfactual_summary(real_stops, lookforward_days)

    # ── 真の止損：post-exit drift（補助指標）
    print("─" * 70)
    print(f"真の止損（negative PnL）n={len(real_stops)}  Post-exit drift 分析（補助指標）")
    print("─" * 70)

    continued = [r for r in real_stops if r["continued_down"]]
    recovered = [r for r in real_stops if r["recovered_to_entry"]]
    neither = [r for r in real_stops if not r["continued_down"] and not r["recovered_to_entry"]]

    correct_stop_rate = len(continued) / len(real_stops) * 100 if real_stops else 0
    false_stop_rate = len(recovered) / len(real_stops) * 100 if real_stops else 0

    print(f"  正しい止損（exit後さらに下落）  : {len(continued):3d} / {len(real_stops)}  ({correct_stop_rate:.1f}%)")
    print(f"  誤発動（entry_price まで回復）    : {len(recovered):3d} / {len(real_stops)}  ({false_stop_rate:.1f}%)")
    print(f"  どちらでもない（横ばい）          : {len(neither):3d} / {len(real_stops)}")
    print(f"  ⚠️  この指標は補助情報。高ボラ銘柄では統計的にほぼ常に「正しい止損」")
    print(f"      判定になりうるため、単独で stop_loss の良し悪しを判断しないこと。")
    print(f"      主判定は上記 Counterfactual cost/benefit（--counterfactual）を使う。")
    print()

    # 平均 post-exit drift
    avg_min = sum(r["post_min_drift_pct"] for r in real_stops) / len(real_stops)
    avg_max = sum(r["post_max_drift_pct"] for r in real_stops) / len(real_stops)
    avg_last = sum(r["post_last_drift_pct"] for r in real_stops) / len(real_stops)

    print(f"  平均 post-exit最安値ドリフト: {avg_min:+.2f}%")
    print(f"  平均 post-exit最高値ドリフト: {avg_max:+.2f}%")
    print(f"  平均 post-exit終値ドリフト  : {avg_last:+.2f}%")
    print()

    # 判定（2026-08-14: 主指標を正しい止損率からcounterfactual cost/benefitに変更）
    print("─" * 70)
    print("判定サマリー")
    print("─" * 70)
    if show_counterfactual:
        cf_results = [r for r in real_stops if r["counterfactual_diff"] is not None]
        if cf_results:
            net_diff = sum(r["counterfactual_diff"] for r in cf_results)
            if net_diff > 0:
                verdict = "✅ stop_loss が正味で価値を生んでいる（実損失 < 保有した場合の損失）"
            else:
                verdict = "❌ stop_loss が正味でコストになっている（実損失 > 保有した場合の損失）"
            print(f"  正味 cost/benefit（主指標）: ${net_diff:+,.2f}  →  {verdict}")
        print(f"  正しい止損率（補助指標）    : {correct_stop_rate:.1f}%")
    else:
        print(f"  正しい止損率（補助指標のみ、主判定には使わないこと）: {correct_stop_rate:.1f}%")
        print(f"  主指標（counterfactual cost/benefit）を見るには --counterfactual を指定してください")
    print()

    # ── 個別詳細
    print("─" * 70)
    header = f"個別詳細（真の止損のみ）"
    print(header)
    if show_counterfactual:
        print(f"{'Symbol':8s} {'Exit':10s} {'ret%':>6s} {'PnL':>9s} {'CF_PnL':>9s} {'Diff':>9s} | {'min_d%':>7s} {'max_d%':>7s} {'last_d%':>7s} | {'回収':5s} {'続落':5s}")
    else:
        print(f"{'Symbol':8s} {'Exit':10s} {'ret%':>6s} {'PnL':>9s} | {'min_d%':>7s} {'max_d%':>7s} {'last_d%':>7s} | {'回収':5s} {'続落':5s}")
    print("-" * 70)
    for r in sorted(real_stops, key=lambda x: x["exit_date"]):
        rec = "✅" if r["recovered_to_entry"] else "  "
        cont = "↓" if r["continued_down"] else " "
        if show_counterfactual and r["counterfactual_pnl"] is not None:
            print(
                f"  {r['symbol']:8s} {r['exit_date']}  "
                f"{r['ret_pct']:+6.1f}%  ${r['pnl']:+9.2f} ${r['counterfactual_pnl']:+9.2f} ${r['counterfactual_diff']:+9.2f} | "
                f"{r['post_min_drift_pct']:+7.2f}% {r['post_max_drift_pct']:+7.2f}% {r['post_last_drift_pct']:+7.2f}% | "
                f"{rec}  {cont}"
            )
        else:
            print(
                f"  {r['symbol']:8s} {r['exit_date']}  "
                f"{r['ret_pct']:+6.1f}%  ${r['pnl']:+9.2f} | "
                f"{r['post_min_drift_pct']:+7.2f}% {r['post_max_drift_pct']:+7.2f}% {r['post_last_drift_pct']:+7.2f}% | "
                f"{rec}  {cont}"
            )

    print()
    print("─" * 70)
    print("凡例: 回収=exit後にentry_priceまで回復（誤発動）  続落=exit後に最安値更新（正しい止損）")
    if show_counterfactual:
        print("      CF_PnL=stop_lossせず lookforward_days 保有した場合の想定PnL")
        print("      Diff=実PnL - CF_PnL（正なら stop_loss が得、負なら保有の方が得だった）")


def print_counterfactual_summary(real_stops: list[dict], lookforward_days: int) -> None:
    """Print the primary cost/benefit verdict section (2026-08-14 主指標)."""
    cf_results = [r for r in real_stops if r["counterfactual_diff"] is not None]
    print("─" * 70)
    print(f"【主指標】Counterfactual Cost/Benefit（stop_lossせず{lookforward_days}営業日保有した場合との比較）")
    print("─" * 70)

    if not cf_results:
        print("  (qty が取得できずcounterfactual計算不可のトレードのみでした)")
        print()
        return

    total_actual = sum(r["pnl"] for r in cf_results)
    total_cf = sum(r["counterfactual_pnl"] for r in cf_results)
    net_diff = total_actual - total_cf

    better_to_stop = [r for r in cf_results if r["counterfactual_diff"] > 0]
    better_to_hold = [r for r in cf_results if r["counterfactual_diff"] < 0]

    print(f"  実損失合計（stop_loss実行）        : ${total_actual:,.2f}")
    print(f"  反実仮想合計（保有し続けた場合）    : ${total_cf:,.2f}")
    print(f"  正味差分（実損失 - 反実仮想）      : ${net_diff:+,.2f}")
    print(f"    (正なら stop_loss が正味で得、負なら保有の方が正味で得だった)")
    print()
    print(f"  stop_lossした方が良かった件数      : {len(better_to_stop):3d} / {len(cf_results)}")
    print(f"  保有した方が良かった件数            : {len(better_to_hold):3d} / {len(cf_results)}")
    print()

    if better_to_hold:
        worst = sorted(better_to_hold, key=lambda x: x["counterfactual_diff"])[:5]
        print("  保有した方が良かった上位5件（stop_lossのコストが大きかった順）:")
        for r in worst:
            print(
                f"    {r['symbol']:8s} {r['exit_date']}  "
                f"実損失=${r['pnl']:+9.2f}  反実仮想=${r['counterfactual_pnl']:+9.2f}  "
                f"差={r['counterfactual_diff']:+9.2f}"
            )
    print()


# ── Entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stop loss post-exit drift analysis")
    parser.add_argument("--days", type=int, default=10, help="Lookforward days (default: 10)")
    parser.add_argument("--since", type=str, default=None, help="Only trades exited on/after YYYY-MM-DD")
    parser.add_argument(
        "--counterfactual", action="store_true",
        help="Show counterfactual cost/benefit summary (primary metric, 2026-08-14)",
    )
    args = parser.parse_args()

    trades = load_stop_loss_trades()
    if args.since:
        trades = [t for t in trades if (t.get("exit_time") or "")[:10] >= args.since]
        print(f"Filtered to trades since {args.since}: {len(trades)} trades")

    print(f"Fetching post-exit price data for {len(trades)} stop_loss trades...")
    print("(This may take ~30-60 seconds)\n")

    analysis = analyze(trades, lookforward_days=args.days)
    print_report(analysis, args.days, show_counterfactual=args.counterfactual)
