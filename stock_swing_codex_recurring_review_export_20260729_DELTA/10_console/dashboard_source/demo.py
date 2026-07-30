"""Deterministic demo data so the dashboard renders before real keys exist.

Shapes mirror the Alpaca API responses that the app consumes, so the UI code
has a single path for real and demo data.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

NY = ZoneInfo("America/New_York")

DEMO_NAMES = {1: "Momentum (demo)", 2: "Mean Reversion (demo)", 3: "Macro (demo)"}
_BASE = {1: 100_000.0, 2: 250_000.0, 3: 50_000.0}
_DRIFT = {1: 0.0009, 2: 0.0003, 3: -0.0002}
_VOL = {1: 0.014, 2: 0.007, 3: 0.011}

_DAYS = {"1W": 6, "1M": 22, "3M": 64, "1Y": 253, "All": 500}


def _daily_walk(idx: int) -> pd.Series:
    """A ~2-year daily equity series, deterministic per account."""
    rng = np.random.default_rng(1234 + idx)
    end = pd.Timestamp.now(tz=NY).normalize()
    days = pd.bdate_range(end=end, periods=_DAYS["All"], tz=NY)
    rets = rng.normal(_DRIFT[idx], _VOL[idx], len(days))
    return pd.Series(_BASE[idx] * np.exp(np.cumsum(rets)), index=days)


def demo_history(idx: int, period_label: str) -> dict:
    daily = _daily_walk(idx)
    if period_label == "1D":
        rng = np.random.default_rng(4321 + idx)
        day = daily.index[-1]
        times = pd.date_range(day + pd.Timedelta(hours=9, minutes=30),
                              day + pd.Timedelta(hours=16), freq="5min", tz=NY)
        start = float(daily.iloc[-2])
        rets = rng.normal(0, _VOL[idx] / np.sqrt(len(times)), len(times))
        equity = start * np.exp(np.cumsum(rets))
        series = pd.Series(equity, index=times)
    else:
        series = daily.tail(_DAYS[period_label])
    return {
        "timestamp": [int(t.timestamp()) for t in series.index],
        "equity": [round(float(v), 2) for v in series],
        "base_value": round(float(series.iloc[0]), 2),
    }


def demo_summary(idx: int) -> dict:
    daily = _daily_walk(idx)
    equity = float(daily.iloc[-1])
    cash = equity * (0.15 + 0.05 * idx)
    return {
        "status": "ACTIVE",
        "equity": f"{equity:.2f}",
        "last_equity": f"{float(daily.iloc[-2]):.2f}",
        "cash": f"{cash:.2f}",
        "buying_power": f"{cash * 2:.2f}",
        "long_market_value": f"{equity - cash:.2f}",
        "short_market_value": "0",
        "pattern_day_trader": False,
        "currency": "USD",
    }


_DEMO_POSITIONS = {
    1: [("NVDA", 40, 118.20, 134.55), ("MSFT", 25, 415.00, 442.10), ("AMZN", 30, 178.90, 171.30)],
    2: [("SPY", 120, 545.10, 558.75), ("TLT", 200, 92.40, 95.10), ("GLD", 60, 215.80, 224.40)],
    3: [("XLE", 90, 88.30, 84.95), ("FXI", 150, 27.10, 29.65)],
}


def demo_positions(idx: int) -> list[dict]:
    out = []
    for sym, qty, entry, price in _DEMO_POSITIONS[idx]:
        mv = qty * price
        pl = (price - entry) * qty
        out.append({
            "symbol": sym,
            "qty": str(qty),
            "side": "long",
            "avg_entry_price": f"{entry:.2f}",
            "current_price": f"{price:.2f}",
            "market_value": f"{mv:.2f}",
            "unrealized_pl": f"{pl:.2f}",
            "unrealized_plpc": f"{pl / (entry * qty):.4f}",
        })
    return out


def demo_orders(idx: int) -> list[dict]:
    rng = np.random.default_rng(99 + idx)
    syms = [p[0] for p in _DEMO_POSITIONS[idx]]
    now = dt.datetime.now(tz=NY)
    out = []
    for k in range(8):
        sym = syms[k % len(syms)]
        ts = now - dt.timedelta(hours=6 * k + int(rng.integers(0, 4)))
        out.append({
            "submitted_at": ts.isoformat(),
            "symbol": sym,
            "side": "buy" if k % 3 else "sell",
            "qty": str(int(rng.integers(5, 40))),
            "type": "market" if k % 2 else "limit",
            "status": "filled",
            "filled_avg_price": f"{float(rng.uniform(30, 500)):.2f}",
        })
    return out


def demo_clock() -> dict:
    now = dt.datetime.now(tz=NY)
    is_open = now.weekday() < 5 and dt.time(9, 30) <= now.time() < dt.time(16, 0)
    return {"is_open": is_open, "timestamp": now.isoformat()}
