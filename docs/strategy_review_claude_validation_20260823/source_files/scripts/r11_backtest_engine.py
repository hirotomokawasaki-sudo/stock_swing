#!/usr/bin/env python3
"""R11-A/B: Historical backtest harness that calls the REAL production code
(PriceMomentumFeature, BreakoutMomentumStrategy, SimpleExitV2Strategy)
against 2 years of cached daily OHLCV data (scripts/r11_fetch_historical_data.py).

Why not use src/stock_swing/backtest/engine_v2.py: that engine (a) simulates
price movement with `random.uniform(-0.02, 0.03)` per day instead of real
prices when use_real_prices=False, and (b) implements its own independent
stop_loss/take_profit/max_hold exit rules rather than calling
SimpleExitV2Strategy -- it does not reflect any of the improvements shipped
since 2026-05 (trailing stop, staged trailing, staged breakeven, tiered
min_hold, volatility-adjusted stop). It is not usable for R11-B without a
substantial rewrite, so this script re-implements only the *simulation loop*
and delegates all trading-logic decisions to the actual production classes.

Design:
  - Both PriceMomentumFeature and SimpleExitV2Strategy call
    `datetime.now(timezone.utc)` directly (not via an injectable clock).
    We monkeypatch each module's `datetime` name to a frozen subclass for
    the duration of each simulated day, so "now" tracks the simulated date
    instead of wall-clock time. This is the standard technique for freezing
    time in code that wasn't written with a clock dependency injected, and
    avoids adding a new test-only dependency (freezegun is not installed).
  - Entry price = same-day close (approximation; production makes intraday
    decisions off latest quote/bar, but only daily bars are available here).
  - Exit price = same-day close, using the same SimpleExitV2Strategy that
    runs in production (loaded from config/strategy/simple_exit_v2.yaml,
    identical to how paper_demo.py constructs it).
  - Position notional is fixed (default $10,000) so profit factor is not
    distorted by price level differences across symbols; return_pct is also
    reported per-decile as a sizing-independent cross-check.
  - One open position per symbol at a time (same implicit constraint as
    production risk validation for duplicate positions).

Usage:
    python scripts/r11_backtest_engine.py [--symbols AAPL,MSFT] [--notional 10000]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.core.types import CanonicalRecord  # noqa: E402
from stock_swing.feature_engine.price_momentum_feature import (  # noqa: E402
    PriceMomentumFeature,
)
import stock_swing.feature_engine.price_momentum_feature as _pmf_module  # noqa: E402
from stock_swing.strategy_engine.breakout_momentum_strategy import (  # noqa: E402
    BreakoutMomentumStrategy,
)
from stock_swing.strategy_engine.simple_exit_v2_strategy import (  # noqa: E402
    SimpleExitV2Strategy,
)
import stock_swing.strategy_engine.simple_exit_v2_strategy as _sev2_module  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
EXIT_CONFIG_PATH = PROJECT_ROOT / "config" / "strategy" / "simple_exit_v2.yaml"
BAR_LIMIT = 20  # matches paper_demo.py --bar-limit default


class _FrozenDatetime(datetime):
    """datetime subclass whose .now() always returns a fixed instant.

    Assigned over a module's `datetime` name (not the global stdlib module)
    so only the target module's `datetime.now(...)` calls are affected.
    """

    _frozen_now: datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is None:
            return cls._frozen_now
        return cls._frozen_now.astimezone(tz)


def _freeze(day: datetime) -> None:
    _FrozenDatetime._frozen_now = day
    _pmf_module.datetime = _FrozenDatetime
    _sev2_module.datetime = _FrozenDatetime


def _unfreeze() -> None:
    _pmf_module.datetime = datetime
    _sev2_module.datetime = datetime


def load_exit_strategy() -> SimpleExitV2Strategy:
    """Build SimpleExitV2Strategy from the live production config file,
    identical to how paper_demo.py constructs it (src/stock_swing/cli/
    paper_demo.py ~line 1276), so the backtest exercises the exact same
    exit rules currently running in paper/live.
    """
    with open(EXIT_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    return SimpleExitV2Strategy(
        stop_loss_pct=cfg.get("stop_loss_pct", -0.07),
        breakeven_activation_pct=cfg.get("breakeven_activation_pct", 0.03),
        trailing_activation_pct=cfg.get("trailing_activation_pct", 0.08),
        trailing_stop_pct=cfg.get("trailing_stop_pct", 0.04),
        max_hold_days=cfg.get("max_hold_days", 20),
        staged_trailing_enabled=cfg.get("staged_trailing_enabled", False),
        staged_trailing_levels=cfg.get("staged_trailing_levels", []),
        min_hold_days=cfg.get("min_hold_days", 1),
        min_hold_days_enabled=cfg.get("min_hold_days_enabled", True),
        emergency_stop_bypass_pct=cfg.get("emergency_stop_bypass_pct", -0.12),
        tiered_min_hold_enabled=cfg.get("tiered_min_hold_enabled", False),
        tiered_min_hold_levels=cfg.get("tiered_min_hold_levels", []),
        broker_recon_graduation_days=cfg.get("broker_recon_graduation_days", 5),
        staged_breakeven_enabled=cfg.get("staged_breakeven_enabled", False),
        staged_breakeven_levels=cfg.get("staged_breakeven_levels", []),
        volatility_adjusted_stop_enabled=cfg.get("volatility_adjusted_stop_enabled", False),
        volatility_multiplier_min=cfg.get("volatility_multiplier_min", 0.5),
        volatility_multiplier_max=cfg.get("volatility_multiplier_max", 1.75),
    )


def load_price_data(symbols: list[str]) -> dict[str, dict[str, dict[str, float]]]:
    data: dict[str, dict[str, dict[str, float]]] = {}
    for sym in symbols:
        path = CACHE_DIR / f"{sym}.json"
        if not path.exists():
            continue
        with open(path) as f:
            data[sym] = json.load(f)
    return data


def make_record(symbol: str, date_str: str, bar: dict[str, float]) -> CanonicalRecord:
    event_time = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
    return CanonicalRecord(
        record_id=f"r11_{symbol}_{date_str}",
        schema_version="v1",
        source="r11_yfinance_cache",
        source_type="price",
        symbol=symbol,
        event_type="bar_daily",
        event_time=event_time,
        as_of=event_time.isoformat(),
        ingested_at=event_time,
        timezone="UTC",
        payload_version="v1",
        payload={
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar.get("volume", 0),
        },
        quality_flags=[],
    )


class Position:
    __slots__ = ("symbol", "entry_date", "entry_price", "qty", "peak_price",
                 "entry_signal_strength")

    def __init__(self, symbol, entry_date, entry_price, qty, entry_signal_strength):
        self.symbol = symbol
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.qty = qty
        self.peak_price = entry_price
        self.entry_signal_strength = entry_signal_strength


def run_backtest(
    symbols: list[str],
    notional: float,
    min_momentum: float = 0.05,
    min_signal_strength: float = 0.40,
) -> dict[str, Any]:
    price_data = load_price_data(symbols)
    if not price_data:
        raise RuntimeError(f"No cached price data found in {CACHE_DIR}; run r11_fetch_historical_data.py first")

    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(f"Simulating {len(symbols)} symbols over {len(all_dates)} trading days "
          f"({all_dates[0]} -> {all_dates[-1]})")

    entry_strategy = BreakoutMomentumStrategy(
        min_momentum=min_momentum, min_signal_strength=min_signal_strength
    )
    exit_strategy = load_exit_strategy()

    open_positions: dict[str, Position] = {}
    closed_trades: list[dict[str, Any]] = []

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        _freeze(current_dt)
        try:
            # Build a rolling BAR_LIMIT-day window of records per symbol
            # (mirrors PriceMomentumFeature's assumption that "records" IS
            # the lookback window, not an unbounded history).
            window_start_idx = max(0, i - BAR_LIMIT + 1)
            window_dates = all_dates[window_start_idx : i + 1]

            features_by_symbol: dict[str, list[CanonicalRecord]] = {}
            for sym, bars in price_data.items():
                recs = [make_record(sym, d, bars[d]) for d in window_dates if d in bars]
                if recs:
                    features_by_symbol[sym] = recs

            momentum_feat = PriceMomentumFeature(period_days=BAR_LIMIT)
            all_records: list[CanonicalRecord] = []
            for recs in features_by_symbol.values():
                all_records.extend(recs)
            momentum_results = momentum_feat.compute(all_records)
            momentum_by_symbol = {r.symbol: r for r in momentum_results}

            # --- 1. Check exits for open positions -------------------------
            if open_positions:
                current_positions_payload = {}
                for sym, pos in open_positions.items():
                    bar = price_data.get(sym, {}).get(date_str)
                    if bar is None:
                        continue
                    close_px = bar["close"]
                    pos.peak_price = max(pos.peak_price, close_px)
                    current_positions_payload[sym] = {
                        "qty": pos.qty,
                        "avg_entry_price": pos.entry_price,
                        "current_price": close_px,
                        "peak_price": pos.peak_price,
                        "created_at": pos.entry_date.isoformat(),
                        "entry_signal_strength": pos.entry_signal_strength,
                    }

                if current_positions_payload:
                    exit_signals = exit_strategy.generate(
                        features=list(momentum_results),
                        current_positions=current_positions_payload,
                    )
                    for sig in exit_signals:
                        sym = sig.symbol
                        pos = open_positions.get(sym)
                        if pos is None:
                            continue
                        exit_price = sig.metadata.get("current_price", price_data[sym][date_str]["close"])
                        pnl = (exit_price - pos.entry_price) * pos.qty
                        return_pct = (exit_price - pos.entry_price) / pos.entry_price
                        hold_days = (current_dt - pos.entry_date).days
                        closed_trades.append({
                            "symbol": sym,
                            "entry_date": pos.entry_date.date().isoformat(),
                            "entry_price": pos.entry_price,
                            "exit_date": date_str,
                            "exit_price": exit_price,
                            "qty": pos.qty,
                            "pnl": pnl,
                            "return_pct": return_pct,
                            "holding_days": hold_days,
                            "exit_reason": sig.metadata.get("exit_trigger", "unknown"),
                            "entry_signal_strength": pos.entry_signal_strength,
                        })
                        del open_positions[sym]

            # --- 2. Check entries for symbols without an open position -----
            candidate_records = []
            for sym, recs in features_by_symbol.items():
                if sym not in open_positions:
                    candidate_records.extend(recs)
            if candidate_records:
                candidate_momentum = momentum_feat.compute(candidate_records)
                buy_signals = entry_strategy.generate(candidate_momentum)
                for sig in buy_signals:
                    sym = sig.symbol
                    if sym in open_positions:
                        continue
                    bar = price_data.get(sym, {}).get(date_str)
                    if bar is None or bar["close"] <= 0:
                        continue
                    entry_price = bar["close"]
                    qty = notional / entry_price
                    open_positions[sym] = Position(
                        symbol=sym,
                        entry_date=current_dt,
                        entry_price=entry_price,
                        qty=qty,
                        entry_signal_strength=sig.signal_strength,
                    )
        finally:
            _unfreeze()

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(all_dates)} days simulated, "
                  f"{len(closed_trades)} closed, {len(open_positions)} open")

    # Force-close remaining open positions at final available price
    final_date = all_dates[-1]
    for sym, pos in open_positions.items():
        bar = price_data.get(sym, {}).get(final_date)
        if bar is None:
            continue
        exit_price = bar["close"]
        pnl = (exit_price - pos.entry_price) * pos.qty
        return_pct = (exit_price - pos.entry_price) / pos.entry_price
        hold_days = (datetime.fromisoformat(final_date).replace(tzinfo=timezone.utc) - pos.entry_date).days
        closed_trades.append({
            "symbol": sym,
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
        "min_momentum": min_momentum,
        "min_signal_strength": min_signal_strength,
    }


def summarize(trades: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if not trades:
        return {"label": label, "n": 0}
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
    avg_return = sum(t["return_pct"] for t in trades) / len(trades)
    win_rate = len(wins) / len(trades)
    return {
        "label": label,
        "n": len(trades),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(pf, 4) if pf != float("inf") else "inf",
        "net_pnl": round(sum(t["pnl"] for t in trades), 2),
        "avg_return_pct": round(avg_return, 4),
    }


def decile_summary(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = sorted(trades, key=lambda t: t["entry_signal_strength"])
    n = len(scored)
    if n < 10:
        return []
    rows = []
    for d in range(10):
        lo = int(n * d / 10)
        hi = int(n * (d + 1) / 10) if d < 9 else n
        bucket = scored[lo:hi]
        if not bucket:
            continue
        s = summarize(bucket, f"decile_{d+1}")
        s["ss_min"] = round(min(t["entry_signal_strength"] for t in bucket), 4)
        s["ss_max"] = round(max(t["entry_signal_strength"] for t in bucket), 4)
        rows.append(s)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None, help="Comma-separated; default = all cached")
    parser.add_argument("--notional", type=float, default=10000.0)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    if args.symbols:
        symbols = args.symbols.split(",")
    else:
        symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json"))

    result = run_backtest(symbols, notional=args.notional)
    trades = result["trades"]
    print(f"\nTotal trades: {len(trades)}")

    overall = summarize(trades, "overall")
    print(f"\nOverall: n={overall['n']} WR={overall.get('win_rate')} "
          f"PF={overall.get('profit_factor')} net=${overall.get('net_pnl')}")

    # Walk-forward split: first half vs second half of the date range
    if trades:
        dates_sorted = sorted(t["entry_date"] for t in trades)
        mid = dates_sorted[len(dates_sorted) // 2]
        period1 = [t for t in trades if t["entry_date"] < mid]
        period2 = [t for t in trades if t["entry_date"] >= mid]
        s1 = summarize(period1, f"period1 (< {mid})")
        s2 = summarize(period2, f"period2 (>= {mid})")
        print(f"\nWalk-forward split at {mid}:")
        print(f"  {s1}")
        print(f"  {s2}")

        deciles = decile_summary(trades)
        print("\nDecile breakdown (by entry_signal_strength):")
        for row in deciles:
            print(f"  {row}")
    else:
        s1 = s2 = {}
        deciles = []

    if args.save:
        out_path = PROJECT_ROOT / "reports" / "r11_backtest_results.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "config": {
                    "symbols": symbols,
                    "notional_per_trade": args.notional,
                    "date_range": result["date_range"],
                },
                "overall": overall,
                "period1": s1,
                "period2": s2,
                "decile_summary": deciles,
                "trades": trades,
            }, f, indent=2, ensure_ascii=False)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
