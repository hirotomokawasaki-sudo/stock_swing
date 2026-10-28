#!/usr/bin/env python3
"""R14 (2026-08-25): Dip-buy / mean-reversion feasibility check (Phase 1).

QUESTION (from user, 2026-08-25 session): "下がり局面であればある意味買い時
なのでは" -- during a broad drawdown (e.g. the 2026-08-24 semiconductor
sell-off that pushed the circuit breaker into block_buys), wouldn't buying
INTO the drop be an opportunity rather than something to guard against?
This script tests that idea empirically, and separately measures how much
a dip-buy strategy would compete with the EXISTING breakout_momentum_v1
strategy for capital/positions if both ran simultaneously.

THIS IS A PHASE 1 FEASIBILITY CHECK ONLY, following the exact same pattern
already used and validated for R13-D (ETF sector rotation) and the JP
semiconductor overnight-spillover roadmap item: pure research over the
SAME cached 2-year daily price data already used for R13-C
(data/r11_price_cache/, 2024-08-15 to 2026-08-14), no production wiring,
no shadow logging, no strategy-engine changes. GO/NO-GO here only decides
whether a Phase 2 (real strategy design) is worth attempting.

ENTRY RULE TESTED: mirror image of BreakoutMomentumStrategy's own entry
condition. Breakout buys when trailing N-day momentum >= +min_momentum
AND PriceMomentumFeature classifies trend=="bullish". This script buys
when trailing N-day momentum <= -min_momentum_drop AND trend=="bearish"
(the feature's own bearish classification, unchanged, same N=20 bar_limit
paper_demo.py actually uses -- see load momentum feature call below). This
is the simplest, least-tunable "buy the dip" rule that is a direct mirror
of the strategy already in production, which keeps this a fair apples-to-
apples comparison rather than a cherry-picked new indicator.

EXIT RULE: reuses the SAME production SimpleExitV2Strategy config
(load_exit_strategy(), unchanged) that both breakout_momentum_v1 and this
dip-buy test would exit through in a real run -- so any PF/WR difference
is attributable to the ENTRY rule, not a different exit design.

FILL / COST MODEL: reuses r11_backtest_engine_v3's conservative-OHLC-exit
+ t+1-open-fill + slippage machinery verbatim (imported, not reimplemented)
so results are on equal footing with the R13-C headline PF=1.453
(2026-08-24) figure already used for the momentum strategy's own
Go/No-Go evidence.

OVERLAP / COMPATIBILITY MEASUREMENT: separately runs the EXISTING
BreakoutMomentumStrategy over the identical universe/period and records,
for every dip-buy entry, whether momentum already held (or was pending
entry into) the same symbol on that date -- this directly answers "would
these two compete for the same position slot" without needing to touch
any shared-risk-layer code (cluster cap / rolling PF gate / circuit
breaker), which are portfolio-level and out of scope for a raw-signal
Phase 1 check (same scoping rule R13-D Phase 1 used).

LIMITATIONS (explicit):
  - No transaction-cost-free "signal only" claim here (unlike R13-D
    Phase 1) -- fills/slippage ARE modeled because unlike sector rotation,
    dip-buying's viability is highly sensitive to whipsaw/stop-loss
    churn, which no-cost modeling would hide.
  - Only ONE entry-rule shape tested (mirror of the existing breakout
    momentum threshold). No parameter grid search across drop depth /
    lookback window -- deliberately, to avoid the overfitting risk R13-C
    repeatedly flagged for parameter tuning without out-of-sample checks.
  - Point-in-time universe and fixed $10,000/trade notional, one open
    position per symbol -- same simplifications as r11_backtest_engine_v3.
  - Does not model the shared risk layers (circuit breaker,
    rolling-PF entry_filter Gate 3, correlation cluster cap,
    PortfolioAllocator ETF/stock band) that a real wired-in dip-buy
    strategy would also have to pass; those interact at the PORTFOLIO
    level and require live paper data, not a Phase 1 raw-signal check.

Usage:
    python scripts/r14_dip_buy_meanreversion_phase1.py [--min-momentum-drop 0.05] [--save]
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

from stock_swing.feature_engine.price_momentum_feature import (  # noqa: E402
    PriceMomentumFeature,
)
from stock_swing.strategy_engine.base_strategy import BaseStrategy, CandidateSignal  # noqa: E402
from stock_swing.strategy_engine.breakout_momentum_strategy import (  # noqa: E402
    BreakoutMomentumStrategy,
)

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
    BAR_LIMIT,
    CACHE_DIR,
    Position,
    _check_conservative_exit_for_day,
)

LIVE_WINDOW_CUTOFF = "2026-05-12"  # matches R13-C's existing live-window convention


class DipBuyMeanReversionStrategy(BaseStrategy):
    """Mirror image of BreakoutMomentumStrategy: buy on a trailing N-day
    DROP instead of a trailing N-day RISE. Same signal-strength formula
    shape (magnitude-scaled), same trend-classification dependency
    (PriceMomentumFeature's own bearish/bullish/neutral labels, unchanged).
    """

    strategy_id = "dip_buy_meanreversion_v1_SPIKE"

    def __init__(self, min_momentum_drop: float = 0.05, min_signal_strength: float = 0.40):
        self.min_momentum_drop = min_momentum_drop
        self.min_signal_strength = min_signal_strength

    def generate(self, features):
        momentum_features = [f for f in features if f.feature_name == "price_momentum" and f.symbol]
        signals = []
        now = datetime.now(timezone.utc)
        BLOCKING_QUALITY_FLAGS = {"stale_data", "insufficient_bars", "insufficient_price_data"}

        for mf in momentum_features:
            symbol = mf.symbol
            quality_flags = set(mf.quality_flags or [])
            if quality_flags & BLOCKING_QUALITY_FLAGS:
                continue
            momentum = mf.values.get("momentum", 0.0)
            trend = mf.values.get("trend", "unknown")

            # Mirror image of breakout's `momentum >= min_momentum and trend == "bullish"`
            if momentum <= -self.min_momentum_drop and trend == "bearish":
                magnitude = abs(momentum) - self.min_momentum_drop
                signal_strength = min(1.0, 0.40 + magnitude * 3.0)
                signal_strength = max(self.min_signal_strength, round(signal_strength, 4))
                signals.append(
                    CandidateSignal(
                        strategy_id=self.strategy_id,
                        symbol=symbol,
                        action="buy",
                        signal_strength=signal_strength,
                        generated_at=now,
                        time_horizon="1w",
                        confidence=0.60,
                        reasoning=f"Mean-reversion dip candidate: {momentum*100:.1f}% trailing momentum",
                        metadata={"momentum_pct": momentum * 100.0},
                    )
                )
        return signals


def run_dip_buy_backtest(
    symbols: list[str],
    notional: float,
    min_momentum_drop: float,
    min_signal_strength: float,
    slippage_bps: float,
    track_momentum_overlap: bool = True,
    enforce_point_in_time_universe: bool = True,
) -> dict[str, Any]:
    price_data = load_price_data(symbols)
    if not price_data:
        raise RuntimeError(f"No cached price data found in {CACHE_DIR}; run r11_fetch_historical_data.py first")

    intro_dates = load_universe_intro_dates() if enforce_point_in_time_universe else {}
    slippage_factor = slippage_bps / 10_000.0

    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(
        f"Simulating dip-buy strategy: {len(symbols)} symbols, {len(all_dates)} days "
        f"({all_dates[0]} -> {all_dates[-1]}), min_momentum_drop={min_momentum_drop}, "
        f"slippage_bps={slippage_bps}"
    )

    dip_strategy = DipBuyMeanReversionStrategy(min_momentum_drop=min_momentum_drop, min_signal_strength=min_signal_strength)
    momentum_strategy = BreakoutMomentumStrategy(min_momentum=0.05, min_signal_strength=0.40)
    exit_strategy = load_exit_strategy()

    open_positions: dict[str, Position] = {}
    closed_trades: list[dict[str, Any]] = []
    pending_entries: dict[str, dict[str, Any]] = {}

    # Shadow-track momentum strategy's own open/pending set purely to measure
    # overlap (this does NOT affect the dip-buy simulation's fills at all).
    momentum_open: dict[str, str] = {}       # symbol -> entry_date (open position)
    momentum_pending: set[str] = set()
    overlap_events: list[dict[str, Any]] = []

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        _freeze(current_dt)
        try:
            for sym, pending in list(pending_entries.items()):
                if sym in open_positions:
                    del pending_entries[sym]
                    continue
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None or bar.get("open", 0) <= 0:
                    del pending_entries[sym]
                    continue
                raw_entry_price = bar["open"]
                entry_price = raw_entry_price * (1 + slippage_factor)
                qty = notional / entry_price
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

            if enforce_point_in_time_universe:
                eligible_symbols = {
                    sym for sym in price_data.keys()
                    if intro_dates.get(sym, "1970-01-01") <= date_str
                }
            else:
                eligible_symbols = set(price_data.keys())

            features_by_symbol = {}
            for sym in eligible_symbols:
                bars = price_data.get(sym, {})
                recs = [make_record(sym, d, bars[d]) for d in window_dates if d in bars]
                if recs:
                    features_by_symbol[sym] = recs

            momentum_feat = PriceMomentumFeature(period_days=BAR_LIMIT)

            # --- Exits for open dip-buy positions ---
            for sym, pos in list(open_positions.items()):
                bar = price_data.get(sym, {}).get(date_str)
                if bar is None:
                    continue
                hold_days = (current_dt - pos.entry_date).days
                exit_result = _check_conservative_exit_for_day(
                    exit_strategy, pos, bar, hold_days, volatility_multiplier=1.0, conservative_ohlc=True,
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

            # --- Generate dip-buy candidates from today's close ---
            candidate_records = []
            for sym, recs in features_by_symbol.items():
                if sym not in open_positions and sym not in pending_entries:
                    candidate_records.extend(recs)
            if candidate_records:
                candidate_momentum = momentum_feat.compute(candidate_records)
                buy_signals = dip_strategy.generate(candidate_momentum)

                # Independently compute what breakout_momentum_v1 would say
                # about the SAME candidate set on the SAME day, purely for
                # overlap bookkeeping (shadow -- consumes no capacity).
                if track_momentum_overlap:
                    momentum_signals = momentum_strategy.generate(candidate_momentum)
                    for msig in momentum_signals:
                        if msig.symbol not in momentum_open and msig.symbol not in momentum_pending:
                            momentum_pending.add(msig.symbol)
                    # Age out momentum_pending -> momentum_open after "fill" (next day);
                    # simplified: treat pending as open immediately for overlap purposes
                    # since we only care about "would compete for the same symbol slot".
                    for s in list(momentum_pending):
                        momentum_open[s] = date_str
                    momentum_pending.clear()
                    # Expire momentum_open entries older than max_hold_days (20d) as a
                    # simplification (real momentum backtest has its own exact exits;
                    # this is intentionally approximate since it's a shadow overlap
                    # measurement, not a second full backtest).
                    for s in list(momentum_open):
                        entry_dt = datetime.fromisoformat(momentum_open[s])
                        if (current_dt.replace(tzinfo=None) - entry_dt).days > 20:
                            del momentum_open[s]

                for sig in buy_signals:
                    sym = sig.symbol
                    if sym in open_positions or sym in pending_entries:
                        continue
                    if track_momentum_overlap and sym in momentum_open:
                        overlap_events.append({
                            "date": date_str,
                            "symbol": sym,
                            "note": "dip_buy_signal_fired_while_momentum_would_also_hold_same_symbol",
                        })
                    pending_entries[sym] = {"signal_strength": sig.signal_strength, "signal_date": date_str}
        finally:
            _unfreeze()

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(all_dates)} days, {len(closed_trades)} closed, {len(open_positions)} open")

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
            "symbol": sym, "signal_date": pos.signal_date, "entry_date": pos.entry_date.date().isoformat(),
            "exit_date": final_date, "entry_price": pos.entry_price, "exit_price": exit_price,
            "qty": pos.qty, "pnl": pnl, "return_pct": return_pct, "holding_days": hold_days,
            "exit_reason": "backtest_end_forced_close", "entry_signal_strength": pos.entry_signal_strength,
        })

    return {
        "trades": closed_trades,
        "overlap_events": overlap_events,
        "date_range": [all_dates[0], all_dates[-1]],
        "symbols": symbols,
        "notional_per_trade": notional,
        "min_momentum_drop": min_momentum_drop,
        "min_signal_strength": min_signal_strength,
        "slippage_bps": slippage_bps,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--notional", type=float, default=10000.0)
    parser.add_argument("--min-momentum-drop", type=float, default=0.05,
                         help="Same magnitude as BreakoutMomentumStrategy's min_momentum=0.05, mirrored to negative")
    parser.add_argument("--min-signal-strength", type=float, default=0.40)
    parser.add_argument("--slippage-bps", type=float, default=10.0)
    parser.add_argument("--no-point-in-time-universe", action="store_true",
                         help="Disable point-in-time universe gating (uses full "
                              "2024-08 - 2026-08 cached window for all symbols; "
                              "same caveat as r11_backtest_engine_v2/v3's own "
                              "--no-point-in-time-universe flag)")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    if args.symbols:
        symbols = args.symbols.split(",")
    else:
        symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_"))

    result = run_dip_buy_backtest(
        symbols,
        notional=args.notional,
        min_momentum_drop=args.min_momentum_drop,
        min_signal_strength=args.min_signal_strength,
        slippage_bps=args.slippage_bps,
        enforce_point_in_time_universe=not args.no_point_in_time_universe,
    )
    trades = result["trades"]
    print(f"\nTotal dip-buy trades: {len(trades)}")

    overall = summarize(trades, "overall")
    print(f"Overall: n={overall['n']} WR={overall.get('win_rate')} PF={overall.get('profit_factor')} net=${overall.get('net_pnl')}")

    live = [t for t in trades if t["entry_date"] >= LIVE_WINDOW_CUTOFF]
    live_summary = summarize(live, f"live_window(>= {LIVE_WINDOW_CUTOFF})")
    print(f"Live window: n={live_summary['n']} WR={live_summary.get('win_rate')} PF={live_summary.get('profit_factor')} net=${live_summary.get('net_pnl')}")

    by_reason: dict[str, dict[str, Any]] = {}
    for t in trades:
        by_reason.setdefault(t["exit_reason"], []).append(t)
    print("\nExit reason breakdown:")
    for reason, ts in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        s = summarize(ts, reason)
        print(f"  {reason}: n={s['n']} WR={s.get('win_rate')} PF={s.get('profit_factor')} net=${s.get('net_pnl')}")

    overlap = result["overlap_events"]
    print(f"\nOverlap events (dip-buy fires on a symbol momentum would also hold): {len(overlap)} / {len(trades)} dip-buy signals total")
    if overlap:
        overlap_symbols = sorted({e["symbol"] for e in overlap})
        print(f"  Symbols involved: {overlap_symbols}")

    deciles = decile_summary(trades)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roadmap_item": "R14-dip-buy-meanreversion-phase1",
        "overall": overall,
        "live_window": live_summary,
        "by_exit_reason": {r: summarize(ts, r) for r, ts in by_reason.items()},
        "decile_summary": deciles,
        "overlap_event_count": len(overlap),
        "overlap_events_sample": overlap[:30],
        "config": {
            "min_momentum_drop": args.min_momentum_drop,
            "min_signal_strength": args.min_signal_strength,
            "slippage_bps": args.slippage_bps,
            "notional_per_trade": args.notional,
            "date_range": result["date_range"],
        },
        "trade_count": len(trades),
    }

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r14_dip_buy_meanreversion_phase1_20260825"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "backtest_result.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        trades_path = out_dir / "trades.json"
        with open(trades_path, "w") as f:
            json.dump(trades, f, indent=2, default=str)
        print(f"\nSaved: {out_path}")
        print(f"Saved: {trades_path}")


if __name__ == "__main__":
    main()
