#!/usr/bin/env python3
"""Read-only performance assessment of the stock_swing paper ledger.

Reproduces docs/strategy_assessment_20261020/README.md numbers.
Never writes to data/ or config/; only writes results.json next to this file.
Usage: python3 docs/strategy_assessment_20261020/assess_performance.py
"""
import csv, json, math, random, statistics as st
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "data/tracking/pnl_state.json"
OUT = Path(__file__).with_name("results.json")
SEED, B = 7, 4000


def pf(x):
    g = sum(v for v in x if v > 0)
    l = -sum(v for v in x if v <= 0)
    return g / l if l else float("inf")


def tstats(ts):
    p = [t["pnl"] for t in ts]
    w = [v for v in p if v > 0]
    lo = [v for v in p if v <= 0]
    n = len(p)
    return {
        "n": n, "net": round(sum(p)), "pf": round(pf(p), 3) if n else None,
        "win_rate": round(len(w) / n, 3) if n else None,
        "avg_win": round(sum(w) / len(w)) if w else 0,
        "avg_loss": round(sum(lo) / len(lo)) if lo else 0,
        "expectancy": round(sum(p) / n) if n else 0,
    }


def main():
    random.seed(SEED)
    d = json.loads(LEDGER.read_text())
    res = {"ledger_last_updated": d["last_updated"], "baseline_equity": d["baseline_equity"],
           "baseline_date": d["baseline_date"], "ledger_max_drawdown_pct_field": d.get("max_drawdown_pct")}
    T = [t for t in d["trades"] if t.get("status") == "closed" and t.get("pnl") is not None]
    res["closed_trades"] = len(T)
    res["quarantined_excluded"] = len(d.get("quarantined_trades", []))

    # --- equity curve (last snapshot per date)
    by = {}
    for s in d["daily_snapshots"]:
        by[s["date"]] = s["equity"]
    ds = sorted(by)
    eq = [by[x] for x in ds]
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))]
    peak, mdd, pk_date = eq[0], 0.0, ds[0]
    for x, e in zip(ds, eq):
        if e > peak:
            peak, pk_date = e, x
        mdd = min(mdd, e / peak - 1)
    days = (datetime.fromisoformat(ds[-1]) - datetime.fromisoformat(d["baseline_date"])).days
    tot = eq[-1] / d["baseline_equity"] - 1
    res["equity"] = {
        "first_date": ds[0], "last_date": ds[-1], "n_dates": len(ds), "last_equity": eq[-1],
        "peak_equity": max(eq), "peak_date": ds[eq.index(max(eq))],
        "total_return_vs_baseline": round(tot, 4),
        "annualized_simple_compound": round((1 + tot) ** (365 / days) - 1, 4),
        "daily_vol_ann": round(st.pstdev(rets) * math.sqrt(252), 4),
        "naive_sharpe_rf0": round(st.mean(rets) / st.pstdev(rets) * math.sqrt(252), 2),
        "max_drawdown_curve": round(mdd, 4),
        "dd_from_peak_now": round(eq[-1] / max(eq) - 1, 4),
        "days_over_5pct_below_peak": sum(1 for i, e in enumerate(eq) if e < max(eq[: i + 1]) * 0.95),
    }
    mon = defaultdict(list)
    for x in ds:
        mon[x[:7]].append(by[x])
    prev, mrows = d["baseline_equity"], {}
    for k in sorted(mon):
        mrows[k] = round(mon[k][-1] / prev - 1, 4)
        prev = mon[k][-1]
    res["monthly_return"] = mrows

    # --- trade stats
    res["all"] = tstats(T)
    res["breakeven_win_rate"] = round(-res["all"]["avg_loss"] / (res["all"]["avg_win"] - res["all"]["avg_loss"]), 3)

    def grp(fn):
        g = defaultdict(list)
        for t in T:
            g[fn(t)].append(t)
        return {k: tstats(v) for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))}

    res["by_exit_reason"] = grp(lambda t: t.get("exit_reason"))
    res["by_asset_class"] = grp(lambda t: t.get("asset_class"))
    res["by_month"] = grp(lambda t: (t.get("exit_time") or "")[:7])
    hb = lambda t: "<1d" if (t.get("holding_days") or 0) < 1 else "1-3d" if t["holding_days"] < 3 else "3-6d" if t["holding_days"] < 6 else "6d+"
    res["by_holding"] = grp(hb)
    S = sorted(T, key=lambda t: t["pnl"])
    res["worst10"] = [(t["symbol"], round(t["pnl"]), t.get("exit_reason"), t["exit_time"][:10]) for t in S[:10]]
    res["best10"] = [(t["symbol"], round(t["pnl"]), t.get("exit_reason"), t["exit_time"][:10]) for t in S[-10:]]
    res["worst10_sum"] = round(sum(t["pnl"] for t in S[:10]))
    res["best10_sum"] = round(sum(t["pnl"] for t in S[-10:]))
    nots = [t["qty"] * t["entry_price"] for t in T if t.get("qty") and t.get("entry_price")]
    res["avg_notional"] = round(st.mean(nots))
    res["cohort_exit_ge_2026_08_14"] = tstats([t for t in T if t["exit_time"] >= "2026-08-14"])

    # --- weekly PnL
    wk = defaultdict(list)
    for t in T:
        wk[datetime.fromisoformat(t["exit_time"].replace("Z", "+00:00")).isocalendar()[:2]].append(t["pnl"])
    wsum = sorted((round(sum(v)), "%d-W%02d" % k) for k, v in wk.items())
    res["weekly"] = {"weeks": len(wk), "positive_weeks": sum(1 for v, _ in wsum if v > 0),
                     "worst5": wsum[:5], "best5": wsum[-5:]}

    # --- bootstrap
    p = [t["pnl"] for t in T]
    n = len(p)
    ex1, pf1 = [], []
    for _ in range(B):
        s = [random.choice(p) for _ in range(n)]
        ex1.append(st.mean(s)); pf1.append(pf(s))
    W = list(wk.values())
    ex2, pf2 = [], []
    for _ in range(B):
        s = []
        for _ in range(len(W)):
            s += random.choice(W)
        ex2.append(st.mean(s)); pf2.append(pf(s))
    q = lambda a, f: sorted(a)[int(f * B)]
    res["bootstrap"] = {
        "trade_level": {"expectancy_ci95": [round(q(ex1, .025)), round(q(ex1, .975))],
                        "pf_ci95": [round(q(pf1, .025), 2), round(q(pf1, .975), 2)],
                        "p_pf_gt_1": round(sum(1 for x in pf1 if x > 1) / B, 2)},
        "week_block": {"expectancy_ci95": [round(q(ex2, .025)), round(q(ex2, .975))],
                       "pf_ci95": [round(q(pf2, .025), 2), round(q(pf2, .975), 2)],
                       "p_pf_gt_1": round(sum(1 for x in pf2 if x > 1) / B, 2)},
        "t_stat_expectancy": round(st.mean(p) / (st.pstdev(p) / math.sqrt(n)), 2),
    }
    # --- power / design effect
    sd = st.pstdev(p)
    deff = (st.pstdev(ex2) / st.pstdev(ex1)) ** 2
    months = (datetime.fromisoformat(max(t["exit_time"] for t in T)[:10]) - datetime.fromisoformat(min(t["entry_time"] for t in T)[:10])).days / 30.44
    tpm = n / months
    pw = {}
    for delta in (300, 500, 1000):
        n_ind = ((1.645 + 0.84) * sd / delta) ** 2
        pw[str(delta)] = {"n_independent": round(n_ind), "n_with_deff": round(n_ind * deff),
                          "months_at_current_pace": round(n_ind * deff / tpm, 1)}
    res["power"] = {"sd_per_trade": round(sd), "design_effect": round(deff, 1),
                    "trades_per_month": round(tpm, 1), "one_sided_alpha": 0.05, "power": 0.8, "by_expectancy_delta_usd": pw}
    # sensitivity: annual gross loss / equity
    gl = -sum(v for v in p if v <= 0)
    res["annual_gross_loss_over_equity"] = round(gl * 12 / months / d["baseline_equity"], 2)

    # --- reconstructed exposure
    exp = defaultdict(float)
    for t in T:
        a = datetime.fromisoformat(t["entry_time"].replace("Z", "+00:00")).date()
        b = datetime.fromisoformat(t["exit_time"].replace("Z", "+00:00")).date()
        if b < a:
            continue
        x = a
        while x <= b:
            if x.weekday() < 5:
                exp[x] += t["qty"] * t["entry_price"]
            x += timedelta(days=1)
    m = defaultdict(list)
    for x, v in exp.items():
        e = by.get(x.isoformat())
        if e:
            m[x.strftime("%Y-%m")].append(v / e)
    res["reconstructed_gross_over_equity_by_month"] = {k: round(st.mean(v), 2) for k, v in sorted(m.items())}

    # --- benchmarks (two windows; caches end at different dates)
    def series_r11(sym):
        j = json.loads((ROOT / f"data/r11_price_cache/{sym}.json").read_text())
        return {k: float(v["close"]) for k, v in j.items()}
    bm = {}
    csvp = ROOT / "data/benchmarks/benchmark_prices.csv"
    g = defaultdict(dict)
    for r in csv.DictReader(open(csvp)):
        g[r["symbol"]][r["date"]] = float(r["close"])
    def win(s, a, b):
        ks = [k for k in sorted(s) if a <= k <= b]
        return (ks[0], ks[-1], round(s[ks[-1]] / s[ks[0]] - 1, 4)) if len(ks) > 1 else None
    for sym in ("SPY", "QQQ", "SMH"):
        bm[sym] = {"r11_cache_2026-05-12_to_2026-08-14": win(series_r11(sym), "2026-05-12", "2026-08-14"),
                   "benchmarks_csv_from_2026-07-20": win(g[sym], "2026-07-20", "2026-12-31") if sym in g else None}
    res["benchmarks"] = bm
    res["strategy_equity_2026-07-20_to_last"] = (by.get("2026-07-20"), eq[-1])
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
