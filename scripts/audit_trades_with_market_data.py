#!/usr/bin/env python3
"""Audit PnL tracker trades against market prices and broker position truth.

This script checks two failure modes:
1. Historical price anomalies using Yahoo Finance daily bars
2. Tracker integrity anomalies by comparing tracker open positions with broker positions

Usage:
    python scripts/audit_trades_with_market_data.py [--anomaly-threshold 0.30]

Exit codes:
    0: Success, no anomalies detected
    1: Error or anomalies detected
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.sources.broker_client import BrokerClient


def fetch_yahoo_finance_bars(symbol: str, start_date: str, end_date: str) -> dict:
    """Fetch historical bars from Yahoo Finance."""
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            result = data.get('chart', {}).get('result', [{}])[0]
            timestamps = result.get('timestamp', [])
            quotes = result.get('indicators', {}).get('quote', [{}])[0]

            bars = {}
            for i, ts in enumerate(timestamps):
                date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                close = quotes.get('close', [])[i]
                high = quotes.get('high', [])[i]
                low = quotes.get('low', [])[i]

                if close and high and low:
                    bars[date] = (float(low), float(high), float(close))

            return bars
    except Exception as e:
        print(f"WARN: Could not fetch Yahoo Finance data for {symbol}: {e}", file=sys.stderr)
        return {}


def load_env(env_file: Path) -> None:
    """Load environment variables from .env file if present."""
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())


def build_tracker_open_positions(trades: list[dict]) -> dict[str, dict]:
    """Aggregate tracker open positions by symbol."""
    positions: dict[str, dict] = {}
    for trade in trades:
        if trade.get("status") != "open":
            continue
        symbol = str(trade.get("symbol") or "").upper()
        if not symbol:
            continue
        qty = int(float(trade.get("qty") or 0))
        entry_price = float(trade.get("entry_price") or 0)
        row = positions.setdefault(symbol, {
            "symbol": symbol,
            "qty": 0,
            "entry_notional": 0.0,
            "trade_count": 0,
        })
        row["qty"] += qty
        row["entry_notional"] += entry_price * qty
        row["trade_count"] += 1

    for row in positions.values():
        qty = row["qty"]
        row["avg_entry_price"] = round((row["entry_notional"] / qty), 4) if qty else 0.0
    return positions


def analyze_tracker_integrity(trades: list[dict], broker_positions: list[dict]) -> dict:
    """Compare tracker open positions with broker positions."""
    tracker_positions = build_tracker_open_positions(trades)
    broker_map = {}
    for pos in broker_positions:
        symbol = str(pos.get("symbol") or "").upper()
        if not symbol:
            continue
        broker_map[symbol] = {
            "symbol": symbol,
            "qty": int(float(pos.get("qty") or 0)),
            "avg_entry_price": float(pos.get("avg_entry_price") or 0),
        }

    tracker_symbols = set(tracker_positions.keys())
    broker_symbols = set(broker_map.keys())
    mismatches = []
    multi_lot_symbols = []
    consistent = []

    for symbol in sorted(tracker_symbols):
        tracker_pos = tracker_positions[symbol]
        if tracker_pos.get("trade_count", 0) > 1:
            multi_lot_symbols.append({
                "symbol": symbol,
                "trade_count": tracker_pos["trade_count"],
                "tracker_qty": tracker_pos["qty"],
            })

    for symbol in sorted(tracker_symbols & broker_symbols):
        tracker_pos = tracker_positions[symbol]
        broker_pos = broker_map[symbol]
        qty_match = tracker_pos["qty"] == broker_pos["qty"]
        price_diff = abs(tracker_pos["avg_entry_price"] - broker_pos["avg_entry_price"])
        if not qty_match or price_diff > 0.01:
            mismatches.append({
                "symbol": symbol,
                "tracker_qty": tracker_pos["qty"],
                "broker_qty": broker_pos["qty"],
                "tracker_entry": tracker_pos["avg_entry_price"],
                "broker_entry": round(broker_pos["avg_entry_price"], 4),
                "tracker_trade_count": tracker_pos["trade_count"],
            })
        else:
            consistent.append(symbol)

    return {
        "tracker_positions": tracker_positions,
        "broker_positions": broker_map,
        "multi_lot_symbols": multi_lot_symbols,
        "mismatches": mismatches,
        "tracker_only": sorted(tracker_symbols - broker_symbols),
        "broker_only": sorted(broker_symbols - tracker_symbols),
        "consistent": consistent,
    }


def load_broker_positions(project_root: Path) -> list[dict]:
    """Load current broker positions if credentials are available."""
    load_env(project_root / ".env")
    api_key = os.environ.get("BROKER_API_KEY")
    api_secret = os.environ.get("BROKER_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("BROKER_API_KEY / BROKER_API_SECRET are not set")

    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
    resp = broker.fetch_positions()
    return resp.payload if hasattr(resp, "payload") else resp


def main():
    parser = argparse.ArgumentParser(description="Audit trades against market prices")
    parser.add_argument("--anomaly-threshold", type=float, default=0.30,
                       help="Price deviation threshold for anomaly detection (default: 0.30 = 30%%)")
    parser.add_argument("--symbols", nargs="*", help="Only audit specific symbols (default: all)")
    parser.add_argument("--recent-days", type=int, help="Only audit trades from recent N days")
    args = parser.parse_args()

    project_root = PROJECT_ROOT
    state_file = project_root / "data" / "tracking" / "pnl_state.json"

    if not state_file.exists():
        print(f"ERROR: {state_file} not found", file=sys.stderr)
        return 1

    state = json.loads(state_file.read_text(encoding="utf-8"))
    trades = state.get("trades", [])

    if args.symbols:
        trades = [t for t in trades if t.get("symbol") in args.symbols]

    if args.recent_days:
        cutoff = (datetime.now() - timedelta(days=args.recent_days)).isoformat()
        trades = [t for t in trades if t.get("entry_time", "") > cutoff]

    closed_trades = [t for t in trades if t.get("status") == "closed"]

    print(f"INFO: Auditing {len(closed_trades)} closed trades (threshold={args.anomaly_threshold:.0%})", file=sys.stderr)
    print()

    trades_by_symbol = {}
    for t in closed_trades:
        symbol = t.get("symbol")
        if symbol:
            trades_by_symbol.setdefault(symbol, []).append(t)

    total_anomalies = 0
    entry_anomalies = 0
    exit_anomalies = 0
    both_anomalies = 0

    for symbol, symbol_trades in sorted(trades_by_symbol.items()):
        print(f"\n{'='*100}")
        print(f"SYMBOL: {symbol} ({len(symbol_trades)} trades)")
        print('='*100)

        all_dates = set()
        for t in symbol_trades:
            entry_date = t.get("entry_time", "")[:10]
            exit_date = t.get("exit_time", "")[:10]
            all_dates.add(entry_date)
            all_dates.add(exit_date)

        if not all_dates:
            continue

        market_bars = fetch_yahoo_finance_bars(symbol, min(all_dates), max(all_dates))

        if not market_bars:
            print(f"WARN: No market data available for {symbol}, skipping", file=sys.stderr)
            continue

        for t in sorted(symbol_trades, key=lambda x: x.get("entry_time", "")):
            trade_id = t.get("trade_id", "unknown")
            entry_time = t.get("entry_time", "")[:19]
            exit_time = t.get("exit_time", "")[:19]
            entry_date = entry_time[:10]
            exit_date = exit_time[:10]
            entry_price = t.get("entry_price", 0)
            exit_price = t.get("exit_price", 0)
            ret = t.get("return_pct", 0)
            pnl = t.get("pnl", 0)

            entry_market = market_bars.get(entry_date)
            exit_market = market_bars.get(exit_date)

            if not entry_market or not exit_market:
                print(f"SKIP: {trade_id} (missing market data for {entry_date} or {exit_date})")
                continue

            entry_low, entry_high, entry_close = entry_market
            exit_low, exit_high, exit_close = exit_market

            entry_in_range = entry_low <= entry_price <= entry_high
            exit_in_range = exit_low <= exit_price <= exit_high

            entry_dev = 0
            exit_dev = 0

            if not entry_in_range:
                if entry_price < entry_low:
                    entry_dev = (entry_low - entry_price) / entry_low
                else:
                    entry_dev = (entry_price - entry_high) / entry_high

            if not exit_in_range:
                if exit_price < exit_low:
                    exit_dev = (exit_low - exit_price) / exit_low
                else:
                    exit_dev = (exit_price - exit_high) / exit_high

            is_anomaly = (not entry_in_range and entry_dev > args.anomaly_threshold) or \
                        (not exit_in_range and exit_dev > args.anomaly_threshold)

            if is_anomaly:
                total_anomalies += 1

                if not entry_in_range and not exit_in_range:
                    status = "❌ BOTH ANOMALOUS"
                    both_anomalies += 1
                elif not entry_in_range:
                    status = f"⚠️  ENTRY ANOMALOUS ({entry_dev:+.1%})"
                    entry_anomalies += 1
                else:
                    status = f"⚠️  EXIT ANOMALOUS ({exit_dev:+.1%})"
                    exit_anomalies += 1

                print(f"\n{status}")
                print(f"  Trade ID: {trade_id}")
                print(f"  Entry: {entry_date} ${entry_price:.2f} (market ${entry_low:.2f}-${entry_high:.2f})")
                print(f"  Exit:  {exit_date} ${exit_price:.2f} (market ${exit_low:.2f}-${exit_high:.2f})")
                print(f"  Return: {ret:+.2%}  P&L: ${pnl:,.2f}")

    print("\n" + "="*100)
    print("\nAUDIT SUMMARY")
    print("="*100)
    print(f"Total closed trades audited: {len(closed_trades)}")
    print(f"Total anomalies detected:    {total_anomalies}")
    print(f"  Entry price anomalies:     {entry_anomalies}")
    print(f"  Exit price anomalies:      {exit_anomalies}")
    print(f"  Both anomalous:            {both_anomalies}")

    integrity_issue_count = 0
    broker_check_failed = False
    print("\n" + "="*100)
    print("TRACKER INTEGRITY SUMMARY")
    print("="*100)
    try:
        broker_positions = load_broker_positions(project_root)
        integrity = analyze_tracker_integrity(trades, broker_positions)
        multi_lot_symbols = integrity["multi_lot_symbols"]
        mismatches = integrity["mismatches"]
        tracker_only = integrity["tracker_only"]
        broker_only = integrity["broker_only"]
        integrity_issue_count = len(mismatches) + len(tracker_only) + len(broker_only)

        print(f"Broker positions: {len(broker_positions)}")
        print(f"Tracker open symbols: {len(integrity['tracker_positions'])}")
        print(f"Integrity issue count: {integrity_issue_count}")

        if multi_lot_symbols:
            print("\nℹ️  MULTI-LOT TRACKER OPEN POSITIONS (aggregate matched broker)")
            for row in multi_lot_symbols:
                print(f"  {row['symbol']}: {row['trade_count']} tracker lots / qty={row['tracker_qty']}")

        if mismatches:
            print("\n⚠️  BROKER/TRACKER MISMATCHES")
            for row in mismatches:
                print(
                    f"  {row['symbol']}: tracker qty={row['tracker_qty']} @ ${row['tracker_entry']:.2f} "
                    f"vs broker qty={row['broker_qty']} @ ${row['broker_entry']:.2f} "
                    f"(lots={row['tracker_trade_count']})"
                )

        if tracker_only:
            print("\n⚠️  TRACKER-ONLY OPEN SYMBOLS")
            print("  " + ", ".join(tracker_only))

        if broker_only:
            print("\n⚠️  BROKER-ONLY OPEN SYMBOLS")
            print("  " + ", ".join(broker_only))

        if integrity_issue_count == 0:
            print("\n✅ Tracker open positions match broker positions.")
    except Exception as e:
        broker_check_failed = True
        print(f"WARN: Could not run broker/tracker integrity check: {e}", file=sys.stderr)

    if total_anomalies > 0 or integrity_issue_count > 0 or broker_check_failed:
        print("\n⚠️  ACTION REQUIRED:")
        if total_anomalies > 0:
            print(f"   Review {total_anomalies} anomalous trade(s) above")
        if integrity_issue_count > 0:
            print(f"   Review {integrity_issue_count} tracker integrity issue(s) above")
        if broker_check_failed:
            print("   Fix broker integrity check environment/credentials and rerun audit")
        print("\nNext steps:")
        print("  1. Backup pnl_state.json")
        if total_anomalies > 0:
            print("  2. Investigate price anomalies against market data")
        elif integrity_issue_count > 0:
            print("  2. Rebuild pnl_state from broker fills to repair tracker state")
            print("  3. Run: python scripts/rebuild_pnl_state_from_broker.py --backup")
            print("  4. Restart console to clear cache")
        else:
            print("  2. Fix the broker check environment (virtualenv/dependencies/credentials)")
            print("  3. Rerun: python scripts/audit_trades_with_market_data.py")
        return 1

    print("\n✅ No price anomalies or tracker integrity issues detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
