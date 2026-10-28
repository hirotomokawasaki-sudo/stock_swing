#!/usr/bin/env python3
"""R11-C: Backtest already-collected-but-unused signal sources as ENTRY
FILTERS layered on top of the R11-B baseline (BreakoutMomentumStrategy +
SimpleExitV2Strategy), over the same historical window/cost assumptions,
for a fair side-by-side comparison.

Candidates (docs/console_improvement_tasks.md "R11-C" section):
  1. RSI reversed filter  -- only enter when RSI(14) < overbought threshold
     (Plan E's rsi_diagnostic used in the OPPOSITE direction: instead of
     just logging overbought BUYs, actually skip them)
  2. News sentiment positive filter -- requires live news data per-symbol
     per-day; NOT backtestable with the current historical setup (no
     historical news archive), see note below. Included as a documented
     gap, not silently skipped.
  3. Earnings-calendar proximity -- only enter within N days of an
     upcoming/recent earnings date (yfinance Ticker.earnings_dates gives
     historical earnings dates, requires lxml)
  4. Sector relative strength -- only enter when the symbol's momentum
     exceeds its sector benchmark's momentum over the same window
     (symbol_registry.yaml benchmark_symbols)

This script reuses r11_backtest_engine.py's simulation loop by importing
and calling into it with an additional entry-time filter callback, rather
than duplicating the frozen-clock / production-strategy-loading logic.

Usage:
    python scripts/r11c_candidate_backtest.py --candidate rsi_reversed
    python scripts/r11c_candidate_backtest.py --candidate earnings_proximity
    python scripts/r11c_candidate_backtest.py --candidate sector_relative_strength
    python scripts/r11c_candidate_backtest.py --candidate all
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import r11_backtest_engine as base  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
EARNINGS_CACHE_DIR = PROJECT_ROOT / "data" / "r11_earnings_cache"
REGISTRY_PATH = PROJECT_ROOT / "config" / "reference" / "symbol_registry.yaml"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def compute_rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI, same smoothing convention as standard RSI(14).

    Returns a list aligned with `closes` (index i = RSI as of closes[i]),
    with the first `period` entries as None (insufficient history).
    """
    n = len(closes)
    rsis: list[float | None] = [None] * n
    if n <= period:
        return rsis
    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    idx = period  # closes[period] is the first index with a valid RSI
    rs = avg_gain / avg_loss if avg_loss > 0 else float("inf")
    rsis[idx] = 100.0 - 100.0 / (1.0 + rs) if rs != float("inf") else 100.0

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else float("inf")
        val = 100.0 - 100.0 / (1.0 + rs) if rs != float("inf") else 100.0
        rsis[i + 1] = val
    return rsis


def load_universe_registry() -> dict[str, Any]:
    with open(REGISTRY_PATH) as f:
        return yaml.safe_load(f)["symbols"]


def fetch_earnings_dates(symbols: list[str]) -> dict[str, list[str]]:
    """Fetch historical earnings dates per symbol via yfinance, cached to disk."""
    EARNINGS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, list[str]] = {}
    import yfinance as yf

    for sym in symbols:
        cache_path = EARNINGS_CACHE_DIR / f"{sym}.json"
        if cache_path.exists():
            result[sym] = json.loads(cache_path.read_text())
            continue
        try:
            ed = yf.Ticker(sym).earnings_dates
            if ed is None or ed.empty:
                dates = []
            else:
                dates = [d.strftime("%Y-%m-%d") for d in ed.index]
            cache_path.write_text(json.dumps(dates), encoding="utf-8")
            result[sym] = dates
        except Exception as exc:
            print(f"  WARN: earnings_dates fetch failed for {sym}: {exc}", file=sys.stderr)
            result[sym] = []
    return result


# ---------------------------------------------------------------------------
# Filtered backtest runner (mirrors r11_backtest_engine.run_backtest but
# accepts an entry_filter callback: (symbol, date_str, momentum_result) -> bool)
# ---------------------------------------------------------------------------

def run_filtered_backtest(
    symbols: list[str],
    notional: float,
    entry_filter: Callable[[str, str], bool] | None,
    min_momentum: float = 0.05,
    min_signal_strength: float = 0.40,
) -> dict[str, Any]:
    from stock_swing.strategy_engine.breakout_momentum_strategy import BreakoutMomentumStrategy

    price_data = base.load_price_data(symbols)
    if not price_data:
        raise RuntimeError(f"No cached price data found in {CACHE_DIR}")

    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))

    entry_strategy = BreakoutMomentumStrategy(
        min_momentum=min_momentum, min_signal_strength=min_signal_strength
    )
    exit_strategy = base.load_exit_strategy()

    open_positions: dict[str, base.Position] = {}
    closed_trades: list[dict[str, Any]] = []

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        base._freeze(current_dt)
        try:
            window_start_idx = max(0, i - base.BAR_LIMIT + 1)
            window_dates = all_dates[window_start_idx : i + 1]

            features_by_symbol: dict[str, list] = {}
            for sym, bars in price_data.items():
                recs = [base.make_record(sym, d, bars[d]) for d in window_dates if d in bars]
                if recs:
                    features_by_symbol[sym] = recs

            momentum_feat = base.PriceMomentumFeature(period_days=base.BAR_LIMIT)
            all_records = []
            for recs in features_by_symbol.values():
                all_records.extend(recs)
            momentum_results = momentum_feat.compute(all_records)

            # --- Exits (unchanged from R11-B) ---
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

            # --- Entries (with filter applied) ---
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
                    if entry_filter is not None and not entry_filter(sym, date_str):
                        continue
                    bar = price_data.get(sym, {}).get(date_str)
                    if bar is None or bar["close"] <= 0:
                        continue
                    entry_price = bar["close"]
                    qty = notional / entry_price
                    open_positions[sym] = base.Position(
                        symbol=sym, entry_date=current_dt, entry_price=entry_price,
                        qty=qty, entry_signal_strength=sig.signal_strength,
                    )
        finally:
            base._unfreeze()

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
            "symbol": sym, "entry_date": pos.entry_date.date().isoformat(),
            "exit_date": final_date, "entry_price": pos.entry_price,
            "exit_price": exit_price, "qty": pos.qty, "pnl": pnl,
            "return_pct": return_pct, "holding_days": hold_days,
            "exit_reason": "backtest_end_forced_close",
            "entry_signal_strength": pos.entry_signal_strength,
        })

    return {"trades": closed_trades, "date_range": [all_dates[0], all_dates[-1]]}


# ---------------------------------------------------------------------------
# Candidate filter builders
# ---------------------------------------------------------------------------

def build_rsi_reversed_filter(symbols: list[str], threshold: float = 75.0) -> Callable[[str, str], bool]:
    """Only allow entry when RSI(14) < threshold (skip already-overbought)."""
    rsi_by_symbol: dict[str, dict[str, float | None]] = {}
    for sym in symbols:
        path = CACHE_DIR / f"{sym}.json"
        if not path.exists():
            continue
        bars = json.loads(path.read_text())
        dates = sorted(bars.keys())
        closes = [bars[d]["close"] for d in dates]
        rsis = compute_rsi_series(closes)
        rsi_by_symbol[sym] = dict(zip(dates, rsis))

    def _filter(symbol: str, date_str: str) -> bool:
        rsi = rsi_by_symbol.get(symbol, {}).get(date_str)
        if rsi is None:
            return True  # insufficient history to compute -> don't block
        return rsi < threshold

    return _filter


def build_earnings_proximity_filter(symbols: list[str], window_days: int = 5) -> Callable[[str, str], bool]:
    """Only allow entry within window_days of an earnings date (before or after)."""
    earnings = fetch_earnings_dates(symbols)
    earnings_dt: dict[str, list[datetime]] = {
        sym: [datetime.fromisoformat(d) for d in dates] for sym, dates in earnings.items()
    }

    def _filter(symbol: str, date_str: str) -> bool:
        dts = earnings_dt.get(symbol) or []
        if not dts:
            return False  # no earnings data -> exclude from this candidate's universe
        current = datetime.fromisoformat(date_str)
        return any(abs((current - d).days) <= window_days for d in dts)

    return _filter


def build_news_sentiment_positive_filter(
    symbols: list[str],
    min_net_score: float = 0.0,
) -> tuple[Callable[[str, str], bool], str, str]:
    """Only allow entry when the most recent Finnhub news snapshot as-of
    that date scores net-positive (using the same lexicon as Plan D's
    news_sentiment.py, in the OPPOSITE direction: require net_score >=
    min_net_score rather than just flagging net_score <= -0.34).

    IMPORTANT LIMITATION: unlike price data (2 years via yfinance), Finnhub
    company-news snapshots only exist from when stock_swing_news_collection
    started running (data/raw/finnhub/finnhub_{symbol}_news_*.json), which
    covers roughly 2026-04-21 through today -- about 4 months, not 2 years.
    There is no historical news archive to backfill the earlier ~20 months.
    This candidate can therefore only be evaluated over the shorter window,
    which is both a smaller sample and a period-specific result (cannot do
    the same two-window walk-forward split as the other R11-C candidates
    with any real independence). Reported with this caveat, not silently
    normalized to look like the others.
    """
    import re
    from stock_swing.risk.news_sentiment import _score_article_text

    raw_dir = PROJECT_ROOT / "data" / "raw" / "finnhub"
    snapshots_by_symbol: dict[str, list[tuple[datetime, list[dict]]]] = {}
    min_date, max_date = None, None

    for sym in symbols:
        files = sorted(raw_dir.glob(f"finnhub_{sym.lower()}_news_*.json"))
        entries = []
        for path in files:
            m = re.search(r"news_(\d{4}-\d{2}-\d{2})", path.name)
            if not m:
                continue
            snap_date = datetime.fromisoformat(m.group(1))
            try:
                raw = json.loads(path.read_text())
                news = (raw.get("payload") or {}).get("news") or []
            except Exception:
                continue
            entries.append((snap_date, news))
            if min_date is None or snap_date < min_date:
                min_date = snap_date
            if max_date is None or snap_date > max_date:
                max_date = snap_date
        entries.sort(key=lambda e: e[0])
        snapshots_by_symbol[sym] = entries

    def _net_score(symbol: str, date_str: str) -> float | None:
        entries = snapshots_by_symbol.get(symbol) or []
        current = datetime.fromisoformat(date_str)
        # Most recent snapshot at or before `current`
        best = None
        for snap_date, news in entries:
            if snap_date <= current:
                best = news
            else:
                break
        if best is None:
            return None
        pos_total, neg_total = 0, 0
        for item in best:
            text = f"{item.get('headline', '')} {item.get('summary', '')}".lower()
            p, n = _score_article_text(text)
            pos_total += p
            neg_total += n
        total = pos_total + neg_total
        if total == 0:
            return None
        return (pos_total - neg_total) / total

    def _filter(symbol: str, date_str: str) -> bool:
        score = _net_score(symbol, date_str)
        if score is None:
            return False  # no scorable news data -> exclude from this candidate's universe
        return score >= min_net_score

    window_label = f"{min_date.date().isoformat() if min_date else '?'} -> {max_date.date().isoformat() if max_date else '?'}"
    return _filter, window_label, "news archive is ~4 months, not the full 2y backtest window"


def build_sector_relative_strength_filter(symbols: list[str], registry: dict[str, Any]) -> Callable[[str, str], bool]:
    """Only allow entry when symbol's 5-day momentum > its primary benchmark's 5-day momentum."""
    closes_by_symbol: dict[str, dict[str, float]] = {}
    all_syms = set(symbols)
    for sym_info in registry.values():
        all_syms.update(sym_info.get("benchmark_symbols", []))
    for sym in all_syms:
        path = CACHE_DIR / f"{sym}.json"
        if path.exists():
            closes_by_symbol[sym] = {d: v["close"] for d, v in json.loads(path.read_text()).items()}

    def _momentum(sym: str, date_str: str, lookback: int = 5) -> float | None:
        bars = closes_by_symbol.get(sym)
        if not bars:
            return None
        dates = sorted(d for d in bars if d <= date_str)
        if len(dates) <= lookback:
            return None
        recent = dates[-(lookback + 1):]
        start, end = bars[recent[0]], bars[recent[-1]]
        if start <= 0:
            return None
        return (end - start) / start

    def _filter(symbol: str, date_str: str) -> bool:
        benchmarks = registry.get(symbol, {}).get("benchmark_symbols") or []
        if not benchmarks:
            return True  # no benchmark defined -> don't block
        sym_mom = _momentum(symbol, date_str)
        if sym_mom is None:
            return True
        # Compare against the first (primary) benchmark only, for simplicity
        bench_mom = _momentum(benchmarks[0], date_str)
        if bench_mom is None:
            return True
        return sym_mom > bench_mom

    return _filter


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def summarize(trades: list[dict[str, Any]], label: str) -> dict[str, Any]:
    return base.summarize(trades, label)


def compare_to_baseline(candidate_trades: list[dict[str, Any]], label: str, baseline_path: Path) -> None:
    baseline = json.loads(baseline_path.read_text())
    baseline_overall = baseline["overall"]
    candidate_overall = summarize(candidate_trades, label)

    print(f"\n=== {label} vs baseline (R11-B) ===")
    print(f"  baseline:  n={baseline_overall['n']:>5} WR={baseline_overall['win_rate']} "
          f"PF={baseline_overall['profit_factor']} net=${baseline_overall['net_pnl']:,}")
    print(f"  candidate: n={candidate_overall['n']:>5} WR={candidate_overall.get('win_rate')} "
          f"PF={candidate_overall.get('profit_factor')} net=${candidate_overall.get('net_pnl', 0):,}")

    # Walk-forward split using baseline's date-derived midpoint approach
    if candidate_trades:
        dates_sorted = sorted(t["entry_date"] for t in candidate_trades)
        mid = dates_sorted[len(dates_sorted) // 2]
        p1 = [t for t in candidate_trades if t["entry_date"] < mid]
        p2 = [t for t in candidate_trades if t["entry_date"] >= mid]
        print(f"  walk-forward: period1(n={len(p1)}) {summarize(p1, 'p1')} | "
              f"period2(n={len(p2)}) {summarize(p2, 'p2')}")

    return candidate_overall


CANDIDATES = {
    "rsi_reversed": ("RSI reversed filter (skip RSI>=75 overbought)", build_rsi_reversed_filter),
    "earnings_proximity": ("Earnings-calendar proximity (+/-5d)", build_earnings_proximity_filter),
    "sector_relative_strength": ("Sector relative strength (vs primary benchmark)", build_sector_relative_strength_filter),
    "news_sentiment_positive": ("News sentiment positive filter (net_score>=0, LIMITED WINDOW)", None),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, choices=list(CANDIDATES.keys()) + ["all"])
    parser.add_argument("--notional", type=float, default=10000.0)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json"))
    baseline_path = PROJECT_ROOT / "reports" / "r11_backtest_results.json"
    if not baseline_path.exists():
        print("ERROR: run r11_backtest_engine.py --save first to produce the baseline", file=sys.stderr)
        sys.exit(1)

    registry = load_universe_registry()
    to_run = list(CANDIDATES.keys()) if args.candidate == "all" else [args.candidate]

    results = {}
    for cand_key in to_run:
        label, builder = CANDIDATES[cand_key]
        print(f"\n--- Building filter: {label} ---")
        caveat = None
        if cand_key == "sector_relative_strength":
            entry_filter = builder(symbols, registry)
        elif cand_key == "news_sentiment_positive":
            entry_filter, window_label, caveat = build_news_sentiment_positive_filter(symbols)
            print(f"  NOTE: news archive window = {window_label} ({caveat})")
        else:
            entry_filter = builder(symbols)

        result = run_filtered_backtest(symbols, notional=args.notional, entry_filter=entry_filter)
        trades = result["trades"]
        overall = compare_to_baseline(trades, label, baseline_path)
        results[cand_key] = {"label": label, "overall": overall, "n_trades": len(trades), "caveat": caveat}

        if args.save:
            out_path = PROJECT_ROOT / "reports" / f"r11c_{cand_key}_results.json"
            with open(out_path, "w") as f:
                json.dump({
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "candidate": cand_key,
                    "label": label,
                    "overall": overall,
                    "trades": trades,
                }, f, indent=2, ensure_ascii=False)
            print(f"  Saved: {out_path}")

    print("\n=== Summary ===")
    for k, v in results.items():
        print(f"  {k}: n={v['n_trades']} PF={v['overall'].get('profit_factor')}")


if __name__ == "__main__":
    main()
