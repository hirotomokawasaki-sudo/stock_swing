#!/usr/bin/env python3
"""R18-E: Execution-cost measurement from recorded fills (READ-ONLY analysis).

Purpose
-------
paper環境（Alpaca paper）のPnLには手数料もスリッページ控除も入っていない
（pnl_state.jsonのtradeレコードにfee/commission/slippageフィールドは存在せず、
PnLは記録されたentry_price/exit_priceの差×qtyのみ。2026-09-05 コードレベル
確認: src/stock_swing/tracking/ と check_go_no_go.py に cost 控除は一切ない）。
このスクリプトは、記録されたfill価格を日次バーの基準価格と比較して
「実効スリッページ（fill vs 基準価格の乖離、bps）」の分布を推計する。

基準価格の定義（データで可能なもの、明記）
------------------------------------------
分足の履歴が保存されていないため、基準価格は yfinance の日足バーから取る:

- **ref=open**: 約定当日の公式始値。エントリーの大半は 9:25/9:35 ET の
  paper_demo run（市場オープン直後）なので、エントリーlegに対しては
  「オープンからの乖離 ≒ 数分のドリフト + fill品質」の上限推計になる。
- **ref=prev_close**: 前営業日終値。オーバーナイトギャップを含む参考値。

いずれも「真のスリッページ（同時刻NBBO midとの差）」ではなく上限推計である
ことに注意。特に 12:00 / 15:55 ET run のエントリーと日中の stop exit は
当日ドリフトが支配的になるため、時間帯バケット別に分けて集計する
（9時台バケットが最もクリーンな推計）。

注文種別: 全注文は market 注文
（src/stock_swing/decision_engine/decision_engine.py:213 order_type="market"、
limit注文の発注パスは存在しない）。よって market/limit の別集計は不要。

既知のデータ品質限界（結果解釈に必須）
--------------------------------------
1. Alpaca paper のバー凍結問題（2026-04-22〜）により、paper_demo.py の
   resolve_recorded_entry_price() は broker fill が sizing_price から 15%超
   乖離した場合 **sizing_price（Massive最新close）を entry_price として記録**
   する。つまり記録価格の一部は「fillですらない」楽観値。
2. fill価格がその日の[low, high]レンジ外にあるlegは stale/合成価格の疑いが
   強いため、件数を別掲しデフォルトで分布から除外する（--include-outliers
   で含められる）。

cost-adjusted PF 試算
---------------------
片道 X bps を notional（qty×price）に掛けて控除した場合の PF を、
全期間・直近コホート（exit_time >= 2026-08-14、economic_viability ゲートと
同一定義）で試算する。check_go_no_go.py へのコード変更は行わない（R18-E は
定義と試算まで。Required化はユーザー承認後の別タスク）。

READ-ONLY: data/ 配下への書き込みは一切しない。出力はstdoutのみ
（--json PATH で任意パスに結果JSONを保存可能。docs/配下を想定）。

Usage:
    python scripts/analyze_execution_costs.py [--cohort-start 2026-08-14]
        [--cost-bps 2 5 10 15] [--json docs/r18e_.../results.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PNL_STATE = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
ET = ZoneInfo("America/New_York")

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance is required. pip install yfinance", file=sys.stderr)
    sys.exit(1)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def load_closed_trades() -> list[dict]:
    state = json.loads(PNL_STATE.read_text())
    return [
        t for t in state.get("trades", [])
        if t.get("status") == "closed"
        and isinstance(t.get("pnl"), (int, float))
        and t.get("entry_price") and t.get("exit_price")
        and t.get("entry_time") and t.get("exit_time")
    ]


def fetch_daily_bars(symbols: list[str], start: str, end: str) -> dict[str, dict[str, dict]]:
    """Fetch daily OHLC via yfinance. Returns {symbol: {YYYY-MM-DD: {open,high,low,close}}}."""
    data = yf.download(
        symbols, start=start, end=end, group_by="ticker",
        progress=False, auto_adjust=False, threads=True,
    )
    bars: dict[str, dict[str, dict]] = {}
    for sym in symbols:
        try:
            df = data[sym] if len(symbols) > 1 else data
            df = df.dropna(how="all")
        except (KeyError, TypeError):
            continue
        day_map: dict[str, dict] = {}
        for idx, row in df.iterrows():
            try:
                day_map[idx.date().isoformat()] = {
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                }
            except (TypeError, ValueError, KeyError):
                continue
        if day_map:
            bars[sym] = day_map
    return bars


def prev_close(day_map: dict[str, dict], day: str) -> float | None:
    prior = sorted(d for d in day_map if d < day)
    if not prior:
        return None
    return day_map[prior[-1]].get("close")


def pct_stats(values: list[float]) -> dict:
    if not values:
        return {}
    vs = sorted(values)

    def q(p: float) -> float:
        i = min(len(vs) - 1, max(0, int(round(p * (len(vs) - 1)))))
        return vs[i]

    return {
        "n": len(vs),
        "mean": statistics.fmean(vs),
        "median": statistics.median(vs),
        "p25": q(0.25),
        "p75": q(0.75),
        "p90": q(0.90),
        "p95": q(0.95),
    }


def fmt_stats(s: dict) -> str:
    if not s:
        return "n=0"
    return (f"n={s['n']:3d}  mean={s['mean']:+7.1f}  median={s['median']:+7.1f}  "
            f"p25={s['p25']:+7.1f}  p75={s['p75']:+7.1f}  p90={s['p90']:+7.1f}  p95={s['p95']:+7.1f}")


def compute_pf(trades: list[dict], cost_bps_per_side: float) -> dict:
    """PF with cost_bps_per_side deducted on each side's notional."""
    n = 0
    gross_profit = 0.0
    gross_loss = 0.0
    total = 0.0
    for t in trades:
        qty = float(t.get("qty") or 0)
        entry_notional = qty * float(t["entry_price"])
        exit_notional = qty * float(t["exit_price"])
        cost = (entry_notional + exit_notional) * cost_bps_per_side / 10_000.0
        adj = float(t["pnl"]) - cost
        n += 1
        total += adj
        if adj > 0:
            gross_profit += adj
        else:
            gross_loss += -adj
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    return {"n": n, "pf": pf, "net": total, "expectancy": total / n if n else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-start", default="2026-08-14",
                        help="recent-cohort exit_time lower bound (economic_viability と同一デフォルト)")
    parser.add_argument("--cost-bps", type=float, nargs="+", default=[0.0, 2.0, 5.0, 10.0, 15.0],
                        help="片道コスト bps の試算グリッド")
    parser.add_argument("--include-outliers", action="store_true",
                        help="当日[low,high]レンジ外のfillも分布に含める")
    parser.add_argument("--json", default=None, help="結果JSONの保存先（docs/配下を想定）")
    args = parser.parse_args()

    trades = load_closed_trades()
    print(f"=== R18-E Execution Cost Analysis (read-only) ===")
    print(f"closed trades with usable prices: {len(trades)}")
    print("order type: all market orders (decision_engine.py:213, limit path does not exist)\n")

    symbols = sorted({t["symbol"] for t in trades})
    entry_days = [parse_dt(t["entry_time"]).date().isoformat() for t in trades]
    exit_days = [parse_dt(t["exit_time"]).date().isoformat() for t in trades]
    start = min(entry_days)
    end = max(exit_days)
    print(f"fetching daily bars via yfinance: {len(symbols)} symbols, {start}..{end} ...")
    # end+2d so the last exit day is included (yf end is exclusive)
    from datetime import date, timedelta
    end_plus = (date.fromisoformat(end) + timedelta(days=2)).isoformat()
    bars = fetch_daily_bars(symbols, start, end_plus)
    print(f"got bars for {len(bars)}/{len(symbols)} symbols\n")

    # Build legs: (kind, side_sign, symbol, day, hour_et, fill_price, asset_class)
    legs = []
    for t in trades:
        for kind, price_key, time_key, sign in (
            ("entry", "entry_price", "entry_time", +1),   # buy: fill>ref = cost
            ("exit", "exit_price", "exit_time", -1),      # sell: fill<ref = cost
        ):
            dt = parse_dt(t[time_key])
            legs.append({
                "kind": kind,
                "sign": sign,
                "symbol": t["symbol"],
                "day": dt.date().isoformat(),
                "hour_et": dt.astimezone(ET).hour,
                "minute_et": dt.astimezone(ET).minute,
                "fill": float(t[price_key]),
                "asset_class": t.get("asset_class") or "unknown",
                "exit_reason": t.get("exit_reason"),
            })

    measured = []
    missing_bar = 0
    outliers = 0
    for leg in legs:
        day_map = bars.get(leg["symbol"])
        bar = day_map.get(leg["day"]) if day_map else None
        if not bar or not bar.get("open"):
            missing_bar += 1
            continue
        pc = prev_close(day_map, leg["day"])
        in_range = (bar["low"] * 0.999) <= leg["fill"] <= (bar["high"] * 1.001)
        if not in_range:
            outliers += 1
            if not args.include_outliers:
                leg["outlier"] = True
                measured.append({**leg, "outlier": True})
                continue
        rec = {
            **leg,
            "outlier": not in_range,
            "slip_open_bps": leg["sign"] * (leg["fill"] - bar["open"]) / bar["open"] * 10_000,
        }
        if pc:
            rec["slip_prevclose_bps"] = leg["sign"] * (leg["fill"] - pc) / pc * 10_000
        measured.append(rec)

    valid = [m for m in measured if "slip_open_bps" in m]
    print(f"legs total={len(legs)}  measured={len(valid)}  missing_bar={missing_bar}  "
          f"outside_day_range(stale/synthetic suspect)={outliers}"
          f"{' (included)' if args.include_outliers else ' (excluded from distributions)'}\n")

    results: dict = {"generated_at": datetime.now(timezone.utc).isoformat(),
                     "n_trades": len(trades), "n_legs_measured": len(valid),
                     "n_outliers_excluded": outliers, "distributions": {}, "cost_adjusted_pf": {}}

    print("── 実効スリッページ分布（+ = コスト方向: buyは基準より高く、sellは基準より安く約定）──")
    buckets = {
        "entry (all)": lambda m: m["kind"] == "entry",
        "entry 09:2x-09:4x ET (near-open runs; cleanest)": lambda m: m["kind"] == "entry" and m["hour_et"] == 9,
        "entry 12:00 ET run": lambda m: m["kind"] == "entry" and m["hour_et"] == 12,
        "entry 15:5x ET run": lambda m: m["kind"] == "entry" and m["hour_et"] == 15,
        "exit (all)": lambda m: m["kind"] == "exit",
        "exit hour 09 ET": lambda m: m["kind"] == "exit" and m["hour_et"] == 9,
        "exit hour 10-15 ET (intraday stops)": lambda m: m["kind"] == "exit" and 10 <= m["hour_et"] <= 15,
    }
    for ref_key, label in (("slip_open_bps", "ref=当日始値"), ("slip_prevclose_bps", "ref=前営業日終値")):
        print(f"\n[{label}]")
        results["distributions"][ref_key] = {}
        for name, pred in buckets.items():
            vals = [m[ref_key] for m in valid if pred(m) and ref_key in m]
            s = pct_stats(vals)
            results["distributions"][ref_key][name] = s
            print(f"  {name:<48} {fmt_stats(s)}")

    print("\n── cost-adjusted PF 試算（片道 X bps を両legのnotionalに課金）──")
    cohort = [t for t in trades if (t.get("exit_time") or "")[:10] >= args.cohort_start]
    print(f"{'X bps/side':>10} | {'全期間 PF':>10} {'Net':>12} | 直近(exit>={args.cohort_start}) PF{'':>0} {'Net':>12}")
    for x in args.cost_bps:
        full = compute_pf(trades, x)
        rec = compute_pf(cohort, x)
        results["cost_adjusted_pf"][str(x)] = {"full": full, "recent": rec}
        print(f"{x:>10.1f} | {full['pf']:>10.3f} {full['net']:>+12,.0f} | "
              f"{rec['pf']:>10.3f} {rec['net']:>+12,.0f}   (n_full={full['n']}, n_recent={rec['n']})")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
        print(f"\nresults JSON saved: {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
