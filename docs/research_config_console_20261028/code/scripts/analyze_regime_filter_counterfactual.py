#!/usr/bin/env python3
"""市場レジームフィルタの反実仮想分析（R18-A、読み取り専用）.

背景（2026-09-05、ギャップ分析より）:
現行システムにはエントリー時の市場レジームフィルタが存在しない
（market_regime はレポート表示のみで常時 unknown）。paper実績は
月次で 5月-22k / 6月+87k / 7月-86k / 8月-22k とレジーム依存の疑いが強い。
本スクリプトは「エントリー時点で市場がリスクオフなら当該エントリーを
ブロックしていたら、実績はどう変わったか」を一次近似で測定する。

レジーム定義バリアント（エントリー日の**前営業日close**で判定 = look-ahead回避）:
  (a) SPY < 50日SMA
  (b) SPY < 200日SMA
  (c) VIX > 20
  (d) VIX > 25
  (e) 複合: SPY < 50日SMA または VIX > 25

データ:
  - yfinance で SPY / ^VIX 日足を取得。指標ウォームアップ（200日SMA）のため
    ダウンロード開始は 2025-06-01（レジーム判定に使うのは 2026-04-01 以降のみ。
    タスク指定の「2026-04-01〜現在」はエントリー判定対象期間であり、
    SMA計算には過去200営業日が必要なため取得期間のみ延長）。
  - 判定日付はエントリー時刻（UTC）を US/Eastern に変換した日付を使用し、
    その日付より**厳密に前**の最終取引日のclose/SMA/VIXで判定する。

手法:
  - data/tracking/pnl_state.json の closed トレード全件が対象。
  - 反実仮想は一次近似: ブロックされたトレードの実現PnLを丸ごと除去。
    資金再配分・複利・「ブロックで浮いた枠での別エントリー」は考慮しない。
  - ブロックは勝ちトレードも消すため、機会損失（ブロックされた勝ち件数・
    勝ちPnL）を必ず表示する。
  - コホート: 全期間 / exit >= 2026-07-16。
  - 月別ブロック分布: ブロックされたトレードのPnLを exit月・entry月の両方で
    集計（「7月の出血をどれだけ避けられたか」を直接確認するため）。

注意（多重検定）: 本分析は同一357件への反実仮想の重ね掛けの一つであり
探索的検証。昇格判断には R13-C 完了後の out-of-sample 再検証を要する。

出力: docs/r18a_regime_filter_validation_20260905/
  - summary生成用の生出力（full_run.txt はリダイレクトで保存）
  - regime_results.json（機械可読な結果）

使い方:
  . venv/bin/activate
  python scripts/analyze_regime_filter_counterfactual.py \
      | tee docs/r18a_regime_filter_validation_20260905/full_run.txt
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PNL_STATE_PATH = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
OUT_DIR = PROJECT_ROOT / "docs" / "r18a_regime_filter_validation_20260905"

DOWNLOAD_START = "2025-06-01"  # 200日SMAウォームアップ用
REGIME_EVAL_START = "2026-04-01"  # タスク指定の判定対象期間の開始
COHORT2_EXIT_START = "2026-07-16"
ET = ZoneInfo("America/New_York")


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def load_closed_trades() -> list[dict]:
    state = json.loads(PNL_STATE_PATH.read_text())
    closed = [t for t in state["trades"] if t.get("status") == "closed"]
    for t in closed:
        t["_entry_dt"] = parse_ts(t["entry_time"])
        t["_exit_dt"] = parse_ts(t["exit_time"])
        t["_entry_date_et"] = t["_entry_dt"].astimezone(ET).date()
    return closed


def fetch_market_data():
    import pandas as pd
    import yfinance as yf

    end = (datetime.now(ET).date() + timedelta(days=1)).isoformat()
    spy = yf.download("SPY", start=DOWNLOAD_START, end=end, progress=False, auto_adjust=False)
    vix = yf.download("^VIX", start=DOWNLOAD_START, end=end, progress=False, auto_adjust=False)
    if spy.empty or vix.empty:
        raise RuntimeError("yfinance download failed (SPY or ^VIX empty)")

    def close_series(df):
        c = df["Close"]
        if hasattr(c, "columns"):  # MultiIndex column
            c = c.iloc[:, 0]
        return c

    spy_close = close_series(spy)
    vix_close = close_series(vix)
    df = pd.DataFrame({"spy": spy_close})
    df["sma50"] = df["spy"].rolling(50).mean()
    df["sma200"] = df["spy"].rolling(200).mean()
    df["vix"] = vix_close.reindex(df.index).ffill()
    df.index = pd.to_datetime(df.index).date
    return df


def build_regime_lookup(df):
    """日付 -> その日より厳密に前の最終取引日の行（前営業日close判定用）."""
    dates = sorted(df.index)
    rows = {d: df.loc[d] for d in dates}
    return dates, rows


def regime_flags(row) -> dict[str, bool]:
    spy, sma50, sma200, vix = row["spy"], row["sma50"], row["sma200"], row["vix"]
    import math

    def valid(x):
        return x is not None and not (isinstance(x, float) and math.isnan(x))

    a = valid(sma50) and spy < sma50
    b = valid(sma200) and spy < sma200
    c = valid(vix) and vix > 20
    d = valid(vix) and vix > 25
    e = a or d
    return {"a_spy_lt_sma50": a, "b_spy_lt_sma200": b, "c_vix_gt20": c, "d_vix_gt25": d, "e_sma50_or_vix25": e}


VARIANT_LABELS = {
    "a_spy_lt_sma50": "(a) SPY < 50日SMA",
    "b_spy_lt_sma200": "(b) SPY < 200日SMA",
    "c_vix_gt20": "(c) VIX > 20",
    "d_vix_gt25": "(d) VIX > 25",
    "e_sma50_or_vix25": "(e) SPY<50SMA または VIX>25",
}


def pf(trades: list[dict]) -> float | None:
    gp = sum(t["pnl"] for t in trades if (t.get("pnl") or 0) > 0)
    gl = sum(-t["pnl"] for t in trades if (t.get("pnl") or 0) < 0)
    if gl == 0:
        return None
    return gp / gl


def fmt_pf(x) -> str:
    return "inf" if x is None else f"{x:.3f}"


def analyze_cohort(name: str, trades: list[dict], blocked_ids_by_variant: dict[str, set]) -> dict:
    print(f"\n{'=' * 78}\n■ コホート: {name}（n={len(trades)}, Net PnL ${sum(t['pnl'] for t in trades):,.0f}, PF {fmt_pf(pf(trades))}）\n{'=' * 78}")
    base_pnl = sum(t["pnl"] for t in trades)
    base_pf = pf(trades)
    results = {}
    header = f"{'バリアント':<34}{'ブロック':>6}{'勝ち':>5}{'負け':>5}{'勝ちPnL':>12}{'負けPnL':>12}{'PnL差':>12}{'PF前':>8}{'PF後':>8}"
    print(header)
    print("-" * len(header))
    for key, label in VARIANT_LABELS.items():
        blocked = [t for t in trades if t["trade_id"] in blocked_ids_by_variant[key]]
        kept = [t for t in trades if t["trade_id"] not in blocked_ids_by_variant[key]]
        bw = [t for t in blocked if t["pnl"] > 0]
        bl = [t for t in blocked if t["pnl"] < 0]
        bw_pnl = sum(t["pnl"] for t in bw)
        bl_pnl = sum(t["pnl"] for t in bl)
        delta = sum(t["pnl"] for t in kept) - base_pnl  # = -blocked pnl
        after_pf = pf(kept)
        print(f"{label:<36}{len(blocked):>6}{len(bw):>5}{len(bl):>5}{bw_pnl:>12,.0f}{bl_pnl:>12,.0f}{delta:>+12,.0f}{fmt_pf(base_pf):>8}{fmt_pf(after_pf):>8}")
        results[key] = {
            "label": label,
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


def monthly_blocked_distribution(trades: list[dict], blocked_ids_by_variant: dict[str, set]):
    print(f"\n{'=' * 78}\n■ 月別ブロック分布（全期間コホート、上段=exit月ベースPnL、下段=entry月ベース件数）\n{'=' * 78}")
    months = sorted({t["_exit_dt"].strftime("%Y-%m") for t in trades})
    base_by_exit = defaultdict(float)
    for t in trades:
        base_by_exit[t["_exit_dt"].strftime("%Y-%m")] += t["pnl"]
    print("\n[参考] 実績Net PnL（exit月別）: " + "  ".join(f"{m}: ${base_by_exit[m]:+,.0f}" for m in months))
    out = {}
    for key, label in VARIANT_LABELS.items():
        blocked = [t for t in trades if t["trade_id"] in blocked_ids_by_variant[key]]
        by_exit_pnl = defaultdict(float)
        by_exit_cnt = defaultdict(int)
        by_entry_cnt = defaultdict(int)
        for t in blocked:
            m_exit = t["_exit_dt"].strftime("%Y-%m")
            m_entry = t["_entry_date_et"].strftime("%Y-%m")
            by_exit_pnl[m_exit] += t["pnl"]
            by_exit_cnt[m_exit] += 1
            by_entry_cnt[m_entry] += 1
        print(f"\n{label}:")
        print("  exit月 : " + "  ".join(f"{m}: {by_exit_cnt[m]}件 ${by_exit_pnl[m]:+,.0f}" for m in months))
        print("  entry月: " + "  ".join(f"{m}: {by_entry_cnt[m]}件" for m in months))
        out[key] = {
            "blocked_pnl_by_exit_month": {m: round(by_exit_pnl[m], 2) for m in months},
            "blocked_count_by_exit_month": {m: by_exit_cnt[m] for m in months},
            "blocked_count_by_entry_month": {m: by_entry_cnt[m] for m in months},
        }
    return out


def main() -> int:
    print("R18-A: 市場レジームフィルタ反実仮想分析（2026-09-05、読み取り専用）")
    print(f"実行時刻: {datetime.now(ET).isoformat()}")

    trades = load_closed_trades()
    print(f"\nclosedトレード: {len(trades)}件, Net PnL ${sum(t['pnl'] for t in trades):,.2f}, PF {fmt_pf(pf(trades))}")

    df = fetch_market_data()
    dates, rows = build_regime_lookup(df)
    print(f"市場データ: SPY/^VIX {dates[0]}〜{dates[-1]}（{len(dates)}営業日、SMAウォームアップ含む）")

    # 各エントリー日 -> 前営業日の行でレジーム判定（look-ahead回避）
    import bisect

    blocked_ids_by_variant: dict[str, set] = {k: set() for k in VARIANT_LABELS}
    regime_by_trade = {}
    undetermined = 0
    for t in trades:
        ed = t["_entry_date_et"]
        idx = bisect.bisect_left(dates, ed)  # dates[idx-1] < ed（厳密に前営業日）
        if idx == 0:
            undetermined += 1
            continue
        prev_day = dates[idx - 1]
        flags = regime_flags(rows[prev_day])
        regime_by_trade[t["trade_id"]] = {"prev_trading_day": prev_day.isoformat(), **flags}
        for k, v in flags.items():
            if v:
                blocked_ids_by_variant[k].add(t["trade_id"])
    print(f"レジーム判定不能（市場データ範囲外）: {undetermined}件")

    # 判定日のサンプル表示（look-ahead検証用）
    sample = trades[0]
    print(f"look-ahead検証サンプル: entry_date(ET)={sample['_entry_date_et']} -> 判定使用日={regime_by_trade[sample['trade_id']]['prev_trading_day']}")

    cohorts = {
        "全期間": trades,
        f"exit >= {COHORT2_EXIT_START}": [t for t in trades if t["_exit_dt"].date().isoformat() >= COHORT2_EXIT_START],
    }
    all_results = {}
    for name, ct in cohorts.items():
        all_results[name] = analyze_cohort(name, ct, blocked_ids_by_variant)

    monthly = monthly_blocked_distribution(trades, blocked_ids_by_variant)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "regime_results.json"
    out_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(ET).isoformat(),
                "n_closed": len(trades),
                "market_data_range": [dates[0].isoformat(), dates[-1].isoformat()],
                "cohorts": all_results,
                "monthly_blocked_distribution": monthly,
                "note": "一次近似（ブロックPnL除去のみ、再配分/複利なし）。探索的検証であり昇格にはR13-C後のout-of-sample確認を要する。",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n結果JSONを保存: {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
