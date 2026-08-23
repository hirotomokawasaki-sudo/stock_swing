#!/usr/bin/env python3
"""R11-A: Fetch and cache 2 years of daily OHLCV for the full symbol universe.

Uses yfinance batch download (confirmed instantly available, no new API
contract needed) rather than the existing backtest/price_cache.py, which is
designed for one-symbol-at-a-time broker API calls and would need ~69 x 500
individual requests. Output is a simple per-symbol JSON cache consumed by
r11_backtest_engine.py.

Usage:
    python scripts/r11_fetch_historical_data.py [--period 2y] [--symbols AAPL,MSFT]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
REGISTRY_PATH = PROJECT_ROOT / "config" / "reference" / "symbol_registry.yaml"


def load_universe_symbols() -> list[str]:
    with open(REGISTRY_PATH) as f:
        registry = yaml.safe_load(f)
    return sorted(registry["symbols"].keys())


def fetch_and_cache(symbols: list[str], period: str) -> None:
    import yfinance as yf

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {len(symbols)} symbols, period={period} (batched)...")
    data = yf.download(
        symbols,
        period=period,
        group_by="ticker",
        progress=False,
        auto_adjust=False,
        threads=True,
    )

    ok, failed = [], []
    for sym in symbols:
        try:
            if len(symbols) == 1:
                df = data
            else:
                if sym not in data.columns.get_level_values(0):
                    failed.append(sym)
                    continue
                df = data[sym]
            df = df.dropna(how="all")
            if df.empty:
                failed.append(sym)
                continue

            bars = {}
            for idx, row in df.iterrows():
                date_str = idx.strftime("%Y-%m-%d")
                if any(k not in row or row[k] != row[k] for k in ("Open", "High", "Low", "Close")):
                    continue
                bars[date_str] = {
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row.get("Volume", 0) or 0),
                }

            out_path = CACHE_DIR / f"{sym}.json"
            out_path.write_text(json.dumps(bars, indent=None, sort_keys=True), encoding="utf-8")
            ok.append(sym)
        except Exception as exc:
            print(f"  WARN: {sym} failed: {exc}", file=sys.stderr)
            failed.append(sym)

    print(f"OK: {len(ok)} symbols cached to {CACHE_DIR}")
    if failed:
        print(f"FAILED ({len(failed)}): {', '.join(failed)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="2y")
    parser.add_argument("--symbols", default=None, help="Comma-separated override; default = full universe")
    args = parser.parse_args()

    symbols = args.symbols.split(",") if args.symbols else load_universe_symbols()
    fetch_and_cache(symbols, args.period)


if __name__ == "__main__":
    main()
