#!/usr/bin/env python3
"""決算ブラックアウトの反実仮想分析（R18-B、読み取り専用）.

背景（2026-09-05、ギャップ分析より）:
現行システムには決算ブラックアウト（決算発表直前の新規エントリー禁止）が存在
しない（entry_filters.yaml は出来高/ADR/銘柄PFゲートのみ）。stop_loss合計
-$216k/147件のうち exit return <= -9% のギャップ貫通が多数あり、決算またぎが
原因の一部である疑いがある。本スクリプトは「エントリー日から次回決算まで
N日以内なら当該エントリーをブロックしていたら、実績はどう変わったか」を
一次近似で測定する。

決算日データ源:
  - 一次: data/r11_earnings_cache/<SYMBOL>.json（R11-Cが yfinance
    Ticker.earnings_dates から取得・キャッシュした過去+将来の決算日リスト。
    2026-09-05時点で closed トレード58銘柄すべてにファイルが存在）。
  - 空リストの銘柄はETF（決算なし）としてブラックアウト対象外に分類。
  - リポジトリ内のもう一つの決算データ源（R10で接続した finnhub
    calendar/earnings、data/raw/finnhub/finnhub_earnings_calendar_*.json）は
    取得開始が2026-08-07以降でエントリー期間（05-12〜）の過去日付カバレッジが
    不足するため、本検証では使用しない（クロスチェック用に存在のみ記録）。
  - **カバレッジ%（次回決算日が判定可能だったトレード比率）を必ず報告**。
    判定可能 = キャッシュ内にエントリー日以降の決算日が1つ以上存在すること。

ルール:
  - エントリー日（ET換算）から次回決算日まで N カレンダー日以内ならブロック。
    N ∈ {3, 5, 7}。
  - event_swing系トレード（strategy_id / original_strategy_id に 'event_swing'
    を含む）は「決算前に買う」設計のため対象から除外し、除外件数を報告する
    （0件でもその旨を明示）。

追加分析（直接効果の証拠）:
  - exit_reason=stop_loss かつ return_pct <= -9% のギャップ貫通トレードのうち、
    保有期間 [entry_date, exit_date] 内に決算日を含むものを直接カウント。

手法・限界:
  - 反実仮想は一次近似: ブロックされたトレードの実現PnLを丸ごと除去。
    資金再配分・複利は考慮しない。機会損失（ブロックした勝ち）を必ず表示。
  - コホート: 全期間 / exit >= 2026-07-16。
  - yfinance決算日には事後修正・重複（同日複数行）があり得る。品質注意を
    summary に明記する。

注意（多重検定）: 本分析は同一357件への反実仮想の重ね掛けの一つであり
探索的検証。昇格判断には R13-C 完了後の out-of-sample 再検証を要する。

出力: docs/r18b_earnings_blackout_validation_20260905/
  - full_run.txt（リダイレクト保存） / blackout_results.json

使い方:
  . venv/bin/activate
  python scripts/analyze_earnings_blackout_counterfactual.py \
      | tee docs/r18b_earnings_blackout_validation_20260905/full_run.txt
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PNL_STATE_PATH = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
EARNINGS_CACHE_DIR = PROJECT_ROOT / "data" / "r11_earnings_cache"
OUT_DIR = PROJECT_ROOT / "docs" / "r18b_earnings_blackout_validation_20260905"

BLACKOUT_WINDOWS = [3, 5, 7]
COHORT2_EXIT_START = "2026-07-16"
GAP_THROUGH_RETURN = -0.09
ET = ZoneInfo("America/New_York")


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def load_closed_trades() -> list[dict]:
    state = json.loads(PNL_STATE_PATH.read_text())
    closed = [t for t in state["trades"] if t.get("status") == "closed"]
    for t in closed:
        t["_entry_date"] = parse_ts(t["entry_time"]).astimezone(ET).date()
        t["_exit_dt"] = parse_ts(t["exit_time"])
        t["_exit_date"] = t["_exit_dt"].astimezone(ET).date()
    return closed


def load_earnings_cache(symbols: set[str]) -> tuple[dict[str, list[date]], list[str], list[str]]:
    """symbol -> sorted earnings dates。戻り値: (dates, ETF扱い銘柄, キャッシュ欠落銘柄)."""
    earnings: dict[str, list[date]] = {}
    etf_like: list[str] = []
    missing: list[str] = []
    for sym in sorted(symbols):
        p = EARNINGS_CACHE_DIR / f"{sym}.json"
        if not p.exists():
            missing.append(sym)
            continue
        raw = json.loads(p.read_text())
        if not raw:
            etf_like.append(sym)
            continue
        earnings[sym] = sorted({date.fromisoformat(d[:10]) for d in raw})
    return earnings, etf_like, missing


def next_earnings(earnings: dict[str, list[date]], symbol: str, on: date) -> date | None:
    dts = earnings.get(symbol)
    if not dts:
        return None
    for d in dts:
        if d >= on:
            return d
    return None


def pf(trades: list[dict]) -> float | None:
    gp = sum(t["pnl"] for t in trades if (t.get("pnl") or 0) > 0)
    gl = sum(-t["pnl"] for t in trades if (t.get("pnl") or 0) < 0)
    return None if gl == 0 else gp / gl


def fmt_pf(x) -> str:
    return "inf" if x is None else f"{x:.3f}"


def analyze_cohort(name: str, trades: list[dict], blocked_ids_by_n: dict[int, set]) -> dict:
    base_pnl = sum(t["pnl"] for t in trades)
    base_pf = pf(trades)
    print(f"\n{'=' * 78}\n■ コホート: {name}（n={len(trades)}, Net PnL ${base_pnl:,.0f}, PF {fmt_pf(base_pf)}）\n{'=' * 78}")
    header = f"{'N(日)':<8}{'ブロック':>6}{'勝ち':>5}{'負け':>5}{'勝ちPnL':>12}{'負けPnL':>12}{'PnL差':>12}{'PF前':>8}{'PF後':>8}"
    print(header)
    print("-" * len(header))
    results = {}
    for n in BLACKOUT_WINDOWS:
        blocked = [t for t in trades if t["trade_id"] in blocked_ids_by_n[n]]
        kept = [t for t in trades if t["trade_id"] not in blocked_ids_by_n[n]]
        bw = [t for t in blocked if t["pnl"] > 0]
        bl = [t for t in blocked if t["pnl"] < 0]
        bw_pnl = sum(t["pnl"] for t in bw)
        bl_pnl = sum(t["pnl"] for t in bl)
        delta = sum(t["pnl"] for t in kept) - base_pnl
        after_pf = pf(kept)
        print(f"N={n:<6}{len(blocked):>6}{len(bw):>5}{len(bl):>5}{bw_pnl:>12,.0f}{bl_pnl:>12,.0f}{delta:>+12,.0f}{fmt_pf(base_pf):>8}{fmt_pf(after_pf):>8}")
        results[n] = {
            "blocked": len(blocked),
            "blocked_wins": len(bw),
            "blocked_losses": len(bl),
            "blocked_win_pnl": round(bw_pnl, 2),
            "blocked_loss_pnl": round(bl_pnl, 2),
            "net_pnl_delta": round(delta, 2),
            "pf_before": None if base_pf is None else round(base_pf, 4),
            "pf_after": None if after_pf is None else round(after_pf, 4),
            "net_pnl_before": round(base_pnl, 2),
            "net_pnl_after": round(base_pnl + delta, 2),
        }
    return results


def main() -> int:
    print("R18-B: 決算ブラックアウト反実仮想分析（2026-09-05、読み取り専用）")
    print(f"実行時刻: {datetime.now(ET).isoformat()}")

    trades = load_closed_trades()
    print(f"\nclosedトレード: {len(trades)}件, Net PnL ${sum(t['pnl'] for t in trades):,.2f}, PF {fmt_pf(pf(trades))}")

    # event_swing系の除外
    def is_event_swing(t: dict) -> bool:
        sid = (t.get("strategy_id") or "") + "|" + (t.get("original_strategy_id") or "")
        return "event_swing" in sid

    event_swing = [t for t in trades if is_event_swing(t)]
    trades = [t for t in trades if not is_event_swing(t)]
    print(f"event_swing系の除外: {len(event_swing)}件（strategy_id/original_strategy_idで判別。0件=当該戦略のclosedトレードなし）")

    symbols = {t["symbol"] for t in trades}
    earnings, etf_like, missing = load_earnings_cache(symbols)
    print(f"\n決算日データ源: data/r11_earnings_cache（R11-C、yfinance Ticker.earnings_dates由来）")
    print(f"  銘柄数: {len(symbols)} / 決算日あり: {len(earnings)} / ETF等（決算なし・対象外）: {len(etf_like)} / キャッシュ欠落: {len(missing)}")
    if etf_like:
        print(f"  ETF等: {', '.join(etf_like)}")
    if missing:
        print(f"  ★キャッシュ欠落（要yfinanceフォールバック）: {', '.join(missing)}")

    # カバレッジ: 次回決算日が判定可能か（非ETFトレードのみが本来の対象）
    stock_trades = [t for t in trades if t["symbol"] in earnings or t["symbol"] in missing]
    etf_trades = [t for t in trades if t["symbol"] in etf_like]
    covered, uncovered = [], []
    for t in stock_trades:
        if next_earnings(earnings, t["symbol"], t["_entry_date"]) is not None:
            covered.append(t)
        else:
            uncovered.append(t)
    print(f"\nカバレッジ（次回決算日が判定できた比率）:")
    print(f"  個別株トレード: {len(covered)}/{len(stock_trades)} = {100 * len(covered) / max(1, len(stock_trades)):.1f}%")
    print(f"  ETFトレード（決算なし・ブラックアウト対象外）: {len(etf_trades)}件")
    total_determinable = len(covered) + len(etf_trades)
    print(f"  全体（ETF含む判定可能率）: {total_determinable}/{len(trades)} = {100 * total_determinable / len(trades):.1f}%")
    if uncovered:
        by_sym = defaultdict(int)
        for t in uncovered:
            by_sym[t["symbol"]] += 1
        print(f"  判定不能（entry以降の決算日がキャッシュに無い）: {dict(sorted(by_sym.items()))}")
        print("  → 判定不能トレードは『ブロックされない』側に置く（保守的: ブラックアウト効果を過小評価する方向）")

    # ブロック判定
    blocked_ids_by_n: dict[int, set] = {n: set() for n in BLACKOUT_WINDOWS}
    blocked_detail = []
    for t in covered:
        ne = next_earnings(earnings, t["symbol"], t["_entry_date"])
        days_to = (ne - t["_entry_date"]).days
        for n in BLACKOUT_WINDOWS:
            if days_to <= n:
                blocked_ids_by_n[n].add(t["trade_id"])
        if days_to <= max(BLACKOUT_WINDOWS):
            blocked_detail.append(
                {
                    "trade_id": t["trade_id"],
                    "symbol": t["symbol"],
                    "entry_date": t["_entry_date"].isoformat(),
                    "next_earnings": ne.isoformat(),
                    "days_to_earnings": days_to,
                    "pnl": t["pnl"],
                    "return_pct": t.get("return_pct"),
                    "exit_reason": t.get("exit_reason"),
                }
            )

    print(f"\nブロック対象トレード明細（N=7基準、days_to_earnings昇順）:")
    for b in sorted(blocked_detail, key=lambda x: (x["days_to_earnings"], x["symbol"])):
        print(f"  {b['entry_date']} {b['symbol']:<6} 決算まで{b['days_to_earnings']}日（{b['next_earnings']}） pnl ${b['pnl']:>+10,.0f}  {b['exit_reason']}")

    # コホート分析
    cohorts = {
        "全期間": trades,
        f"exit >= {COHORT2_EXIT_START}": [t for t in trades if t["_exit_date"].isoformat() >= COHORT2_EXIT_START],
    }
    all_results = {}
    for name, ct in cohorts.items():
        all_results[name] = analyze_cohort(name, ct, blocked_ids_by_n)

    # 追加分析: ギャップ貫通ストップ × 保有期間内決算
    gap_trades = [
        t for t in trades if t.get("exit_reason") == "stop_loss" and (t.get("return_pct") or 0) <= GAP_THROUGH_RETURN
    ]
    print(f"\n{'=' * 78}\n■ 追加分析: ギャップ貫通ストップ（stop_loss かつ return <= {GAP_THROUGH_RETURN:.0%}）× 決算またぎ\n{'=' * 78}")
    print(f"ギャップ貫通トレード: {len(gap_trades)}件, PnL合計 ${sum(t['pnl'] for t in gap_trades):,.0f}")
    with_earnings = []
    undeterminable = 0
    for t in gap_trades:
        dts = earnings.get(t["symbol"])
        if dts is None:
            if t["symbol"] not in etf_like:
                undeterminable += 1
            continue
        if not dts or dts[-1] < t["_entry_date"]:
            undeterminable += 1
            continue
        hit = [d for d in dts if t["_entry_date"] <= d <= t["_exit_date"]]
        if hit:
            with_earnings.append((t, hit[0]))
    print(f"うち保有期間 [entry_date, exit_date] 内に決算日を含む: {len(with_earnings)}件 "
          f"(PnL合計 ${sum(t['pnl'] for t, _ in with_earnings):,.0f}) / 判定不能: {undeterminable}件")
    for t, d in sorted(with_earnings, key=lambda x: x[0]["_entry_date"]):
        print(f"  {t['_entry_date']}→{t['_exit_date']} {t['symbol']:<6} 決算日{d} pnl ${t['pnl']:>+10,.0f} ret {t['return_pct']:.1%}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "blackout_results.json"
    out_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(ET).isoformat(),
                "n_closed": len(trades),
                "event_swing_excluded": len(event_swing),
                "coverage": {
                    "stock_trades": len(stock_trades),
                    "stock_trades_covered": len(covered),
                    "stock_coverage_pct": round(100 * len(covered) / max(1, len(stock_trades)), 1),
                    "etf_trades": len(etf_trades),
                    "overall_determinable_pct": round(100 * total_determinable / len(trades), 1),
                    "uncovered": len(uncovered),
                },
                "cohorts": all_results,
                "blocked_detail_n7": blocked_detail,
                "gap_through": {
                    "total": len(gap_trades),
                    "total_pnl": round(sum(t["pnl"] for t in gap_trades), 2),
                    "with_earnings_in_holding": len(with_earnings),
                    "with_earnings_pnl": round(sum(t["pnl"] for t, _ in with_earnings), 2),
                    "undeterminable": undeterminable,
                },
                "note": "一次近似（ブロックPnL除去のみ）。探索的検証であり昇格にはR13-C後のout-of-sample確認を要する。",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n結果JSONを保存: {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
