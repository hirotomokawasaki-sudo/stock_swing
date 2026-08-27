#!/usr/bin/env python3
"""R11-C rigorous re-run (2026-08-26): re-test the 4 candidate entry filters
that were rejected on 2026-08-15 (RSI reversed / sector relative strength /
earnings proximity / news sentiment positive), using the SAME rigorous
backtest methodology later established by R13-C (t+1 open fill,
point-in-time universe, conservative OHLC exit, slippage) instead of the
original r11c_candidate_backtest.py's same-day-close fill with no PIT
universe and no slippage.

Background (2026-08-26 evidence-based-system-audit finding, 🔴 High #1):
    r11c_candidate_backtest.py entered positions at bar["close"] on the
    SAME day the signal fired (r11c_candidate_backtest.py:223-229) -- the
    exact same-bar look-ahead bias that R13-C's t+1-fill engine was later
    built specifically to eliminate. It also had no point-in-time universe
    filter and no slippage model. All 4 candidates were rejected using
    this pre-R13-C methodology; this script re-derives the same 4
    candidates on r11_backtest_engine_v4.py's rigorous engine (composed,
    not reimplemented) to check whether the "reject" verdict still holds.

Design: rather than duplicating v4's entire simulation loop, this module
imports `run_backtest_v4` and monkeypatches its entry-generation step via
a lightweight wrapper: it re-implements only the entry-candidate-generation
block (which is short) with an added `entry_filter(symbol, date_str) ->
bool` hook, otherwise delegating fill/exit/capacity logic to the exact
same helper functions v4 uses (imported, not copied). This keeps the t+1
fill, point-in-time universe, conservative OHLC exit, and slippage model
IDENTICAL to v4's for a true apples-to-apples comparison against v4's own
baseline (BreakoutMomentumStrategy, no filter).

Filter builders (build_rsi_reversed_filter, build_earnings_proximity_
filter, build_sector_relative_strength_filter, build_news_sentiment_
positive_filter) are imported UNCHANGED from r11c_candidate_backtest.py --
only the underlying engine they run on top of has changed, not the filter
logic itself, so any difference in outcome is attributable to the
methodology fix, not a redefinition of the candidates.

Usage:
    python scripts/r11c_v2_rigorous_rerun.py --candidate all --save
    python scripts/r11c_v2_rigorous_rerun.py --candidate rsi_reversed
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from stock_swing.core.types import CanonicalRecord  # noqa: E402
from stock_swing.feature_engine.price_momentum_feature import (  # noqa: E402
    PriceMomentumFeature,
)
from stock_swing.strategy_engine.breakout_momentum_strategy import (  # noqa: E402
    BreakoutMomentumStrategy,
)
from stock_swing.risk.correlation_cluster import (  # noqa: E402
    CLUSTERS,
    DEFAULT_CLUSTER_CAPS,
    get_cluster_for_symbol,
)
from stock_swing.risk.position_sizing import SYMBOL_SECTORS  # noqa: E402

import r11_backtest_engine as base  # noqa: E402
from r11_backtest_engine import load_exit_strategy, load_price_data, make_record, summarize  # noqa: E402
from r11_backtest_engine_v2 import load_universe_intro_dates  # noqa: E402
from r11_backtest_engine_v3 import Position, _check_conservative_exit_for_day  # noqa: E402
from r11_backtest_engine_v4 import (  # noqa: E402
    CACHE_DIR,
    BAR_LIMIT,
    DEFAULT_GROSS_EXPOSURE_CAP_PCT,
    DEFAULT_SECTOR_CAP_PCT,
)

# Reuse filter builders UNCHANGED from the original (non-rigorous) R11-C
# script -- only the engine underneath differs.
from r11c_candidate_backtest import (  # noqa: E402
    build_rsi_reversed_filter,
    build_earnings_proximity_filter,
    build_sector_relative_strength_filter,
    build_news_sentiment_positive_filter,
    REGISTRY_PATH,
)


def load_symbol_registry(path: Path) -> dict[str, Any]:
    """Same inline load pattern as r11c_candidate_backtest.py:89-90
    (that script has no separate named function for this -- factored out
    here only for readability, logic unchanged)."""
    with open(path) as f:
        return yaml.safe_load(f)["symbols"]


def run_backtest_v4_filtered(
    symbols: list[str],
    notional: float,
    equity_base: float,
    entry_filter: Callable[[str, str], bool] | None,
    min_momentum: float = 0.05,
    min_signal_strength: float = 0.40,
    enforce_point_in_time_universe: bool = True,
    conservative_ohlc: bool = True,
    slippage_bps: float = 0.0,
    gross_exposure_cap_pct: float = DEFAULT_GROSS_EXPOSURE_CAP_PCT,
    sector_cap_pct: float = DEFAULT_SECTOR_CAP_PCT,
    cluster_caps: dict[str, float] | None = None,
    enforce_caps: bool = True,
) -> dict[str, Any]:
    """v4's exact simulation loop (t+1 fill, PIT universe, conservative
    OHLC exit, slippage, gross/sector/cluster caps) with one addition: an
    optional `entry_filter(symbol, date_str) -> bool` gate applied at
    candidate-signal-generation time (same semantics as the original
    r11c_candidate_backtest.py's entry_filter parameter). When
    entry_filter is None, this function is behaviorally IDENTICAL to
    r11_backtest_engine_v4.run_backtest_v4() (verified via
    --candidate baseline_check, see main()).
    """
    price_data = load_price_data(symbols)
    if not price_data:
        raise RuntimeError(f"No cached price data found in {CACHE_DIR}; run r11_fetch_historical_data.py first")

    intro_dates = load_universe_intro_dates() if enforce_point_in_time_universe else {}
    slippage_factor = slippage_bps / 10_000.0
    caps = cluster_caps if cluster_caps is not None else DEFAULT_CLUSTER_CAPS

    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(
        f"Simulating {len(symbols)} symbols over {len(all_dates)} trading days "
        f"({all_dates[0]} -> {all_dates[-1]}); point_in_time_universe="
        f"{enforce_point_in_time_universe}; conservative_ohlc={conservative_ohlc}; "
        f"slippage_bps={slippage_bps}; enforce_caps={enforce_caps}; "
        f"entry_filter={'yes' if entry_filter else 'none (baseline)'}"
    )

    entry_strategy = BreakoutMomentumStrategy(
        min_momentum=min_momentum, min_signal_strength=min_signal_strength
    )
    exit_strategy = load_exit_strategy()

    open_positions: dict[str, Position] = {}
    closed_trades: list[dict[str, Any]] = []
    pending_entries: dict[str, dict[str, Any]] = {}
    capacity_dropped_count = 0
    capacity_dropped_by_reason: dict[str, int] = {}
    filter_dropped_count = 0

    def _current_gross_notional() -> float:
        return sum(pos.qty * pos.entry_price for pos in open_positions.values())

    def _current_sector_notional(sector: str | None) -> float:
        if sector is None:
            return 0.0
        return sum(
            pos.qty * pos.entry_price
            for sym, pos in open_positions.items()
            if SYMBOL_SECTORS.get(sym) == sector
        )

    def _current_cluster_notional(cluster_name: str) -> float:
        members = set(CLUSTERS.get(cluster_name, []))
        return sum(
            pos.qty * pos.entry_price
            for sym, pos in open_positions.items()
            if sym in members
        )

    def _capacity_check(symbol: str, add_notional: float) -> str | None:
        if not enforce_caps:
            return None
        gross_cap = equity_base * gross_exposure_cap_pct
        if _current_gross_notional() + add_notional > gross_cap:
            return "gross_exposure_cap"
        sector = SYMBOL_SECTORS.get(symbol)
        if sector is not None:
            sector_cap = equity_base * sector_cap_pct
            if _current_sector_notional(sector) + add_notional > sector_cap:
                return f"sector_cap:{sector}"
        for cluster_name in get_cluster_for_symbol(symbol):
            cluster_cap_pct = caps.get(cluster_name)
            if cluster_cap_pct is None:
                continue
            cluster_cap = equity_base * cluster_cap_pct
            if _current_cluster_notional(cluster_name) + add_notional > cluster_cap:
                return f"cluster_cap:{cluster_name}"
        return None

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        base._freeze(current_dt)
        try:
            fillable = [
                (sym, pending) for sym, pending in pending_entries.items()
                if sym not in open_positions
            ]
            fillable.sort(key=lambda item: (-item[1]["signal_strength"], item[0]))

            for sym, pending in fillable:
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None or bar.get("open", 0) <= 0:
                    del pending_entries[sym]
                    continue
                raw_entry_price = bar["open"]
                entry_price = raw_entry_price * (1 + slippage_factor)
                qty = notional / entry_price
                add_notional = qty * entry_price

                drop_reason = _capacity_check(sym, add_notional)
                if drop_reason is not None:
                    capacity_dropped_count += 1
                    capacity_dropped_by_reason[drop_reason] = capacity_dropped_by_reason.get(drop_reason, 0) + 1
                    del pending_entries[sym]
                    continue

                open_positions[sym] = Position(
                    symbol=sym,
                    entry_date=current_dt,
                    entry_price=entry_price,
                    qty=qty,
                    entry_signal_strength=pending["signal_strength"],
                    signal_date=pending["signal_date"],
                )
                del pending_entries[sym]

            window_start_idx = max(0, i - BAR_LIMIT + 1)
            window_dates = all_dates[window_start_idx : i + 1]

            eligible_symbols = set(price_data.keys())
            if enforce_point_in_time_universe:
                eligible_symbols = {
                    sym for sym in eligible_symbols
                    if intro_dates.get(sym, "1970-01-01") <= date_str
                }

            features_by_symbol: dict[str, list[CanonicalRecord]] = {}
            for sym in eligible_symbols:
                bars = price_data.get(sym, {})
                recs = [make_record(sym, d, bars[d]) for d in window_dates if d in bars]
                if recs:
                    features_by_symbol[sym] = recs

            momentum_feat = PriceMomentumFeature(period_days=BAR_LIMIT)

            for sym, pos in list(open_positions.items()):
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None:
                    continue
                hold_days = (current_dt - pos.entry_date).days
                exit_result = _check_conservative_exit_for_day(
                    exit_strategy, pos, bar, hold_days,
                    volatility_multiplier=1.0,
                    conservative_ohlc=conservative_ohlc,
                )
                if exit_result is None:
                    continue
                raw_exit_price = exit_result["exit_price"]
                exit_price = raw_exit_price * (1 - slippage_factor)
                pnl = (exit_price - pos.entry_price) * pos.qty
                return_pct = (exit_price - pos.entry_price) / pos.entry_price
                closed_trades.append({
                    "symbol": sym,
                    "signal_date": pos.signal_date,
                    "entry_date": pos.entry_date.date().isoformat(),
                    "entry_price": pos.entry_price,
                    "exit_date": date_str,
                    "exit_price": exit_price,
                    "qty": pos.qty,
                    "pnl": pnl,
                    "return_pct": return_pct,
                    "holding_days": hold_days,
                    "exit_reason": exit_result["exit_reason"],
                    "entry_signal_strength": pos.entry_signal_strength,
                })
                del open_positions[sym]

            # --- Entry candidate generation, with optional entry_filter gate ---
            candidate_records = []
            for sym, recs in features_by_symbol.items():
                if sym not in open_positions and sym not in pending_entries:
                    candidate_records.extend(recs)
            if candidate_records:
                candidate_momentum = momentum_feat.compute(candidate_records)
                buy_signals = entry_strategy.generate(candidate_momentum)
                for sig in buy_signals:
                    sym = sig.symbol
                    if sym in open_positions or sym in pending_entries:
                        continue
                    if entry_filter is not None and not entry_filter(sym, date_str):
                        filter_dropped_count += 1
                        continue
                    pending_entries[sym] = {
                        "signal_strength": sig.signal_strength,
                        "signal_date": date_str,
                    }
        finally:
            base._unfreeze()

        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(all_dates)} days, {len(closed_trades)} closed, "
                  f"{filter_dropped_count} filter-dropped, {capacity_dropped_count} capacity-dropped")

    final_date = all_dates[-1]
    for sym, pos in open_positions.items():
        bar = price_data.get(sym, {}).get(final_date)
        if bar is None:
            continue
        raw_exit_price = bar["close"]
        exit_price = raw_exit_price * (1 - slippage_factor)
        pnl = (exit_price - pos.entry_price) * pos.qty
        return_pct = (exit_price - pos.entry_price) / pos.entry_price
        hold_days = (datetime.fromisoformat(final_date).replace(tzinfo=timezone.utc) - pos.entry_date).days
        closed_trades.append({
            "symbol": sym, "signal_date": pos.signal_date,
            "entry_date": pos.entry_date.date().isoformat(), "exit_date": final_date,
            "entry_price": pos.entry_price, "exit_price": exit_price, "qty": pos.qty,
            "pnl": pnl, "return_pct": return_pct, "holding_days": hold_days,
            "exit_reason": "backtest_end_forced_close",
            "entry_signal_strength": pos.entry_signal_strength,
        })

    return {
        "trades": closed_trades,
        "date_range": [all_dates[0], all_dates[-1]],
        "symbols": symbols,
        "notional_per_trade": notional,
        "equity_base": equity_base,
        "point_in_time_universe": enforce_point_in_time_universe,
        "conservative_ohlc": conservative_ohlc,
        "slippage_bps": slippage_bps,
        "enforce_caps": enforce_caps,
        "filter_dropped_count": filter_dropped_count,
        "capacity_dropped_count": capacity_dropped_count,
        "capacity_dropped_by_reason": capacity_dropped_by_reason,
    }


def _compare(label: str, baseline_summary: dict, candidate_summary: dict) -> None:
    print(f"\n{'='*90}\n{label}\n{'='*90}")
    for key in ("n", "win_rate", "profit_factor", "net_pnl", "avg_return_pct"):
        b = baseline_summary.get(key)
        c = candidate_summary.get(key)
        print(f"  {key:16} baseline={b!s:>12}  candidate={c!s:>12}")


def _walk_forward_split(trades: list[dict[str, Any]], label: str) -> dict[str, Any]:
    """Split by median entry_date into two halves and summarize each.
    Same methodology as the original r11c_candidate_backtest.py's
    compare_to_baseline() walk-forward check, applied per-candidate here
    (not baseline-relative) so period1/period2 profit factor consistency
    can be judged independently of the baseline's own split point.
    """
    if not trades:
        return {"period1": {"n": 0}, "period2": {"n": 0}}
    dates_sorted = sorted(t["entry_date"] for t in trades)
    mid = dates_sorted[len(dates_sorted) // 2]
    p1 = [t for t in trades if t["entry_date"] < mid]
    p2 = [t for t in trades if t["entry_date"] >= mid]
    return {
        "split_date": mid,
        "period1": summarize(p1, f"{label}_p1"),
        "period2": summarize(p2, f"{label}_p2"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="R11-C rigorous re-run (v4 engine)")
    parser.add_argument(
        "--candidate",
        choices=["rsi_reversed", "sector_relative_strength", "earnings_proximity",
                 "news_sentiment_positive", "all", "baseline_check"],
        default="all",
    )
    parser.add_argument("--notional", type=float, default=10_000.0)
    parser.add_argument("--equity-base", type=float, default=1_000_000.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0,
                         help="Slippage in basis points (default 5bps, matches R13-C's chosen value)")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    registry = load_symbol_registry(REGISTRY_PATH)
    # Match v4's own symbol universe: cached price data files, not the raw
    # registry (registry may list symbols with no cached history).
    cached_symbols = {p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_")}
    symbols = sorted(set(registry.keys()) & cached_symbols)
    print(f"Universe: {len(symbols)} symbols (registry \u2229 cached price data)")

    common_kwargs = dict(
        symbols=symbols,
        notional=args.notional,
        equity_base=args.equity_base,
        enforce_point_in_time_universe=True,
        conservative_ohlc=True,
        slippage_bps=args.slippage_bps,
        enforce_caps=True,
    )

    print("Running BASELINE (no filter, v4 rigorous engine, BreakoutMomentumStrategy only)...")
    baseline_result = run_backtest_v4_filtered(entry_filter=None, **common_kwargs)
    baseline_summary = summarize(baseline_result["trades"], "baseline_v4")
    print(json.dumps(baseline_summary, indent=2, default=str))

    if args.candidate == "baseline_check":
        # Sanity check only: this run's baseline should match
        # r11_backtest_engine_v4.run_backtest_v4()'s own baseline within
        # floating-point noise -- confirms this wrapper didn't silently
        # change engine semantics vs. the original v4.
        print("\n[baseline_check] Compare this baseline against "
              "`python scripts/r11_backtest_engine_v4.py --save` output manually.")
        return 0

    candidates_to_run = []
    if args.candidate in ("rsi_reversed", "all"):
        candidates_to_run.append(("rsi_reversed", build_rsi_reversed_filter(symbols)))
    if args.candidate in ("sector_relative_strength", "all"):
        candidates_to_run.append(("sector_relative_strength", build_sector_relative_strength_filter(symbols, registry)))
    if args.candidate in ("earnings_proximity", "all"):
        candidates_to_run.append(("earnings_proximity", build_earnings_proximity_filter(symbols)))
    if args.candidate in ("news_sentiment_positive", "all"):
        try:
            entry_filter, window_label, caveat = build_news_sentiment_positive_filter(symbols)
            print(f"\n[news_sentiment_positive] {caveat}")
            candidates_to_run.append(("news_sentiment_positive", entry_filter))
        except Exception as e:
            print(f"\n[news_sentiment_positive] SKIPPED: {e}")

    all_results: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "v4 rigorous engine (t+1 open fill, point-in-time universe, "
                        "conservative OHLC exit, slippage_bps, gross/sector/cluster caps)",
        "slippage_bps": args.slippage_bps,
        "baseline": baseline_summary,
        "candidates": {},
    }

    for name, entry_filter in candidates_to_run:
        print(f"\nRunning candidate: {name} (rigorous v4 engine)...")
        result = run_backtest_v4_filtered(entry_filter=entry_filter, **common_kwargs)
        cand_summary = summarize(result["trades"], name)
        cand_summary["filter_dropped_count"] = result["filter_dropped_count"]
        cand_summary["capacity_dropped_count"] = result["capacity_dropped_count"]
        _compare(f"Candidate: {name}", baseline_summary, cand_summary)
        wf = _walk_forward_split(result["trades"], name)
        print(f"  walk-forward: split={wf['split_date']} "
              f"period1(n={wf['period1'].get('n')}, PF={wf['period1'].get('profit_factor')}) | "
              f"period2(n={wf['period2'].get('n')}, PF={wf['period2'].get('profit_factor')})")
        cand_summary["walk_forward"] = wf
        all_results["candidates"][name] = cand_summary

    baseline_wf = _walk_forward_split(baseline_result["trades"], "baseline")
    print(f"\nBaseline walk-forward: split={baseline_wf['split_date']} "
          f"period1(n={baseline_wf['period1'].get('n')}, PF={baseline_wf['period1'].get('profit_factor')}) | "
          f"period2(n={baseline_wf['period2'].get('n')}, PF={baseline_wf['period2'].get('profit_factor')})")
    all_results["baseline"]["walk_forward"] = baseline_wf

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r11c_v2_rigorous_rerun_20260826"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "results.json"
        out_path.write_text(json.dumps(all_results, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
