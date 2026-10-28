#!/usr/bin/env python3
"""G7: Collect benchmark daily bars for sector_shock_hold validation.

Collects: SMH, SOXX, QQQ, SPY, SOXQ (semiconductor + broad market benchmarks)
Output:
  data/benchmarks/benchmark_prices.csv
  data/benchmarks/benchmark_returns.csv
  data/benchmarks/{SYMBOL}_daily.json
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BENCHMARK_SYMBOLS = ["SMH", "SOXX", "QQQ", "SPY", "SOXQ"]
DAYS_BACK = 90


def fetch_finnhub_candles(symbol: str, api_key: str) -> list[dict]:
    """Fetch daily candles from Finnhub."""
    import urllib.error
    import urllib.request

    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).timestamp())

    url = (
        "https://finnhub.io/api/v1/stock/candle?"
        f"symbol={symbol}&resolution=D&from={start_ts}&to={end_ts}&token={api_key}"
    )

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "stock-swing/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if data.get("s") != "ok":
            print(f"  [!] {symbol}: status={data.get('s')}")
            return []

        bars = []
        for i, ts in enumerate(data.get("t", [])):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            bars.append(
                {
                    "date": dt,
                    "open": data["o"][i],
                    "high": data["h"][i],
                    "low": data["l"][i],
                    "close": data["c"][i],
                    "volume": data["v"][i],
                }
            )
        return sorted(bars, key=lambda x: x["date"])
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode().strip()
        except Exception:
            detail = ""
        suffix = f" body={detail[:200]}" if detail else ""
        print(f"  ERROR {symbol}: HTTP {e.code} {e.reason}{suffix}")
        return []
    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return []


def main():
    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("FINNHUB_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not api_key:
        print("ERROR FINNHUB_API_KEY not set")
        return 1

    out_dir = PROJECT_ROOT / "data/benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_bars = {}
    for sym in BENCHMARK_SYMBOLS:
        print(f"  Fetching {sym}...")
        bars = fetch_finnhub_candles(sym, api_key)
        if bars:
            all_bars[sym] = bars
            out_file = out_dir / f"{sym}_daily.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(bars, f, indent=2, ensure_ascii=False)
            print(f"    OK {sym}: {len(bars)} bars -> {out_file}")
        time.sleep(0.5)

    if not all_bars:
        print("No data collected")
        return 1

    prices_path = out_dir / "benchmark_prices.csv"
    with open(prices_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "symbol", "open", "high", "low", "close", "volume"])
        for sym, bars in all_bars.items():
            for b in bars:
                w.writerow(
                    [b["date"], sym, b["open"], b["high"], b["low"], b["close"], b["volume"]]
                )

    returns_path = out_dir / "benchmark_returns.csv"
    with open(returns_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["date", "symbol", "close", "daily_return", "return_3d", "return_5d", "cumulative_return"]
        )
        for sym, bars in all_bars.items():
            closes = [b["close"] for b in bars]
            start = closes[0]
            for i, b in enumerate(bars):
                c = closes[i]
                daily = (c - closes[i - 1]) / closes[i - 1] if i > 0 else 0.0
                r3d = (c - closes[i - 3]) / closes[i - 3] if i >= 3 else 0.0
                r5d = (c - closes[i - 5]) / closes[i - 5] if i >= 5 else 0.0
                cum = (c - start) / start
                w.writerow([b["date"], sym, c, f"{daily:.4f}", f"{r3d:.4f}", f"{r5d:.4f}", f"{cum:.4f}"])

    print(f"\nBenchmark data written: {', '.join(all_bars.keys())}")
    print(f"  {prices_path}")
    print(f"  {returns_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
