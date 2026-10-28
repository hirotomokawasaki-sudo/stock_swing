"""
analyze_news_impact.py
======================
ニュース収集が取引判断・成績にどの程度寄与しうるか分析するスクリプト。

分析1: 閉済トレード × ニュース感情 相関
  - 各クローズトレードのエントリー時点前後のニュースを取得
  - キーワードベースの感情スコア（positive/negative/neutral）を算出
  - 感情スコア × トレード結果（勝/負、return_pct）の相関を確認

分析2: ニュースフィルター仮想シミュレーション
  - 「negative news があるとき buy をスキップ」した場合のPnL差を計算
  - 過去決定ファイル 678件 × ニュース紐付けで疑似評価

分析3: シンボル別 感情 vs 実績
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ---------------------------------------------------------------------------
# Keyword-based sentiment scorer
# ---------------------------------------------------------------------------
POSITIVE_KEYWORDS = [
    "surge", "rally", "beat", "record", "growth", "upgrade", "breakout",
    "gain", "rise", "strong", "bullish", "outperform", "buy", "boost",
    "partnership", "deal", "contract", "positive", "higher", "upside",
    "momentum", "earnings beat", "revenue beat", "raised guidance",
    "exceeded", "exceeded expectations", "wins", "secures",
]
NEGATIVE_KEYWORDS = [
    "decline", "fall", "miss", "downgrade", "loss", "bearish", "sell",
    "drop", "lower", "weak", "cut", "concern", "risk", "warning",
    "investigation", "lawsuit", "probe", "layoff", "slowdown", "guidance cut",
    "below expectations", "disappoints", "misses", "loses", "restructuring",
    "recall", "breach", "default", "bankruptcy",
]
STRONG_NEGATIVE = ["investigation", "lawsuit", "probe", "default", "bankruptcy", "breach"]
STRONG_POSITIVE = ["record", "partnership", "earnings beat", "raised guidance", "secures"]


def score_sentiment(headline: str, summary: str) -> dict:
    text = f"{headline} {summary}".lower()
    pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in text)
    neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text)
    strong_neg = sum(1 for kw in STRONG_NEGATIVE if kw in text)
    strong_pos = sum(1 for kw in STRONG_POSITIVE if kw in text)

    # Weight strong signals more
    score = (pos + strong_pos * 0.5) - (neg + strong_neg * 1.0)
    if score > 0.5:
        label = "positive"
    elif score < -0.5:
        label = "negative"
    else:
        label = "neutral"
    return {"score": score, "label": label, "pos": pos, "neg": neg,
            "strong_neg": strong_neg, "strong_pos": strong_pos}


# ---------------------------------------------------------------------------
# Load news articles, deduplicated by article id
# ---------------------------------------------------------------------------
def load_news_by_symbol(news_dir: Path, symbols: list[str]) -> dict[str, list[dict]]:
    """Load all news articles grouped by symbol, deduped by article id."""
    result: dict[str, list[dict]] = defaultdict(list)
    seen_ids: dict[str, set] = defaultdict(set)

    for sym in symbols:
        sym_lower = sym.lower()
        for f in sorted(news_dir.glob(f"finnhub_{sym_lower}_news_*.json")):
            try:
                data = json.loads(f.read_text())
                payload = data.get("payload", data)
                news_list = payload.get("news", payload) if isinstance(payload, dict) else payload
                if not isinstance(news_list, list):
                    continue
                for item in news_list:
                    aid = item.get("id")
                    if aid and aid in seen_ids[sym]:
                        continue
                    if aid:
                        seen_ids[sym].add(aid)
                    ts = item.get("datetime")
                    if ts:
                        item["_dt"] = datetime.fromtimestamp(ts, tz=timezone.utc)
                    result[sym].append(item)
            except Exception:
                pass
        result[sym].sort(key=lambda x: x.get("_dt", datetime.min.replace(tzinfo=timezone.utc)))

    return result


def find_news_around(articles: list[dict], target_dt: datetime,
                     before_hours: int = 24, after_hours: int = 2) -> list[dict]:
    """Return articles within [target - before_hours, target + after_hours]."""
    lo = target_dt - timedelta(hours=before_hours)
    hi = target_dt + timedelta(hours=after_hours)
    return [a for a in articles if lo <= a.get("_dt", target_dt) <= hi]


# ---------------------------------------------------------------------------
# Load closed trades
# ---------------------------------------------------------------------------
def load_closed_trades(project_root: Path) -> list[dict]:
    state_file = project_root / "data" / "tracking" / "pnl_state.json"
    data = json.loads(state_file.read_text())
    trades = data.get("trades", [])
    closed = [t for t in trades if t.get("status") == "closed"]
    for t in closed:
        for key in ("entry_time", "exit_time"):
            raw = t.get(key)
            if raw and isinstance(raw, str):
                try:
                    t[f"_{key}"] = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except Exception:
                    pass
    return closed


# ---------------------------------------------------------------------------
# Load paper_demo decisions
# ---------------------------------------------------------------------------
def load_decisions(project_root: Path) -> list[dict]:
    dec_dir = project_root / "data" / "decisions"
    decisions = []
    for f in sorted(dec_dir.glob("*.json"), reverse=True):
        try:
            d = json.loads(f.read_text())
            raw_ts = d.get("generated_at")
            if raw_ts:
                d["_dt"] = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            decisions.append(d)
        except Exception:
            pass
    return decisions


# ---------------------------------------------------------------------------
# Analysis 1: Closed trade outcome × news sentiment correlation
# ---------------------------------------------------------------------------
def analysis1_trade_news_correlation(trades: list[dict],
                                     news_by_sym: dict[str, list[dict]]) -> dict:
    results = []
    no_news_count = 0

    for trade in trades:
        symbol = trade.get("symbol", "")
        entry_dt = trade.get("_entry_time")
        if not entry_dt or symbol not in news_by_sym:
            no_news_count += 1
            continue

        articles = find_news_around(news_by_sym[symbol], entry_dt,
                                    before_hours=48, after_hours=2)
        if not articles:
            no_news_count += 1
            continue

        # Aggregate sentiment across all articles
        total_score = 0.0
        labels = []
        for a in articles:
            s = score_sentiment(a.get("headline", ""), a.get("summary", ""))
            total_score += s["score"]
            labels.append(s["label"])

        agg_label = "neutral"
        if total_score > 1.0:
            agg_label = "positive"
        elif total_score < -1.0:
            agg_label = "negative"

        results.append({
            "symbol": symbol,
            "entry_time": trade.get("entry_time"),
            "pnl": trade.get("pnl", 0),
            "return_pct": trade.get("return_pct", 0),
            "win": (trade.get("pnl", 0) or 0) > 0,
            "news_count": len(articles),
            "sentiment_score": round(total_score, 2),
            "sentiment_label": agg_label,
            "sentiment_breakdown": {
                "positive": labels.count("positive"),
                "neutral": labels.count("neutral"),
                "negative": labels.count("negative"),
            },
        })

    return {"trades_with_news": results, "trades_without_news": no_news_count}


# ---------------------------------------------------------------------------
# Analysis 2: News filter simulation on paper decisions
# ---------------------------------------------------------------------------
def analysis2_decision_filter_sim(decisions: list[dict],
                                   news_by_sym: dict[str, list[dict]]) -> dict:
    """Simulate: skip BUY when pre-decision news is negative."""
    buy_decisions = [d for d in decisions if d.get("action") == "buy"]
    no_news = 0
    results = []

    for dec in buy_decisions:
        symbol = dec.get("symbol", "")
        dt = dec.get("_dt")
        if not dt or symbol not in news_by_sym:
            no_news += 1
            continue

        articles = find_news_around(news_by_sym[symbol], dt,
                                    before_hours=24, after_hours=0)
        if not articles:
            no_news += 1
            continue

        total_score = 0.0
        for a in articles:
            s = score_sentiment(a.get("headline", ""), a.get("summary", ""))
            total_score += s["score"]

        label = "neutral"
        if total_score > 1.0:
            label = "positive"
        elif total_score < -1.0:
            label = "negative"

        results.append({
            "symbol": symbol,
            "dt": dt.isoformat(),
            "confidence": dec.get("confidence", 0),
            "signal_strength": dec.get("signal_strength", 0),
            "news_count": len(articles),
            "news_score": round(total_score, 2),
            "news_label": label,
            "would_skip": label == "negative",  # filter: skip when negative
        })

    kept = [r for r in results if not r["would_skip"]]
    skipped = [r for r in results if r["would_skip"]]

    return {
        "total_buy_decisions": len(buy_decisions),
        "with_news": len(results),
        "without_news": no_news,
        "would_skip": len(skipped),
        "would_keep": len(kept),
        "skip_rate_pct": round(len(skipped) / max(len(results), 1) * 100, 1),
        "avg_confidence_kept": round(
            sum(r["confidence"] for r in kept) / max(len(kept), 1), 3),
        "avg_confidence_skipped": round(
            sum(r["confidence"] for r in skipped) / max(len(skipped), 1), 3),
        "avg_signal_kept": round(
            sum(r["signal_strength"] for r in kept) / max(len(kept), 1), 3),
        "avg_signal_skipped": round(
            sum(r["signal_strength"] for r in skipped) / max(len(skipped), 1), 3),
        "skipped_symbols": sorted({r["symbol"] for r in skipped}),
        "details": results,
    }


# ---------------------------------------------------------------------------
# Analysis 3: Symbol-level sentiment vs trade outcomes
# ---------------------------------------------------------------------------
def analysis3_symbol_sentiment(trades_with_news: list[dict]) -> list[dict]:
    by_sym: dict[str, dict] = defaultdict(lambda: {
        "wins": 0, "losses": 0, "total_pnl": 0.0,
        "pos_news_wins": 0, "pos_news_losses": 0,
        "neg_news_wins": 0, "neg_news_losses": 0,
        "neu_news_wins": 0, "neu_news_losses": 0,
    })
    for t in trades_with_news:
        sym = t["symbol"]
        label = t["sentiment_label"]
        win = t["win"]
        by_sym[sym]["total_pnl"] += t["pnl"]
        if win:
            by_sym[sym]["wins"] += 1
            by_sym[sym][f"{label[:3]}_news_wins"] += 1
        else:
            by_sym[sym]["losses"] += 1
            by_sym[sym][f"{label[:3]}_news_losses"] += 1

    rows = []
    for sym, d in sorted(by_sym.items()):
        total = d["wins"] + d["losses"]
        rows.append({
            "symbol": sym,
            "trades": total,
            "win_rate": round(d["wins"] / max(total, 1) * 100, 1),
            "total_pnl": round(d["total_pnl"], 2),
            "pos_news": f"{d['pos_news_wins']}W/{d['pos_news_losses']}L",
            "neg_news": f"{d['neg_news_wins']}W/{d['neg_news_losses']}L",
            "neu_news": f"{d['neu_news_wins']}W/{d['neu_news_losses']}L",
        })
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("ニュースインパクト分析")
    print("=" * 60)

    news_dir = PROJECT_ROOT / "data" / "raw" / "finnhub"
    tracked = ["MRVL", "CIEN", "DELL", "RBRK", "PLTR", "NOW", "INTU", "NBIS"]

    print(f"\n[データロード] シンボル: {tracked}")
    news_by_sym = load_news_by_symbol(news_dir, tracked)
    for sym, arts in news_by_sym.items():
        print(f"  {sym}: {len(arts)} articles (deduped)")

    trades = load_closed_trades(PROJECT_ROOT)
    # Filter to tracked symbols only
    tracked_trades = [t for t in trades if t.get("symbol") in tracked]
    print(f"\n閉済トレード (追跡8銘柄): {len(tracked_trades)} / {len(trades)} 件")

    decisions = load_decisions(PROJECT_ROOT)
    print(f"決定ファイル: {len(decisions)} 件")

    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("分析1: 閉済トレード × ニュース感情 相関")
    print("=" * 60)
    r1 = analysis1_trade_news_correlation(tracked_trades, news_by_sym)
    twn = r1["trades_with_news"]
    print(f"ニュース紐付き: {len(twn)} 件 / ニュースなし: {r1['trades_without_news']} 件")

    if twn:
        by_label: dict[str, list] = defaultdict(list)
        for t in twn:
            by_label[t["sentiment_label"]].append(t)

        print(f"\n{'感情':10} {'件数':>5} {'勝率':>8} {'平均PnL':>10} {'平均return':>10}")
        print("-" * 50)
        for label in ["positive", "neutral", "negative"]:
            group = by_label.get(label, [])
            if not group:
                continue
            wins = sum(1 for t in group if t["win"])
            avg_pnl = sum(t["pnl"] for t in group) / len(group)
            avg_ret = sum(t["return_pct"] for t in group) / len(group)
            print(f"{label:10} {len(group):>5} {wins/len(group)*100:>7.1f}% "
                  f"{avg_pnl:>+10.2f} {avg_ret*100:>+9.2f}%")

        # Correlation coefficient (score vs return_pct)
        scores = [t["sentiment_score"] for t in twn]
        returns = [t["return_pct"] for t in twn]
        if len(scores) > 2:
            mean_s = sum(scores) / len(scores)
            mean_r = sum(returns) / len(returns)
            cov = sum((s - mean_s) * (r - mean_r) for s, r in zip(scores, returns))
            std_s = (sum((s - mean_s) ** 2 for s in scores) / len(scores)) ** 0.5
            std_r = (sum((r - mean_r) ** 2 for r in returns) / len(returns)) ** 0.5
            corr = cov / (std_s * std_r * len(scores)) if std_s * std_r > 0 else 0
            print(f"\nピアソン相関係数 (感情スコア vs return_pct): {corr:+.3f}")
            if abs(corr) > 0.3:
                print("  → 中程度以上の相関あり ✅")
            elif abs(corr) > 0.1:
                print("  → 弱い相関あり ⚠️")
            else:
                print("  → 相関なし ❌")

    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("分析2: ニュースフィルター仮想シミュレーション（paper_demo決定）")
    print("=" * 60)
    r2 = analysis2_decision_filter_sim(decisions, news_by_sym)
    print(f"Buy決定 合計: {r2['total_buy_decisions']} 件")
    print(f"  ニュース紐付き: {r2['with_news']} 件 / なし: {r2['without_news']} 件")
    print(f"\n  ▼ フィルター適用結果（negative newsでskip）")
    print(f"  スキップ: {r2['would_skip']} 件 ({r2['skip_rate_pct']}%)")
    print(f"  継続:     {r2['would_keep']} 件")
    print(f"\n  平均 confidence:")
    print(f"    継続側:   {r2['avg_confidence_kept']:.3f}")
    print(f"    スキップ: {r2['avg_confidence_skipped']:.3f}")
    print(f"  平均 signal_strength:")
    print(f"    継続側:   {r2['avg_signal_kept']:.3f}")
    print(f"    スキップ: {r2['avg_signal_skipped']:.3f}")
    if r2["skipped_symbols"]:
        print(f"  スキップ対象シンボル: {r2['skipped_symbols']}")

    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("分析3: シンボル別 感情 × 成績")
    print("=" * 60)
    r3 = analysis3_symbol_sentiment(twn)
    if r3:
        print(f"{'Symbol':8} {'取引':>5} {'勝率':>7} {'PnL':>10}  {'Pos':>10}  {'Neg':>10}  {'Neu':>10}")
        print("-" * 72)
        for row in r3:
            print(f"{row['symbol']:8} {row['trades']:>5} {row['win_rate']:>6.1f}%"
                  f" {row['total_pnl']:>+10.2f}  {row['pos_news']:>10}  "
                  f"{row['neg_news']:>10}  {row['neu_news']:>10}")

    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("データ制約・信頼性メモ")
    print("=" * 60)
    print(f"  - 閉済トレードのうち追跡8銘柄: {len(tracked_trades)} 件のみ（統計的検出力が低い）")
    print(f"  - ニュース感情はキーワードマッチング（LLM評価ではない）")
    print(f"  - paper_demo決定ファイルは未執行（live取引との結果対応なし）")
    print(f"  - シンボル数が8銘柄に限定（汎化には注意）")
    print(f"  - 感情スコアと取引タイミングの時間的整合は±48h以内で近似")


if __name__ == "__main__":
    main()
