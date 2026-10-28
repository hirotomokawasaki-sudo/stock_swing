#!/usr/bin/env python3
"""
R3-A: Counterfactual Hold Analysis
====================================
「あの時もっと保有していたら？」を定量評価する。

各クローズトレードについて、実際の exit から +1/+3/+5/+10 営業日後の
株価を取得し、仮想 PnL を算出。生存バイアス（長期保有は元々勝ちトレード
だったのか）を制御しながら現在の exit 戦略を評価する。

Usage:
    python scripts/counterfactual_hold_analysis.py
    python scripts/counterfactual_hold_analysis.py --asset-class etf
    python scripts/counterfactual_hold_analysis.py --exit-reason trailing_stop
    python scripts/counterfactual_hold_analysis.py --hold-bucket "<1d"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load env
with open(PROJECT_ROOT / ".env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HOLD_OFFSETS = [1, 3, 5, 10]   # 追加保有日数（営業日ベース）
MIN_TRADES_FOR_REPORT = 3       # レポート行に必要な最小サンプル数


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def hold_bucket(days: float) -> str:
    if days < 1:
        return "<1d"
    if days < 3:
        return "1-3d"
    if days < 7:
        return "3-7d"
    if days < 14:
        return "7-14d"
    return ">14d"


def classify_asset_class(symbol: str, stored_ac: str | None = None) -> str:
    from stock_swing.risk.position_sizing import classify_asset_class as _c
    return stored_ac or _c(symbol)


def pf_str(wins: float, losses: float) -> str:
    if losses == 0:
        return "∞" if wins > 0 else "N/A"
    return f"{wins / losses:.3f}"


# ---------------------------------------------------------------------------
# Price fetcher (Yahoo fallback, cached)
# ---------------------------------------------------------------------------

_price_cache: dict[str, dict[str, float]] = {}   # symbol → {date_str: close}


def fetch_closes(symbol: str, fetcher: Any) -> dict[str, float]:
    """Fetch daily closes for a symbol. Returns {date_str: close}."""
    if symbol in _price_cache:
        return _price_cache[symbol]
    try:
        bars, _ = fetcher.fetch_bars(symbol, timeframe="1Day", limit=120)
        result = {}
        for bar in bars:
            d = bar.event_time.strftime("%Y-%m-%d")
            close = bar.payload.get("close")
            if close is not None:
                result[d] = float(close)
        _price_cache[symbol] = result
        time.sleep(0.15)   # rate-limit courtesy
        return result
    except Exception as exc:
        print(f"  WARN: could not fetch {symbol}: {exc}", file=sys.stderr)
        _price_cache[symbol] = {}
        return {}


def price_n_days_after(
    closes: dict[str, float],
    exit_date: str,
    n: int,
    today: str,
) -> float | None:
    """Return closing price approximately n business days after exit_date.

    Skips weekends; finds nearest available date within +3 extra days.
    Returns None if date is in the future or price unavailable.
    """
    dt = datetime.strptime(exit_date, "%Y-%m-%d")
    bdays = 0
    checked = 0
    while bdays < n and checked < 30:
        dt += timedelta(days=1)
        checked += 1
        if dt.weekday() < 5:   # Mon-Fri
            bdays += 1

    # Allow up to +3 calendar days slop to find an actual trading day
    for slack in range(4):
        candidate = (dt + timedelta(days=slack)).strftime("%Y-%m-%d")
        if candidate > today:
            return None
        if candidate in closes:
            return closes[candidate]
    return None


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def run_analysis(
    closed: list[dict[str, Any]],
    fetcher: Any,
    today: str,
    asset_class_filter: str | None,
    exit_reason_filter: str | None,
    hold_bucket_filter: str | None,
) -> dict[str, Any]:
    """Compute counterfactual PnL for each trade.

    Returns per-bucket aggregated results.
    """
    results: list[dict[str, Any]] = []
    skipped = 0

    all_symbols = sorted({t["symbol"] for t in closed if t.get("symbol")})
    print(f"\n  Fetching prices for {len(all_symbols)} symbols...")
    closes_by_symbol: dict[str, dict[str, float]] = {}
    for i, sym in enumerate(all_symbols, 1):
        closes_by_symbol[sym] = fetch_closes(sym, fetcher)
        if i % 10 == 0:
            print(f"    {i}/{len(all_symbols)} done")
    print(f"  Done ({len(all_symbols)} symbols)")

    for trade in closed:
        sym = trade.get("symbol", "")
        qty = trade.get("qty", 0) or 0
        exit_price = trade.get("exit_price")
        exit_time = trade.get("exit_time")
        entry_time = trade.get("entry_time")
        actual_pnl = trade.get("pnl") or 0
        exit_reason = trade.get("exit_reason") or "unknown"
        stored_ac = trade.get("asset_class")
        ac = classify_asset_class(sym, stored_ac)

        if not (exit_time and entry_time and exit_price and qty > 0):
            skipped += 1
            continue

        exit_date = exit_time[:10]
        hold_days = (parse_dt(exit_time) - parse_dt(entry_time)).total_seconds() / 86400
        bucket = hold_bucket(hold_days)

        # Filters
        if asset_class_filter and ac != asset_class_filter:
            continue
        if exit_reason_filter and exit_reason != exit_reason_filter:
            continue
        if hold_bucket_filter and bucket != hold_bucket_filter:
            continue

        closes = closes_by_symbol.get(sym, {})

        # Compute counterfactual PnL for each hold offset
        cf: dict[int, float | None] = {}
        for n in HOLD_OFFSETS:
            price_n = price_n_days_after(closes, exit_date, n, today)
            if price_n is not None:
                cf[n] = (price_n - float(exit_price)) * qty + actual_pnl
            else:
                cf[n] = None

        results.append({
            "trade_id": trade.get("trade_id", ""),
            "symbol": sym,
            "asset_class": ac,
            "hold_days": round(hold_days, 2),
            "hold_bucket": bucket,
            "exit_reason": exit_reason,
            "actual_pnl": actual_pnl,
            "qty": qty,
            "exit_price": exit_price,
            "exit_date": exit_date,
            "counterfactual": cf,
        })

    return {"trades": results, "skipped": skipped}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

SEP = "─" * 80

def _bucket_report(
    label: str,
    trades: list[dict],
    offsets: list[int],
) -> None:
    if len(trades) < MIN_TRADES_FOR_REPORT:
        return

    actual_pnls = [t["actual_pnl"] for t in trades]
    actual_net = sum(actual_pnls)
    actual_wins = [p for p in actual_pnls if p > 0]
    actual_losses = [abs(p) for p in actual_pnls if p < 0]
    actual_wr = len(actual_wins) / len(trades)
    actual_avg = actual_net / len(trades)

    print(f"\n  {label}  (n={len(trades)})")
    print(f"  {'':20s}  {'n':>4}  {'WR%':>6}  {'avg PnL':>9}  {'net PnL':>11}  {'PF':>7}  {'vs actual':>11}")
    print(f"  {SEP[:78]}")

    # Actual row
    print(
        f"  {'[actual exit]':<20s}  {len(trades):>4}  {actual_wr*100:>5.1f}%"
        f"  {actual_avg:>+9.0f}  {actual_net:>+11.0f}"
        f"  {pf_str(sum(actual_wins), sum(actual_losses)):>7}  {'—':>11}"
    )

    for n in offsets:
        cf_pnls = [t["counterfactual"].get(n) for t in trades if t["counterfactual"].get(n) is not None]
        if len(cf_pnls) < MIN_TRADES_FOR_REPORT:
            continue
        cf_net = sum(cf_pnls)
        cf_wins = [p for p in cf_pnls if p > 0]
        cf_losses = [abs(p) for p in cf_pnls if p < 0]
        cf_wr = len(cf_wins) / len(cf_pnls)
        cf_avg = cf_net / len(cf_pnls)
        delta = cf_net - actual_net * len(cf_pnls) / len(trades)
        delta_str = f"{delta:+.0f}"
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        print(
            f"  {f'+{n}d hold':<20s}  {len(cf_pnls):>4}  {cf_wr*100:>5.1f}%"
            f"  {cf_avg:>+9.0f}  {cf_net:>+11.0f}"
            f"  {pf_str(sum(cf_wins), sum(cf_losses)):>7}  {arrow}{delta_str:>10}"
        )


def print_report(analysis: dict, args: argparse.Namespace) -> None:
    trades = analysis["trades"]
    skipped = analysis["skipped"]

    print()
    print("=" * 80)
    print("  R3-A: Counterfactual Hold Analysis")
    filters = []
    if args.asset_class:
        filters.append(f"asset_class={args.asset_class}")
    if args.exit_reason:
        filters.append(f"exit_reason={args.exit_reason}")
    if args.hold_bucket:
        filters.append(f"hold_bucket={args.hold_bucket}")
    print(f"  Trades analyzed: {len(trades)}  |  Skipped: {skipped}"
          + (f"  |  Filters: {', '.join(filters)}" if filters else ""))
    print("=" * 80)

    # --- 1. By hold bucket ---
    print("\n── By Hold Duration ─────────────────────────────────────────────────────────")
    for bucket in ["<1d", "1-3d", "3-7d", "7-14d", ">14d"]:
        subset = [t for t in trades if t["hold_bucket"] == bucket]
        _bucket_report(f"Hold {bucket}", subset, HOLD_OFFSETS)

    # --- 2. By asset class ---
    print("\n\n── By Asset Class ───────────────────────────────────────────────────────────")
    for ac in ("etf", "stock"):
        subset = [t for t in trades if t["asset_class"] == ac]
        _bucket_report(ac.upper(), subset, HOLD_OFFSETS)

    # --- 3. By exit reason (post-R1-B only) ---
    reasons = sorted({t["exit_reason"] for t in trades if t["exit_reason"] not in ("broker_fill", "unknown", "MISSING")})
    if reasons:
        print("\n\n── By Exit Reason (signal-attributed) ───────────────────────────────────────")
        for reason in reasons:
            subset = [t for t in trades if t["exit_reason"] == reason]
            _bucket_report(reason, subset, HOLD_OFFSETS)

    # --- 4. Verdict ---
    print("\n\n── Verdict ──────────────────────────────────────────────────────────────────")
    all_pnls = [t["actual_pnl"] for t in trades]
    print(f"\n  Overall: n={len(trades)}  net=${sum(all_pnls):+,.0f}  avg=${sum(all_pnls)/len(trades):+,.0f}" if trades else "")

    # Which buckets benefit most from longer holding?
    verdicts: list[str] = []
    for bucket in ["<1d", "1-3d", "3-7d"]:
        subset = [t for t in trades if t["hold_bucket"] == bucket]
        if len(subset) < MIN_TRADES_FOR_REPORT:
            continue
        actual_net = sum(t["actual_pnl"] for t in subset)
        cf10 = [t["counterfactual"].get(10) for t in subset if t["counterfactual"].get(10) is not None]
        if len(cf10) < MIN_TRADES_FOR_REPORT:
            continue
        cf10_net = sum(cf10)
        if cf10_net > actual_net * 1.2:
            verdicts.append(f"  ⚠️  {bucket} trades: +10d hold would add ${cf10_net - actual_net:+,.0f} → early exit likely premature")
        elif cf10_net < actual_net * 0.8:
            verdicts.append(f"  ✅ {bucket} trades: +10d hold would be worse (${cf10_net - actual_net:+,.0f}) → current exit appropriate")
        else:
            verdicts.append(f"  ➡️  {bucket} trades: +10d hold negligible impact (${cf10_net - actual_net:+,.0f})")

    for v in verdicts:
        print(v)
    if not verdicts:
        print("  (insufficient data for verdict)")

    print("\n" + "=" * 80)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="R3-A Counterfactual Hold Analysis")
    parser.add_argument("--asset-class", choices=["etf", "stock"], help="Filter by asset class")
    parser.add_argument("--exit-reason", help="Filter by exit reason")
    parser.add_argument("--hold-bucket", choices=["<1d", "1-3d", "3-7d", "7-14d", ">14d"],
                        help="Filter by hold bucket")
    parser.add_argument("--save-json", action="store_true", help="Save results to reports/")
    args = parser.parse_args()

    from stock_swing.sources.broker_client import BrokerClient
    from stock_swing.sources.hybrid_data_fetcher import HybridDataFetcher
    from stock_swing.tracking.pnl_tracker import PnLTracker

    broker = BrokerClient(
        api_key=os.environ["BROKER_API_KEY"],
        api_secret=os.environ["BROKER_API_SECRET"],
        paper_mode=True,
        base_url=os.environ.get("BROKER_BASE_URL", ""),
    )
    fetcher = HybridDataFetcher(
        broker_client=broker,
        etf_symbols=set(),
        massive_api_key=os.environ.get("MASSIVE_API_KEY"),
    )
    tracker = PnLTracker(PROJECT_ROOT)
    closed = [t for t in tracker.state.trades if t.get("status") == "closed"]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"  Analysis date: {today}  |  Closed trades: {len(closed)}")

    analysis = run_analysis(
        closed=closed,
        fetcher=fetcher,
        today=today,
        asset_class_filter=args.asset_class,
        exit_reason_filter=args.exit_reason,
        hold_bucket_filter=args.hold_bucket,
    )

    print_report(analysis, args)

    if args.save_json:
        out_path = PROJECT_ROOT / "reports" / "counterfactual_hold_analysis.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "offsets_days": HOLD_OFFSETS,
                    "trades": analysis["trades"],
                    "skipped": analysis["skipped"],
                },
                f, indent=2, ensure_ascii=False
            )
        print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
