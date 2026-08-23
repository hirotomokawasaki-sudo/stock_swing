#!/usr/bin/env python3
"""R13-D Phase 1 (2026-08-23): ETF sector-rotation feasibility research.

Mirrors the Phase 1 pattern already used and validated for the JP
semiconductor overnight-spillover roadmap item (see root MEMORY.md
2026-08-19 entry): a pure-research, no-production-impact correlation/
feasibility check, run BEFORE any strategy design or shadow logging. GO/
NO-GO here only decides whether Phase 2 (strategy design) is worth
attempting -- it does not touch any live trading code, config, or order
path.

QUESTION: does a simple relative-momentum sector-rotation rule (rotate
into recently-strong tech sub-sectors, out of recently-weak ones) produce
better risk-adjusted returns than (a) an equal-weight buy-and-hold basket
of all tracked sector ETFs, or (b) buy-and-hold SPY, using the SAME real
daily price data already cached for R13-C (data/r11_price_cache/,
2024-08-15 to 2026-08-14)?

DATA: config/reference/symbol_registry.yaml tags 20 non-SPY ETFs (already
cached) with a `sector` field: semiconductor (7: SOXX/SMH/SOXQ/FTXL/SHOC/
CHPS/CHPX/SMHX -- note SMHX is 8th but fabless-focused, kept separate),
software (6), robotics_ai (2), technology (1: QQQ), technology_cloud (1:
SKYY), quantum_computing (1: QTUM). Each sector's daily "index" return is
the equal-weighted mean of its member ETFs' daily returns -- NOT a
capitalization-weighted index; this is a simplification appropriate for a
feasibility check, not a final composite methodology.

METHOD: at each monthly rebalance date, rank all sectors (with >=2 members
to reduce single-ETF noise; robotics_ai/technology/technology_cloud/
quantum_computing/broad_market are single- or two-member and are included
but flagged) by trailing 63-trading-day (~3 month) cumulative return.
Hold the top-N sectors equal-weighted for the following ~21-trading-day
period, then re-rank and rebalance. This is a standard, simple relative-
momentum rotation rule (not fit/optimized against this specific dataset --
63d/21d/top-2 are round-number defaults, deliberately not grid-searched,
per the same overfitting-avoidance principle used throughout R13-C).

COMPARISON BASELINES:
  - Equal-weight buy-and-hold across all tracked sector ETFs (no rotation)
  - Buy-and-hold SPY (broad market)

LIMITATIONS (explicit, not hidden):
  - Equal-weighted sector "index" is a simplification; a cap-weighted
    composite could behave differently.
  - No transaction costs/slippage modeled at this Phase 1 stage (this is a
    feasibility check on the RAW momentum signal, not a backtest of a
    tradeable strategy -- matching how R13-C's own R11 v1 first pass and
    the JP spillover Phase 1 correlation check were both signal-only,
    friction-free feasibility checks before any strategy design work).
  - 2-year window (2024-08 to 2026-08) is a single historical regime
    (bull market with two corrections); no claim of regime-robustness.
  - Survivorship: uses the CURRENTLY tracked ETF set retroactively over
    the full window, same caveat as R13-C's point-in-time-universe
    discussion -- these are today's config's ETFs, not necessarily what a
    contemporary 2024 observer would have picked (though ETF universes are
    far less prone to hindsight-driven selection than individual stocks).

Usage:
    python scripts/r13d_etf_sector_rotation_phase1.py [--top-n 2] [--lookback-days 63] [--hold-days 21] [--save]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
REGISTRY_PATH = PROJECT_ROOT / "config" / "reference" / "symbol_registry.yaml"


def load_sector_map() -> dict[str, str]:
    with open(REGISTRY_PATH) as f:
        registry = yaml.safe_load(f)
    return {
        sym: meta.get("sector", "unknown")
        for sym, meta in registry["symbols"].items()
        if meta.get("asset_class") == "etf"
    }


def load_closes(symbol: str) -> dict[str, float]:
    path = CACHE_DIR / f"{symbol}.json"
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    return {d: bar["close"] for d, bar in data.items()}


def build_sector_daily_returns(sector_map: dict[str, str]) -> tuple[dict[str, dict[str, float]], dict[str, list[str]]]:
    """Returns (sector -> {date: equal_weight_avg_daily_return}, sector -> member symbols)."""
    symbol_closes = {sym: load_closes(sym) for sym in sector_map}
    sector_members: dict[str, list[str]] = {}
    for sym, sector in sector_map.items():
        if symbol_closes.get(sym):
            sector_members.setdefault(sector, []).append(sym)

    symbol_returns: dict[str, dict[str, float]] = {}
    for sym, closes in symbol_closes.items():
        dates = sorted(closes.keys())
        rets = {}
        prev = None
        for d in dates:
            if prev is not None and closes[prev] > 0:
                rets[d] = (closes[d] - closes[prev]) / closes[prev]
            prev = d
        symbol_returns[sym] = rets

    all_dates = sorted(set().union(*[set(r.keys()) for r in symbol_returns.values()]))
    sector_returns: dict[str, dict[str, float]] = {}
    for sector, members in sector_members.items():
        sector_returns[sector] = {}
        for d in all_dates:
            vals = [symbol_returns[m][d] for m in members if d in symbol_returns[m]]
            if vals:
                sector_returns[sector][d] = sum(vals) / len(vals)

    return sector_returns, sector_members


def trailing_return(returns: dict[str, float], dates: list[str], end_idx: int, lookback: int) -> float | None:
    start_idx = end_idx - lookback
    if start_idx < 0:
        return None
    window_dates = dates[start_idx:end_idx]
    cum = 1.0
    n_found = 0
    for d in window_dates:
        r = returns.get(d)
        if r is not None:
            cum *= (1 + r)
            n_found += 1
    if n_found < lookback * 0.8:  # require at least 80% coverage
        return None
    return cum - 1.0


def run_rotation(
    sector_returns: dict[str, dict[str, float]],
    all_dates: list[str],
    top_n: int,
    lookback_days: int,
    hold_days: int,
    min_members: int = 2,
) -> dict[str, Any]:
    eligible_sectors = {
        s: r for s, r in sector_returns.items()
    }
    daily_portfolio_returns: list[tuple[str, float]] = []
    rebalance_log: list[dict[str, Any]] = []

    i = lookback_days
    current_holdings: list[str] = []
    days_since_rebalance = hold_days  # force immediate first rebalance

    while i < len(all_dates):
        date = all_dates[i]
        if days_since_rebalance >= hold_days:
            scores = {}
            for sector, rets in eligible_sectors.items():
                tr = trailing_return(rets, all_dates, i, lookback_days)
                if tr is not None:
                    scores[sector] = tr
            ranked = sorted(scores.items(), key=lambda x: -x[1])
            current_holdings = [s for s, _ in ranked[:top_n]]
            rebalance_log.append({
                "date": date,
                "holdings": current_holdings,
                "scores": {s: round(v, 4) for s, v in ranked},
            })
            days_since_rebalance = 0

        if current_holdings:
            day_rets = [
                sector_returns[s].get(date, 0.0) for s in current_holdings
                if date in sector_returns[s]
            ]
            port_ret = sum(day_rets) / len(day_rets) if day_rets else 0.0
        else:
            port_ret = 0.0
        daily_portfolio_returns.append((date, port_ret))
        days_since_rebalance += 1
        i += 1

    return {"daily_returns": daily_portfolio_returns, "rebalance_log": rebalance_log}


def equal_weight_all(sector_returns: dict[str, dict[str, float]], all_dates: list[str], start_idx: int) -> list[tuple[str, float]]:
    result = []
    for i in range(start_idx, len(all_dates)):
        date = all_dates[i]
        vals = [r.get(date) for r in sector_returns.values() if date in r]
        vals = [v for v in vals if v is not None]
        result.append((date, sum(vals) / len(vals) if vals else 0.0))
    return result


def cumulative_curve(daily_returns: list[tuple[str, float]]) -> list[float]:
    curve = [1.0]
    for _, r in daily_returns:
        curve.append(curve[-1] * (1 + r))
    return curve[1:]


def sharpe_ratio(daily_returns: list[float], trading_days_per_year: int = 252) -> float | None:
    if len(daily_returns) < 2:
        return None
    mean_r = statistics.mean(daily_returns)
    std_r = statistics.pstdev(daily_returns)
    if std_r == 0:
        return None
    return (mean_r / std_r) * (trading_days_per_year ** 0.5)


def max_drawdown(curve: list[float]) -> float:
    peak = curve[0]
    max_dd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def summarize_curve(label: str, daily_returns: list[tuple[str, float]]) -> dict[str, Any]:
    rets = [r for _, r in daily_returns]
    curve = cumulative_curve(daily_returns)
    total_return = curve[-1] - 1.0 if curve else 0.0
    sharpe = sharpe_ratio(rets)
    mdd = max_drawdown(curve) if curve else 0.0
    n_years = len(rets) / 252.0
    cagr = (curve[-1] ** (1 / n_years) - 1) if curve and n_years > 0 and curve[-1] > 0 else None
    return {
        "label": label,
        "n_days": len(rets),
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2) if cagr is not None else None,
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "max_drawdown_pct": round(mdd * 100, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--lookback-days", type=int, default=63)
    parser.add_argument("--hold-days", type=int, default=21)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    sector_map = load_sector_map()
    sector_returns, sector_members = build_sector_daily_returns(sector_map)
    print(f"Sectors tracked ({len(sector_members)}):")
    for s, members in sorted(sector_members.items()):
        print(f"  {s:20s} n={len(members)}  {members}")

    all_dates = sorted(set().union(*[set(r.keys()) for r in sector_returns.values()]))
    print(f"\nDate range: {all_dates[0]} -> {all_dates[-1]} ({len(all_dates)} days)")

    rotation_result = run_rotation(
        sector_returns, all_dates,
        top_n=args.top_n, lookback_days=args.lookback_days, hold_days=args.hold_days,
    )
    rotation_daily = rotation_result["daily_returns"]
    start_idx = args.lookback_days
    eq_weight_daily = equal_weight_all(sector_returns, all_dates, start_idx)

    spy_closes = load_closes("SPY")
    spy_dates = sorted(spy_closes.keys())
    spy_returns: dict[str, float] = {}
    prev = None
    for d in spy_dates:
        if prev is not None and spy_closes[prev] > 0:
            spy_returns[d] = (spy_closes[d] - spy_closes[prev]) / spy_closes[prev]
        prev = d
    spy_daily = [(d, spy_returns[d]) for d in all_dates[start_idx:] if d in spy_returns]

    print("\n" + "=" * 90)
    print(f"R13-D Phase 1: Sector Rotation (top-{args.top_n}, lookback={args.lookback_days}d, "
          f"hold={args.hold_days}d) vs Baselines")
    print("=" * 90)
    results = [
        summarize_curve(f"rotation_top{args.top_n}", rotation_daily),
        summarize_curve("equal_weight_all_sectors", eq_weight_daily),
        summarize_curve("spy_buy_and_hold", spy_daily),
    ]
    for r in results:
        print(f"  {r['label']:28s} n={r['n_days']:4d}  total_return={r['total_return_pct']:+7.2f}%  "
              f"CAGR={r['cagr_pct']}%  Sharpe={r['sharpe']}  maxDD={r['max_drawdown_pct']}%")

    print("\n" + "-" * 90)
    print("Rebalance history (first 5 and last 5)")
    print("-" * 90)
    log = rotation_result["rebalance_log"]
    for entry in log[:5] + (["..."] if len(log) > 10 else []) + log[-5:] if len(log) > 5 else log:
        if entry == "...":
            print("  ...")
            continue
        print(f"  {entry['date']}: holdings={entry['holdings']}  top_scores={dict(list(entry['scores'].items())[:4])}")

    # Sensitivity: try a couple of alternate (top_n, lookback, hold) combos
    print("\n" + "-" * 90)
    print("Parameter sensitivity (not optimized -- spot-check for robustness)")
    print("-" * 90)
    for tn, lb, hd in [(1, 63, 21), (3, 63, 21), (2, 126, 21), (2, 63, 42)]:
        alt = run_rotation(sector_returns, all_dates, top_n=tn, lookback_days=lb, hold_days=hd)
        s = summarize_curve(f"top{tn}_lb{lb}_hd{hd}", alt["daily_returns"])
        print(f"  top_n={tn} lookback={lb}d hold={hd}d: total_return={s['total_return_pct']:+7.2f}% "
              f"Sharpe={s['sharpe']} maxDD={s['max_drawdown_pct']}%")

    print("\n" + "-" * 90)
    print("VERDICT (Phase 1 feasibility only -- NOT a paper/live trading decision)")
    print("-" * 90)
    rotation_summary = results[0]
    eq_summary = results[1]
    spy_summary = results[2]
    beats_eq = (rotation_summary["sharpe"] or -999) > (eq_summary["sharpe"] or -999)
    beats_spy = (rotation_summary["sharpe"] or -999) > (spy_summary["sharpe"] or -999)
    if beats_eq and beats_spy:
        print("  ✅ GO -- rotation beats both baselines on risk-adjusted return (Sharpe).")
        print("     Proceed to Phase 2 (strategy design) using R13-C's t+1-fill + cost-aware methodology.")
    elif beats_eq or beats_spy:
        print("  ⚠️  MIXED -- rotation beats one baseline but not the other.")
        print("     Worth a deeper look (longer lookback/regime split) before committing to Phase 2.")
    else:
        print("  ❌ NO-GO (as tested) -- simple relative-momentum rotation does not beat either")
        print("     baseline on this 2-year window with these round-number parameters.")

    if args.save:
        out_path = PROJECT_ROOT / "reports" / "r13d_etf_sector_rotation_phase1_results.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({
                "config": vars(args),
                "sector_members": sector_members,
                "results": results,
                "rebalance_log": log,
            }, f, indent=2, ensure_ascii=False)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
