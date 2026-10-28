#!/usr/bin/env python3
"""Phase 1 correlation/spillover analysis for the JP semiconductor expansion roadmap.

See docs/jp_semiconductor_ai_expansion_plan.md (Phase 1) for context.

This script is a standalone, read-only research tool. It does NOT touch
pnl_state.json, does NOT submit orders, and is NOT wired into paper_demo.py.
It fetches historical daily bars via Yahoo Finance (yfinance) for:
  - US semiconductor benchmarks: SOXX, SMH, NVDA, QQQ
  - JP candidate symbols (Tier 1/2/3 from the roadmap, plus SoftBank Group
    for correlation-only analysis — purchase of 9984 remains prohibited)

And computes:
  1. Same-day and next-day correlation between US benchmark daily returns
     and JP candidate daily returns (JP t+1 vs US t, accounting for the
     JPX/NYSE session gap).
  2. Overnight spillover: conditional analysis of JP open-gap magnitude on
     days following a large US benchmark move (|return| >= threshold).

Usage:
    python scripts/analyze_jp_semiconductor_correlation.py [--period 2y] [--save]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance is required. pip install yfinance", file=sys.stderr)
    sys.exit(1)

import pandas as pd

US_BENCHMARKS = ["SOXX", "SMH", "NVDA", "QQQ"]

JP_CANDIDATES = {
    # Tier 1
    "6857.T": {"name": "Advantest", "tier": 1},
    "8035.T": {"name": "Tokyo Electron", "tier": 1},
    "6146.T": {"name": "Disco", "tier": 1},
    # Tier 2
    "6920.T": {"name": "Lasertec", "tier": 2},
    "7735.T": {"name": "Screen Holdings", "tier": 2},
    "3436.T": {"name": "Sumco", "tier": 2},
    "4063.T": {"name": "Shin-Etsu Chemical", "tier": 2},
    "4062.T": {"name": "Ibiden", "tier": 2},
    # 6967.T (Shinko Electric Industries) delisted 2023 (JIC Capital take-private) —
    # confirmed via yfinance "possibly delisted" error on 2026-08-19. Removed from
    # the live candidate set; kept out of JP_CANDIDATES entirely (not fetchable).
    # Tier 3
    "5803.T": {"name": "Fujikura", "tier": 3},
    "5801.T": {"name": "Furukawa Electric", "tier": 3},
    "6506.T": {"name": "Yaskawa Electric", "tier": 3},
    # Purchase-restricted (correlation analysis only, per roadmap section 1)
    "9984.T": {"name": "SoftBank Group", "tier": "restricted", "purchase_restricted": True},
}

LARGE_MOVE_THRESHOLD_PCT = 2.0  # |US benchmark daily return| >= 2% considered "large move"


def fetch_daily_returns(symbol: str, period: str) -> pd.Series | None:
    """Fetch daily close-to-close returns for a symbol via Yahoo Finance."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        hist = hist[["Open", "Close"]].copy()
        hist["ret"] = hist["Close"].pct_change()
        # normalize index to date-only (tz-naive) so US and JP series align
        # on trading-day boundaries regardless of exchange timezone
        hist.index = pd.to_datetime(hist.index).tz_localize(None).normalize()
        return hist
    except Exception as exc:
        print(f"  WARNING: fetch failed for {symbol}: {exc}", file=sys.stderr)
        return None


def compute_correlation(
    us_df: pd.DataFrame,
    jp_df: pd.DataFrame,
    us_symbol: str,
    jp_symbol: str,
) -> dict[str, Any]:
    """Compute same-day and next-day-JP-vs-US correlation.

    Same-day: US return(t) vs JP return(t) — measures whether the two move
    together on the calendar date basis yfinance reports (loose, since
    sessions don't overlap in wall-clock time).

    Spillover (next-day): US return(t) vs JP return(t+1) — this is the
    economically meaningful comparison, since JPX trades ~10+ hours after
    NYSE closes. A large positive correlation here supports the "overnight
    spillover" hypothesis from the roadmap.
    """
    us_ret = us_df["ret"].rename("us_ret")
    jp_ret = jp_df["ret"].rename("jp_ret")

    same_day = pd.concat([us_ret, jp_ret], axis=1, sort=True).dropna()
    same_day_corr = same_day["us_ret"].corr(same_day["jp_ret"]) if len(same_day) >= 10 else None

    jp_ret_next = jp_df["ret"].shift(-1).rename("jp_ret_next_us_session")
    # Align: we want JP(t+1) vs US(t). Shift JP index back by one so that
    # jp_ret_next[date] holds the JP return of the *next* JP trading day.
    spill = pd.concat([us_ret, jp_ret_next], axis=1, sort=True).dropna()
    spillover_corr = spill["us_ret"].corr(spill["jp_ret_next_us_session"]) if len(spill) >= 10 else None

    return {
        "us_symbol": us_symbol,
        "jp_symbol": jp_symbol,
        "n_same_day": int(len(same_day)),
        "same_day_correlation": round(float(same_day_corr), 4) if same_day_corr is not None else None,
        "n_spillover": int(len(spill)),
        "spillover_correlation_us_t_vs_jp_t_plus_1": (
            round(float(spillover_corr), 4) if spillover_corr is not None else None
        ),
    }


def compute_conditional_gap_analysis(
    us_df: pd.DataFrame,
    jp_df: pd.DataFrame,
    us_symbol: str,
    jp_symbol: str,
    threshold_pct: float,
) -> dict[str, Any]:
    """Conditional analysis: on days following a large US move, what is the
    JP overnight gap (JP open(t+1) vs JP close(t))?
    """
    us_ret_pct = (us_df["ret"] * 100).rename("us_ret_pct")
    jp_close = jp_df["Close"].rename("jp_close")
    jp_open_next = jp_df["Open"].shift(-1).rename("jp_open_next")

    merged = pd.concat([us_ret_pct, jp_close, jp_open_next], axis=1, sort=True).dropna()
    if merged.empty:
        return {
            "us_symbol": us_symbol,
            "jp_symbol": jp_symbol,
            "large_move_days": 0,
            "note": "insufficient overlapping data",
        }

    merged["jp_gap_pct"] = (merged["jp_open_next"] / merged["jp_close"] - 1) * 100

    large_up = merged[merged["us_ret_pct"] >= threshold_pct]
    large_down = merged[merged["us_ret_pct"] <= -threshold_pct]

    def _summarize(subset: pd.DataFrame) -> dict[str, Any]:
        if subset.empty:
            return {"n": 0}
        same_direction = (
            (subset["jp_gap_pct"] > 0).sum() if len(subset) and subset["us_ret_pct"].iloc[0] >= 0
            else (subset["jp_gap_pct"] < 0).sum()
        )
        return {
            "n": int(len(subset)),
            "mean_jp_gap_pct": round(float(subset["jp_gap_pct"].mean()), 3),
            "median_jp_gap_pct": round(float(subset["jp_gap_pct"].median()), 3),
            "direction_match_rate": round(float(same_direction) / len(subset), 3) if len(subset) else None,
        }

    return {
        "us_symbol": us_symbol,
        "jp_symbol": jp_symbol,
        "threshold_pct": threshold_pct,
        "total_days": int(len(merged)),
        "us_large_up_days": _summarize(large_up),
        "us_large_down_days": _summarize(large_down),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="2y", help="yfinance period (e.g. 1y, 2y, 5y)")
    parser.add_argument("--save", action="store_true", help="Save JSON report to reports/")
    args = parser.parse_args()

    print(f"=== JP Semiconductor Correlation Analysis (Phase 1) — period={args.period} ===\n")

    print("Fetching US benchmark data...")
    us_data: dict[str, pd.DataFrame] = {}
    for sym in US_BENCHMARKS:
        df = fetch_daily_returns(sym, args.period)
        if df is not None:
            us_data[sym] = df
            print(f"  {sym}: {len(df)} bars")
        else:
            print(f"  {sym}: FAILED")

    print("\nFetching JP candidate data...")
    jp_data: dict[str, pd.DataFrame] = {}
    for sym, meta in JP_CANDIDATES.items():
        df = fetch_daily_returns(sym, args.period)
        if df is not None:
            jp_data[sym] = df
            print(f"  {sym} ({meta['name']}): {len(df)} bars")
        else:
            print(f"  {sym} ({meta['name']}): FAILED")

    correlations: list[dict[str, Any]] = []
    conditional_analyses: list[dict[str, Any]] = []

    primary_us = "SOXX" if "SOXX" in us_data else next(iter(us_data), None)

    for jp_sym, jp_df in jp_data.items():
        for us_sym, us_df in us_data.items():
            correlations.append(compute_correlation(us_df, jp_df, us_sym, jp_sym))
        if primary_us:
            conditional_analyses.append(
                compute_conditional_gap_analysis(
                    us_data[primary_us], jp_df, primary_us, jp_sym, LARGE_MOVE_THRESHOLD_PCT
                )
            )

    print("\n=== Spillover Correlation Summary (US t vs JP t+1) ===")
    print(f"{'JP Symbol':<12}{'Name':<28}{'US Bench':<10}{'SpilloverCorr':<15}{'SameDayCorr':<12}")
    for row in sorted(
        [c for c in correlations if c["us_symbol"] == primary_us],
        key=lambda r: (r["spillover_correlation_us_t_vs_jp_t_plus_1"] or -999),
        reverse=True,
    ):
        name = JP_CANDIDATES.get(row["jp_symbol"], {}).get("name", "")
        print(
            f"{row['jp_symbol']:<12}{name:<28}{row['us_symbol']:<10}"
            f"{str(row['spillover_correlation_us_t_vs_jp_t_plus_1']):<15}"
            f"{str(row['same_day_correlation']):<12}"
        )

    print(f"\n=== Conditional Gap Analysis (|{primary_us} daily return| >= {LARGE_MOVE_THRESHOLD_PCT}%) ===")
    for row in conditional_analyses:
        name = JP_CANDIDATES.get(row["jp_symbol"], {}).get("name", "")
        up = row.get("us_large_up_days", {})
        down = row.get("us_large_down_days", {})
        print(f"\n  {row['jp_symbol']} ({name}):")
        print(f"    US large UP days (n={up.get('n', 0)}): mean_jp_gap={up.get('mean_jp_gap_pct', 'n/a')}%, "
              f"direction_match={up.get('direction_match_rate', 'n/a')}")
        print(f"    US large DOWN days (n={down.get('n', 0)}): mean_jp_gap={down.get('mean_jp_gap_pct', 'n/a')}%, "
              f"direction_match={down.get('direction_match_rate', 'n/a')}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": args.period,
        "primary_us_benchmark": primary_us,
        "large_move_threshold_pct": LARGE_MOVE_THRESHOLD_PCT,
        "us_symbols_fetched": list(us_data.keys()),
        "jp_symbols_fetched": list(jp_data.keys()),
        "jp_candidate_metadata": JP_CANDIDATES,
        "correlations": correlations,
        "conditional_gap_analysis": conditional_analyses,
    }

    if args.save:
        out_path = PROJECT_ROOT / "reports" / "jp_semiconductor_correlation_analysis.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nSaved report to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
