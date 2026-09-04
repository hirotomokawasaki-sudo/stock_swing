#!/usr/bin/env python3
"""セクター集中上限の反実仮想分析（読み取り専用）.

背景（2026-09-05、9/8レビュー判断材料）:
直近コホート（exit>=2026-08-14、n=45）の出血 -$24.8k は 8/14以降の新規半導体
エントリー（LRCX/INTC/FTXL/CHPX/AVGO/NVDA 計-$39.9k）に集中している。
現行の sector cap は PositionSizingPolicy の max_sector_exposure_pct=0.55
（equity比55%、サイズ縮小のみでブロックではない）。本スクリプトは
「エントリー時点でセクター露出が equity比 cap を超えるならそのエントリー自体を
ブロックしていたら、実績はどう変わったか」を一次近似で測定する。

セクター分類（優先順位）:
  1. config/reference/symbol_registry.yaml の `sector` フィールド（G6 canonical
     registry、R13-D SectorMomentumFeature と同じソース）。registry 内の
     `semis` キーは `semiconductor` に正規化する（position_sizing.py の
     SYMBOL_SECTORS が同概念を 'semis' キーで持つため表記揺れを吸収）。
  2. カバー外銘柄のみ FALLBACK_SECTORS（semiconductor / other_tech / etf /
     other の簡易静的マップ）。2026-09-05時点では取引58銘柄すべて registry で
     カバーされており fallback は未使用（実行時に coverage を表示）。

手法:
  - pnl_state.json の closed+open トレードから時系列ポートフォリオを再構成
    （notional = qty×entry_price、entry_time〜exit_time で保有。open は保有継続）。
  - equity は baseline_equity（$1M、2026-05-12起点）+ その時点までの実現PnL累積
    （動的）。セクター比率 = セクター保有notional（当該エントリー実行後）/ equity。
  - 反実仮想: cap ∈ {30%, 40%, 50%}。エントリーを時系列順に処理し、
    「実行後の同一セクター比率 > cap」となるエントリーをブロック
    （ブロックされたポジションは以後の露出計算から除外＝逐次シミュレーション）。
  - PnL は一次近似: ブロックされた closed トレードの実現PnLを丸ごと除去。
  - 補助分析: is_semiconductor_related フラグ（registry、n=33銘柄）を1グループ
    として同じ cap を適用した「半導体関連連結」ビュー（ETF+個別株を跨ぐ集中を
    直接測る。docs の「半導体集中」懸念と R5-v2 correlated cluster cap に対応）。

一次近似の限界（summary.md にも明記）:
  - ブロックで浮いた資金の再配分（他エントリーのサイズ増・別銘柄への振替）と
    複利効果は考慮しない。
  - ブロックは「勝ちも消す」: ブロックされたトレードの勝ち負け内訳を機会損失
    として必ず表示する。
  - 実運用の cap はサイズ縮小（部分約定）も可能だが、ここでは全量ブロックのみ。
  - entry_price×qty の名目値ベース（時価評価ではない）。保有中の含み損益は
    露出計算に反映されない。

読み取り専用: pnl_state.json / symbol_registry.yaml を読むのみ。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PNL_STATE_PATH = ROOT / "data" / "tracking" / "pnl_state.json"
REGISTRY_PATH = ROOT / "config" / "reference" / "symbol_registry.yaml"

CAPS = [0.30, 0.40, 0.50]
RECENT_COHORT_START = "2026-07-16"
SEMI_GROUP = "semiconductor_related(flag)"

# カバー外銘柄用の簡易静的マップ（2026-09-05作成）。
# 根拠: semiconductor = 明確な半導体設計/製造/装置/材料銘柄、
#       etf = 上場投信（registry の asset_class: etf 相当）、
#       other_tech = それ以外のテック銘柄、other = 非テック。
# 2026-09-05時点では全取引銘柄が registry でカバーされるため未使用のはずだが、
# 将来 registry 未登録の銘柄が pnl_state に現れた場合の fail-safe として保持。
FALLBACK_SECTORS: dict[str, str] = {
    # (例) "TXN": "semiconductor",  # アナログ半導体大手
    # (例) "XLK": "etf",            # テクノロジーセクターETF
}
FALLBACK_DEFAULT = "other"


def profit_factor(pnls: list[float]) -> float | None:
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    if gross_loss <= 0:
        return None
    return gross_win / gross_loss


def fmt_pf(pf: float | None) -> str:
    return f"{pf:.3f}" if pf is not None else "inf"


def load_data(pnl_path: Path, reg_path: Path):
    state = json.loads(pnl_path.read_text())
    reg = yaml.safe_load(reg_path.read_text())["symbols"]
    trades = [t for t in state["trades"] if t.get("status") in ("closed", "open")]
    trades.sort(key=lambda t: t["entry_time"])
    baseline_equity = float(state.get("baseline_equity") or 1_000_000.0)

    def sector_of(sym: str) -> str:
        entry = reg.get(sym)
        if entry and entry.get("sector"):
            s = entry["sector"]
            return "semiconductor" if s == "semis" else s
        return FALLBACK_SECTORS.get(sym, FALLBACK_DEFAULT)

    def semis_related(sym: str) -> bool:
        entry = reg.get(sym)
        if entry is not None:
            return bool(entry.get("is_semiconductor_related"))
        return sector_of(sym) == "semiconductor"

    uncovered = sorted(
        {t["symbol"] for t in trades if t["symbol"] not in reg or not reg[t["symbol"]].get("sector")}
    )
    return trades, baseline_equity, sector_of, semis_related, uncovered


def simulate_cap(
    trades: list[dict],
    baseline_equity: float,
    group_of,
    cap: float,
) -> tuple[list[dict], list[dict]]:
    """逐次シミュレーション。returns (blocked_trades, entry_snapshots)."""
    # イベント列: entry と exit を時刻順に処理（exit を同時刻なら先に処理）
    events: list[tuple[str, int, dict]] = []
    for t in trades:
        events.append((t["entry_time"], 1, t))
        if t.get("exit_time"):
            events.append((t["exit_time"], 0, t))
    events.sort(key=lambda e: (e[0], e[1]))  # exit(0) を entry(1) より先に

    held: dict[str, dict] = {}  # trade_id -> trade（ブロックされなかった保有中）
    blocked: list[dict] = []
    blocked_ids: set[str] = set()
    realized = 0.0
    snapshots: list[dict] = []
    for ts, kind, t in events:
        if kind == 0:  # exit
            if t["trade_id"] in blocked_ids:
                continue
            held.pop(t["trade_id"], None)
            realized += t["pnl"]
            continue
        # entry
        notional = t["qty"] * t["entry_price"]
        grp = group_of(t["symbol"])
        group_notional = sum(
            h["qty"] * h["entry_price"] for h in held.values() if group_of(h["symbol"]) == grp
        )
        equity = baseline_equity + realized
        ratio_after = (group_notional + notional) / equity
        snapshots.append(
            {
                "trade_id": t["trade_id"],
                "symbol": t["symbol"],
                "group": grp,
                "entry_time": ts,
                "ratio_after": round(ratio_after, 4),
            }
        )
        if grp is not None and ratio_after > cap:
            blocked.append(t)
            blocked_ids.add(t["trade_id"])
        else:
            held[t["trade_id"]] = t
    return blocked, snapshots


def report_cap_results(
    label: str,
    trades: list[dict],
    baseline_equity: float,
    group_of,
    results: dict,
) -> None:
    closed = [t for t in trades if t.get("status") == "closed"]
    cohorts = {
        "全期間": closed,
        f"exit>={RECENT_COHORT_START}": [
            t for t in closed if (t.get("exit_time") or "") >= RECENT_COHORT_START
        ],
    }
    print(f"\n===== グルーピング: {label} =====")
    out = {"grouping": label, "caps": []}
    for cap in CAPS:
        blocked, _ = simulate_cap(trades, baseline_equity, group_of, cap)
        blocked_closed = [t for t in blocked if t.get("status") == "closed"]
        blocked_open = [t for t in blocked if t.get("status") == "open"]
        cap_out = {"cap": cap, "cohorts": [], "blocked_open_n": len(blocked_open)}
        print(f"\n--- cap = {cap:.0%} (equity比) ---")
        if blocked_open:
            print(
                f"  （open中でブロック対象: {len(blocked_open)}件 "
                f"{[t['symbol'] for t in blocked_open]} — PnL未確定のため差分計算から除外）"
            )
        for cname, cohort in cohorts.items():
            cohort_ids = {t["trade_id"] for t in cohort}
            b = [t for t in blocked_closed if t["trade_id"] in cohort_ids]
            base_pnls = [t["pnl"] for t in cohort]
            cf_pnls = [t["pnl"] for t in cohort if t["trade_id"] not in {x["trade_id"] for x in b}]
            base_net, cf_net = sum(base_pnls), sum(cf_pnls)
            base_pf, cf_pf = profit_factor(base_pnls), profit_factor(cf_pnls)
            wins = [t for t in b if t["pnl"] > 0]
            losses = [t for t in b if t["pnl"] < 0]
            print(
                f"  [{cname}] n={len(cohort)} block={len(b)}件 "
                f"(勝ち{len(wins)}件 +${sum(t['pnl'] for t in wins):,.0f} / "
                f"負け{len(losses)}件 -${-sum(t['pnl'] for t in losses):,.0f}) "
                f"net差 {cf_net - base_net:+,.0f} "
                f"PF {fmt_pf(base_pf)}→{fmt_pf(cf_pf)}"
            )
            cap_out["cohorts"].append(
                {
                    "cohort": cname,
                    "n": len(cohort),
                    "blocked_n": len(b),
                    "blocked_wins_n": len(wins),
                    "blocked_wins_pnl": round(sum(t["pnl"] for t in wins), 2),
                    "blocked_losses_n": len(losses),
                    "blocked_losses_pnl": round(sum(t["pnl"] for t in losses), 2),
                    "baseline_net": round(base_net, 2),
                    "cf_net": round(cf_net, 2),
                    "net_diff": round(cf_net - base_net, 2),
                    "pf_before": base_pf,
                    "pf_after": cf_pf,
                    "blocked_trades": [
                        {
                            "trade_id": t["trade_id"],
                            "symbol": t["symbol"],
                            "pnl": t["pnl"],
                            "entry_time": t["entry_time"],
                            "exit_time": t.get("exit_time"),
                            "exit_reason": t.get("exit_reason"),
                        }
                        for t in sorted(b, key=lambda x: x["pnl"])
                    ],
                }
            )
        out["caps"].append(cap_out)
    results["groupings"].append(out)


def open_positions_snapshot(trades, baseline_equity, sector_of, semis_related, results):
    open_trades = [t for t in trades if t.get("status") == "open"]
    realized = sum(t["pnl"] for t in trades if t.get("status") == "closed")
    equity = baseline_equity + realized
    total = sum(t["qty"] * t["entry_price"] for t in open_trades)
    by_sector: dict[str, float] = defaultdict(float)
    semis_notional = 0.0
    print("\n===== 現在のオープンポジション セクター構成スナップショット =====")
    print(f"equity近似（baseline+実現累積）: ${equity:,.0f} / open notional合計: ${total:,.0f}")
    for t in open_trades:
        n = t["qty"] * t["entry_price"]
        sec = sector_of(t["symbol"])
        by_sector[sec] += n
        if semis_related(t["symbol"]):
            semis_notional += n
        print(
            f"  {t['symbol']:<6} {sec:<26} qty={t['qty']:>6} notional=${n:>10,.0f} "
            f"entry={t['entry_time'][:10]}"
        )
    snap = {"equity_approx": round(equity, 2), "total_open_notional": round(total, 2), "sectors": {}}
    print("  --- セクター別 ---")
    for sec, n in sorted(by_sector.items(), key=lambda x: -x[1]):
        print(
            f"  {sec:<28} ${n:>10,.0f}  equity比 {n/equity:.1%}  "
            f"ポートフォリオ比 {n/total:.1%}" if total else f"  {sec}: $0"
        )
        snap["sectors"][sec] = {
            "notional": round(n, 2),
            "pct_of_equity": round(n / equity, 4),
            "pct_of_portfolio": round(n / total, 4) if total else None,
        }
    print(
        f"  半導体関連（is_semiconductor_related連結）: ${semis_notional:,.0f} "
        f"equity比 {semis_notional/equity:.1%} / ポートフォリオ比 "
        f"{(semis_notional/total if total else 0):.1%}"
    )
    snap["semiconductor_related"] = {
        "notional": round(semis_notional, 2),
        "pct_of_equity": round(semis_notional / equity, 4),
        "pct_of_portfolio": round(semis_notional / total, 4) if total else None,
    }
    results["open_positions_snapshot"] = snap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pnl-state", type=Path, default=PNL_STATE_PATH)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--json", type=Path, help="詳細JSON保存先")
    args = parser.parse_args()

    trades, baseline_equity, sector_of, semis_related, uncovered = load_data(
        args.pnl_state, args.registry
    )
    n_closed = sum(1 for t in trades if t["status"] == "closed")
    n_open = len(trades) - n_closed
    print(f"対象トレード: closed {n_closed} / open {n_open}")
    print(f"registry sector カバレッジ: 未カバー銘柄 = {uncovered or 'なし（全銘柄カバー）'}")
    print(f"equity基準: baseline ${baseline_equity:,.0f}（2026-05-12起点）+ 実現PnL累積（動的）")

    results: dict = {"groupings": []}
    report_cap_results("registry sector（semis→semiconductor正規化）", trades, baseline_equity, sector_of, results)
    report_cap_results(
        SEMI_GROUP + " — is_semiconductor_related=True を1グループとして cap 適用",
        trades,
        baseline_equity,
        lambda s: SEMI_GROUP if semis_related(s) else None,  # None グループは cap 対象外
        results,
    )
    open_positions_snapshot(trades, baseline_equity, sector_of, semis_related, results)

    print(
        "\n注意: 一次近似（ブロックで浮いた資金の再配分・複利は無視、名目値ベース）。"
        "ブロックは勝ちトレードも消す — 各行の勝ち負け内訳を機会損失として参照のこと。"
    )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"JSON保存: {args.json}")


if __name__ == "__main__":
    main()
