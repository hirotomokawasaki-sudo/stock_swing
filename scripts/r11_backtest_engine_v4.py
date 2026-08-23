#!/usr/bin/env python3
"""R13-C (2026-08-24): R11 backtest engine v4 -- adds roadmap item 4 (cash /
gross exposure / sector / correlation-cluster cap enforcement) on top of
v3's t+1-fill + point-in-time-universe + conservative-OHLC-exit + slippage
fixes.

WHY THIS MATTERS: v1/v2/v3 all size every entry at a fixed notional (default
$10,000/trade) with NO limit on how many positions can be open
simultaneously, and no cap on how concentrated the open book gets in one
sector or correlation cluster. Every one of v3's headline numbers (PF=1.448
restricted to the live-trading window, per docs/console_improvement_
tasks.md's R13-C section) was explicitly flagged as not reflecting real
portfolio-level risk constraints. The 2026-08-15 R0-v2/R9 guardrail stress
test (console_improvement_tasks.md "R0-v2/R9付鍘") separately measured
guardrail halt/reduce_size behavior against the SAME v1-style unconstrained
trade list, but did not touch entry-side exposure/sector/cluster gating at
all -- that gap is what this v4 closes.

WHAT THIS ADDS (and nothing else -- v3's t+1 fill, point-in-time universe,
conservative OHLC exits, and slippage are all reused unmodified via
composition, not reimplemented):
  1. Gross exposure cap: total open notional (sum of all open positions'
     entry-cost basis) may not exceed `gross_exposure_cap_pct` of a fixed
     notional equity base. A new BUY signal is dropped (not queued, not
     retried) if filling it at t+1's open would breach the cap -- mirrors
     PositionSizingPolicy.size()'s shares_by_exposure REGIME_LIMITS cap
     (src/stock_swing/risk/position_sizing.py) applied at the portfolio
     level rather than per-order granularity (this backtest still uses
     fixed per-trade notional, so it cannot reproduce per-order partial
     sizing -- see Limitations below).
  2. Sector cap: reuses src/stock_swing/risk/position_sizing.py's REAL
     SYMBOL_SECTORS mapping (imported directly, not duplicated) so a
     new BUY is dropped if it would push that symbol's sector's open
     notional over `sector_cap_pct` of the equity base -- mirrors
     PositionSizingPolicy's max_sector_exposure_pct gate.
  3. Correlation cluster cap: reuses src/stock_swing/risk/
     correlation_cluster.py's REAL CLUSTERS/DEFAULT_CLUSTER_CAPS
     (imported directly) so a new BUY is dropped if it would push ANY
     cluster the symbol belongs to over its cap -- mirrors
     paper_demo.py's _filter_buys_by_cluster_cap() /
     is_buy_blocked_by_cluster_cap().

Priority order when multiple same-day BUY signals compete for limited
capacity: signals are filled in DESCENDING signal_strength order (the
strongest conviction signal gets first claim on remaining capacity), then
by symbol alphabetically for ties -- this is a simplifying assumption (real
paper_demo.py's decision ordering is more involved, see
PortfolioAllocator.filter_decisions_by_allocation()'s ETF/stock rebalance
priority), documented as a limitation below.

NOT in scope for this v4 (still open, roadmap item 6 is now covered by
src/stock_swing/research/rolling_walk_forward.py as a separate reusable
module rather than being folded into this engine -- see that module's
docstring; item 7, the trial registry, is likewise a separate reusable
module at src/stock_swing/research/trial_registry.py, not part of this
engine file):
  - Per-order partial sizing (this backtest keeps v1-v3's fixed
    notional-per-trade design; a real portfolio would size DOWN an order
    to fit remaining capacity rather than drop it entirely -- dropping is
    more conservative, i.e. UNDERSTATES how much exposure a real system
    would take, not overstates it)
  - PortfolioAllocator's ETF/Stock 85/15 allocation band (separate concern
    from gross/sector/cluster caps; this v4 does not classify by ETF vs
    stock at all)
  - Any use of the REAL current account equity as the cap denominator --
    equity_base is a fixed constant for the whole backtest (matching v1-v3's
    fixed-notional design), not a running mark-to-market equity curve.

Usage:
    python scripts/r11_backtest_engine_v4.py [--gross-exposure-cap-pct 0.75] [--save]
    python scripts/r11_backtest_engine_v4.py --compare-v3   # side-by-side vs v3 (no caps)
    python scripts/r11_backtest_engine_v4.py --record-trial --roadmap-item R13-C-item4
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

from r11_backtest_engine import (  # noqa: E402
    _freeze,
    _unfreeze,
    decile_summary,
    load_exit_strategy,
    load_price_data,
    make_record,
    summarize,
)
from r11_backtest_engine_v2 import load_universe_intro_dates  # noqa: E402
from r11_backtest_engine_v3 import (  # noqa: E402
    Position,
    _check_conservative_exit_for_day,
)

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
BAR_LIMIT = 20

DEFAULT_GROSS_EXPOSURE_CAP_PCT = 0.75  # matches REGIME_LIMITS["neutral"] in position_sizing.py
DEFAULT_SECTOR_CAP_PCT = 0.55          # matches DEFAULT_MAX_SECTOR_EXPOSURE_PCT in position_sizing.py


def run_backtest_v4(
    symbols: list[str],
    notional: float,
    equity_base: float,
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
    """v3's simulation loop + entry-side gross/sector/cluster exposure caps.

    Args:
        equity_base: Fixed notional-equity denominator used for all three
            caps (gross_exposure_cap_pct * equity_base = max total open
            notional, etc.). Matches v1-v3's fixed-notional-per-trade
            design philosophy (no running equity curve).
        gross_exposure_cap_pct: Max total open notional as a fraction of
            equity_base.
        sector_cap_pct: Max per-sector open notional as a fraction of
            equity_base (sector membership from the REAL
            position_sizing.SYMBOL_SECTORS mapping).
        cluster_caps: Per-cluster cap fractions (defaults to the REAL
            correlation_cluster.DEFAULT_CLUSTER_CAPS).
        enforce_caps: When False, behaves identically to v3 (no capacity
            gating at all) -- used for --compare-v3's side-by-side run
            without needing to re-import v3 separately.
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
        f"slippage_bps={slippage_bps}; enforce_caps={enforce_caps} "
        f"(gross={gross_exposure_cap_pct:.0%}, sector={sector_cap_pct:.0%}, "
        f"equity_base=${equity_base:,.0f})"
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
        """Return a drop-reason string if adding add_notional for symbol
        would breach any cap, else None (allowed)."""
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
        _freeze(current_dt)
        try:
            # --- 0. Fill pending entries at today's open (+ slippage), ---
            # --- gated by remaining gross/sector/cluster capacity, ---
            # --- strongest signal_strength first. ---
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
                add_notional = qty * entry_price  # == notional, kept explicit for clarity

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

            # --- 1. Check exits for open positions (conservative OHLC path) ---
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

            # --- 2. Generate entry candidate signals from TODAY's close ---
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
                    pending_entries[sym] = {
                        "signal_strength": sig.signal_strength,
                        "signal_date": date_str,
                    }
        finally:
            _unfreeze()

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(all_dates)} days simulated, "
                  f"{len(closed_trades)} closed, {len(open_positions)} open, "
                  f"{len(pending_entries)} pending fill, "
                  f"{capacity_dropped_count} capacity-dropped")

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
            "symbol": sym,
            "signal_date": pos.signal_date,
            "entry_date": pos.entry_date.date().isoformat(),
            "exit_date": final_date,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "qty": pos.qty,
            "pnl": pnl,
            "return_pct": return_pct,
            "holding_days": hold_days,
            "exit_reason": "backtest_end_forced_close",
            "entry_signal_strength": pos.entry_signal_strength,
        })

    return {
        "trades": closed_trades,
        "date_range": [all_dates[0], all_dates[-1]],
        "symbols": symbols,
        "notional_per_trade": notional,
        "equity_base": equity_base,
        "min_momentum": min_momentum,
        "min_signal_strength": min_signal_strength,
        "point_in_time_universe": enforce_point_in_time_universe,
        "conservative_ohlc": conservative_ohlc,
        "slippage_bps": slippage_bps,
        "enforce_caps": enforce_caps,
        "gross_exposure_cap_pct": gross_exposure_cap_pct,
        "sector_cap_pct": sector_cap_pct,
        "dropped_pending_at_end": len(pending_entries),
        "capacity_dropped_count": capacity_dropped_count,
        "capacity_dropped_by_reason": capacity_dropped_by_reason,
    }


def _live_window_summary(trades: list[dict], label: str, cutoff: str = "2026-05-12") -> None:
    live = [t for t in trades if t["entry_date"] >= cutoff]
    if not live:
        print(f"  {label}: no trades in live window")
        return
    s = summarize(live, label)
    print(f"  {label} (entry_date >= {cutoff}): n={s['n']} WR={s.get('win_rate')} "
          f"PF={s.get('profit_factor')} net=${s.get('net_pnl')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None, help="Comma-separated; default = all cached")
    parser.add_argument("--notional", type=float, default=10000.0)
    parser.add_argument("--equity-base", type=float, default=1_000_000.0,
                         help="Fixed equity denominator for gross/sector/cluster cap pct math")
    parser.add_argument("--slippage-bps", type=float, default=10.0)
    parser.add_argument("--gross-exposure-cap-pct", type=float, default=DEFAULT_GROSS_EXPOSURE_CAP_PCT)
    parser.add_argument("--sector-cap-pct", type=float, default=DEFAULT_SECTOR_CAP_PCT)
    parser.add_argument("--no-conservative-ohlc", action="store_true")
    parser.add_argument("--no-point-in-time-universe", action="store_true")
    parser.add_argument("--no-caps", action="store_true", help="Disable gross/sector/cluster caps entirely (v3-equivalent)")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--compare-v3", action="store_true",
                         help="Also run with caps disabled for a side-by-side diff")
    parser.add_argument("--record-trial", action="store_true",
                         help="Log this run to the R13-C trial registry (data/research/trial_registry.jsonl)")
    parser.add_argument("--roadmap-item", default="R13-C-item4")
    args = parser.parse_args()

    if args.symbols:
        symbols = args.symbols.split(",")
    else:
        symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_"))

    result = run_backtest_v4(
        symbols,
        notional=args.notional,
        equity_base=args.equity_base,
        enforce_point_in_time_universe=not args.no_point_in_time_universe,
        conservative_ohlc=not args.no_conservative_ohlc,
        slippage_bps=args.slippage_bps,
        gross_exposure_cap_pct=args.gross_exposure_cap_pct,
        sector_cap_pct=args.sector_cap_pct,
        enforce_caps=not args.no_caps,
    )
    trades = result["trades"]
    overall = summarize(trades, "v4_full")
    print(f"\nTotal v4 trades: {len(trades)} (dropped_pending_at_end={result['dropped_pending_at_end']}, "
          f"capacity_dropped={result['capacity_dropped_count']})")
    print(f"Capacity drop breakdown: {result['capacity_dropped_by_reason']}")
    print(f"Overall (v4, caps={'ON' if result['enforce_caps'] else 'OFF'}): "
          f"n={overall['n']} WR={overall.get('win_rate')} PF={overall.get('profit_factor')} "
          f"net=${overall.get('net_pnl')}")
    _live_window_summary(trades, "v4_full live-window-only")

    deciles = decile_summary(trades)
    print("\nDecile breakdown (by entry_signal_strength):")
    for row in deciles:
        print(f"  {row}")

    variants: dict[str, list[dict]] = {"v4 (caps ON)": trades}

    if args.compare_v3:
        v3_equivalent = run_backtest_v4(
            symbols, notional=args.notional, equity_base=args.equity_base,
            enforce_point_in_time_universe=not args.no_point_in_time_universe,
            conservative_ohlc=not args.no_conservative_ohlc,
            slippage_bps=args.slippage_bps,
            enforce_caps=False,
        )["trades"]
        variants["v3-equivalent (caps OFF)"] = v3_equivalent

    if len(variants) > 1:
        print("\n" + "=" * 90)
        print("VARIANT COMPARISON")
        print("=" * 90)
        for label, ts in variants.items():
            s = summarize(ts, label)
            print(f"\n  {label}:")
            print(f"    all:         n={s['n']:4d} WR={s.get('win_rate')} PF={s.get('profit_factor')} net=${s.get('net_pnl')}")
            _live_window_summary(ts, "    live-window")

    if args.record_trial:
        from stock_swing.research.trial_registry import TrialRecord, TrialRegistry
        registry = TrialRegistry()
        registry.record(TrialRecord(
            script="r11_backtest_engine_v4.py",
            roadmap_item=args.roadmap_item,
            params={
                "gross_exposure_cap_pct": args.gross_exposure_cap_pct,
                "sector_cap_pct": args.sector_cap_pct,
                "slippage_bps": args.slippage_bps,
                "enforce_caps": not args.no_caps,
            },
            data_window={"start": result["date_range"][0], "end": result["date_range"][1]},
            segment="full",
            n_trades=overall.get("n"),
            profit_factor=overall.get("profit_factor"),
            win_rate=overall.get("win_rate"),
            net_pnl=overall.get("net_pnl"),
            notes=f"capacity_dropped={result['capacity_dropped_count']}",
        ))
        print(f"\nRecorded trial to {registry.path}")

    if args.save:
        out_path = PROJECT_ROOT / "reports" / "r11_backtest_v4_results.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "config": {
                    "symbols": symbols,
                    "notional_per_trade": args.notional,
                    "equity_base": args.equity_base,
                    "date_range": result["date_range"],
                    "point_in_time_universe": result["point_in_time_universe"],
                    "conservative_ohlc": result["conservative_ohlc"],
                    "slippage_bps": result["slippage_bps"],
                    "enforce_caps": result["enforce_caps"],
                    "gross_exposure_cap_pct": result["gross_exposure_cap_pct"],
                    "sector_cap_pct": result["sector_cap_pct"],
                },
                "overall": overall,
                "capacity_dropped_count": result["capacity_dropped_count"],
                "capacity_dropped_by_reason": result["capacity_dropped_by_reason"],
                "decile_summary": deciles,
                "trades": trades,
            }, f, indent=2, ensure_ascii=False)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
