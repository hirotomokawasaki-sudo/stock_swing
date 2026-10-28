#!/usr/bin/env python3
"""R11-C addendum: market-regime entry filter, motivated directly by the
R11-B parameter-search finding (2026-08-15) that BreakoutMomentumStrategy's
edge is bull-market-dependent -- the "validation" window (2025-10-27 to
2026-03-20) was a real SPY/QQQ correction (-5.4%/-7.3%) during which
stop_loss ratio jumped from a 25.4% baseline to 44.7%.

Hypothesis: a filter that skips new BUYs while the broad market (SPY) is in
a declining-trend regime should reduce losses specifically during periods
like the validation window, without materially hurting bull-market periods
(train/holdout) where the strategy already works.

Evaluated using the SAME train/validation/holdout 3-way split as
r11b_param_search.py (not the 2-way midpoint split used for the other
R11-C candidates), because that split is what exposed the regime-dependency
problem in the first place -- a 2-way split would risk re-hiding it via
cross-window averaging, exactly the trap flagged on 2026-08-05 and again
today.

Two filter variants tested:
  A. price_below_sma:  skip BUY if SPY close < SPY SMA(sma_period)
  B. sma_declining:    skip BUY if SPY SMA(sma_period) is lower than it was
                       `trend_window` trading days ago

Usage:
    python scripts/r11c2_regime_filter_backtest.py --variant price_below_sma
    python scripts/r11c2_regime_filter_backtest.py --variant sma_declining
    python scripts/r11c2_regime_filter_backtest.py --variant all
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import r11_backtest_engine as base  # noqa: E402
import r11c_candidate_backtest as r11c  # noqa: E402
import r11b_param_search as r11b  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"


def build_price_below_sma_filter(regime_symbol: str = "SPY", sma_period: int = 50) -> Callable[[str, str], bool]:
    path = CACHE_DIR / f"{regime_symbol}.json"
    bars = json.loads(path.read_text())
    dates = sorted(bars.keys())
    closes = [bars[d]["close"] for d in dates]

    sma_by_date: dict[str, float | None] = {}
    for i, d in enumerate(dates):
        if i + 1 < sma_period:
            sma_by_date[d] = None
        else:
            sma_by_date[d] = sum(closes[i + 1 - sma_period:i + 1]) / sma_period
    close_by_date = dict(zip(dates, closes))

    def _filter(symbol: str, date_str: str) -> bool:
        sma = sma_by_date.get(date_str)
        px = close_by_date.get(date_str)
        if sma is None or px is None:
            return True  # insufficient regime history -> don't block
        return px >= sma

    return _filter


def build_sma_declining_filter(regime_symbol: str = "SPY", sma_period: int = 20, trend_window: int = 5) -> Callable[[str, str], bool]:
    path = CACHE_DIR / f"{regime_symbol}.json"
    bars = json.loads(path.read_text())
    dates = sorted(bars.keys())
    closes = [bars[d]["close"] for d in dates]

    sma_series: list[float | None] = [None] * len(dates)
    for i in range(len(dates)):
        if i + 1 < sma_period:
            continue
        sma_series[i] = sum(closes[i + 1 - sma_period:i + 1]) / sma_period
    sma_by_date = dict(zip(dates, sma_series))
    date_index = {d: i for i, d in enumerate(dates)}

    def _filter(symbol: str, date_str: str) -> bool:
        idx = date_index.get(date_str)
        if idx is None or idx < trend_window:
            return True
        sma_now = sma_series[idx]
        sma_prev = sma_series[idx - trend_window]
        if sma_now is None or sma_prev is None:
            return True
        return sma_now >= sma_prev  # non-declining -> allow BUY

    return _filter


VARIANTS = {
    "price_below_sma": ("SPY price >= SMA(50) required for new BUYs", build_price_below_sma_filter),
    "sma_declining": ("SPY SMA(20) non-declining over 5d required for new BUYs", build_sma_declining_filter),
}


def run_and_report(symbols: list[str], variant_key: str, notional: float = 10000.0) -> dict[str, Any]:
    label, builder = VARIANTS[variant_key]
    print(f"\n=== {variant_key}: {label} ===")
    entry_filter = builder()

    result = r11c.run_filtered_backtest(symbols, notional=notional, entry_filter=entry_filter)
    trades = result["trades"]

    price_data = base.load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    segments = r11b.compute_date_segments(all_dates)
    parts = r11b.partition_trades(trades, segments)

    baseline_path = PROJECT_ROOT / "reports" / "r11b_param_search_results.json"
    baseline_data = json.loads(baseline_path.read_text())
    baseline_default = next(
        r for r in baseline_data["grid_results"]
        if r["min_momentum"] == 0.05 and r["min_signal_strength"] == 0.40
    )

    train_s = base.summarize(parts["train"], "train")
    val_s = base.summarize(parts["validation"], "validation")
    hold_s = base.summarize(parts["holdout"], "holdout")

    print(f"  baseline (no filter): train PF={baseline_default['train']['profit_factor']} "
          f"val PF={baseline_default['validation']['profit_factor']}")
    print(f"  filtered:             train PF={train_s.get('profit_factor')} (n={train_s['n']}) "
          f"val PF={val_s.get('profit_factor')} (n={val_s['n']}) "
          f"holdout PF={hold_s.get('profit_factor')} (n={hold_s['n']})")

    return {
        "variant": variant_key,
        "label": label,
        "train": train_s,
        "validation": val_s,
        "holdout": hold_s,
        "baseline_train": baseline_default["train"],
        "baseline_validation": baseline_default["validation"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True, choices=list(VARIANTS.keys()) + ["all"])
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json"))
    to_run = list(VARIANTS.keys()) if args.variant == "all" else [args.variant]

    results = {}
    for v in to_run:
        results[v] = run_and_report(symbols, v)

    if args.save:
        out_path = PROJECT_ROOT / "reports" / "r11c2_regime_filter_results.json"
        with open(out_path, "w") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "results": results,
            }, f, indent=2, ensure_ascii=False)
        print(f"\nSaved: {out_path}")

    print("\n=== Summary ===")
    for v, r in results.items():
        def pf(s):
            p = s.get("profit_factor")
            return p if isinstance(p, (int, float)) else p
        print(f"  {v}: train_PF={pf(r['train'])} val_PF={pf(r['validation'])} holdout_PF={pf(r['holdout'])}")


if __name__ == "__main__":
    main()
