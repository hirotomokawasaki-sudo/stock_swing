#!/usr/bin/env python3
"""Build post-signal outcomes for denied/filtered signals (P1-D)."""

from __future__ import annotations

import csv
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

OUT_CSV = PROJECT_ROOT / "data" / "analysis" / "post_signal_outcomes.csv"
FIELDS = [
    "timestamp",
    "symbol",
    "strategy_id",
    "signal_strength",
    "decision_action",
    "deny_reason",
    "price_at_signal",
    "return_1d",
    "return_3d",
    "return_5d",
    "return_10d",
    "return_20d",
    "max_favorable_excursion",
    "max_adverse_excursion",
    "market_regime",
]


def fetch_yahoo_closes(symbol: str) -> dict[str, float]:
    """Fetch about two months of daily closes from Yahoo Finance."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&range=2mo"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        out = {}
        for ts, close in zip(timestamps, closes):
            if close is not None:
                day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                out[day] = float(close)
        return out
    except Exception:
        return {}


def compute_forward_returns(
    closes: dict[str, float],
    signal_date: str,
    price_at_signal: float,
) -> dict[str, float | None]:
    """Compute forward returns from the first trading day after signal_date."""
    if not closes or price_at_signal <= 0:
        return {f"return_{n}d": None for n in [1, 3, 5, 10, 20]}

    sorted_dates = sorted(day for day in closes if day > signal_date)
    baseline_aligned = False
    if sorted_dates:
        baseline_price = closes[sorted_dates[0]]
        baseline_aligned = abs(baseline_price - price_at_signal) / price_at_signal < 0.0001

    out = {}
    for n in [1, 3, 5, 10, 20]:
        if baseline_aligned:
            target_index = 1 if n == 1 else n - 1
        else:
            target_index = n - 1
        if len(sorted_dates) > target_index:
            future_price = closes[sorted_dates[target_index]]
            out[f"return_{n}d"] = round((future_price - price_at_signal) / price_at_signal, 4)
        elif n == 1 and sorted_dates:
            out[f"return_{n}d"] = round((closes[sorted_dates[0]] - price_at_signal) / price_at_signal, 4)
        else:
            out[f"return_{n}d"] = None

    future_start = 1 if baseline_aligned else 0
    future_prices = [closes[day] for day in sorted_dates[future_start:future_start + 20] if day in closes]
    if future_prices:
        out["max_favorable_excursion"] = round(
            (max(future_prices) - price_at_signal) / price_at_signal,
            4,
        )
        out["max_adverse_excursion"] = round(
            (min(future_prices) - price_at_signal) / price_at_signal,
            4,
        )
    else:
        out["max_favorable_excursion"] = None
        out["max_adverse_excursion"] = None
    return out


def main() -> None:
    dec_dir = PROJECT_ROOT / "data" / "decisions"
    if not dec_dir.exists():
        print("No decisions directory.")
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    candidates = []
    for decision_file in sorted(dec_dir.glob("decision_*.json")):
        try:
            decision = json.loads(decision_file.read_text(encoding="utf-8"))
            generated_at = decision.get("generated_at", "")
            if generated_at < cutoff:
                continue
            action = decision.get("action", "")
            if action not in ("deny", "hold", "review"):
                continue
            evidence = decision.get("evidence") or {}
            candidates.append(
                {
                    "timestamp": generated_at,
                    "symbol": decision.get("symbol", ""),
                    "strategy_id": decision.get("strategy_id", ""),
                    "signal_strength": decision.get("signal_strength"),
                    "decision_action": action,
                    "deny_reason": "|".join(decision.get("deny_reasons") or []),
                    "price_at_signal": float(evidence.get("latest_close") or 0),
                    "market_regime": evidence.get("market_regime", ""),
                }
            )
        except Exception:
            continue

    print(f"Processing {len(candidates)} denied/held candidates...")
    price_cache: dict[str, dict[str, float]] = {}
    rows = []
    for i, candidate in enumerate(candidates):
        symbol = candidate["symbol"]
        if symbol not in price_cache:
            print(f"  Fetching {symbol} ({i + 1}/{len(candidates)})...")
            price_cache[symbol] = fetch_yahoo_closes(symbol)
        forward = compute_forward_returns(
            price_cache[symbol],
            candidate["timestamp"][:10],
            candidate["price_at_signal"],
        )
        rows.append({**candidate, **forward})

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    real_rows = [row for row in rows if row.get("return_1d") is not None]
    print(f"\nDone: {len(rows)} rows total, {len(real_rows)} with real return data")
    print(f"Saved to: {OUT_CSV}")


if __name__ == "__main__":
    main()
