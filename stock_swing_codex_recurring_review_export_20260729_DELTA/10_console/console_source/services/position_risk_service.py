"""Open position risk service.

Shows exit-threshold proximity for each open position.
No broker credentials required — reads local state/export files only.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

# Conservative thresholds applied when entry_signal_strength is None/invalid (P0 fix)
_CONSERVATIVE_STOP_LOSS = -0.05
_CONSERVATIVE_TRAILING_ACTIVATION = 0.10

# Buckets for peak_gain_pct histogram
_BUCKETS: list[tuple[str, float, float]] = [
    (">=10%",  0.10,  float("inf")),
    ("8-10%",  0.08,  0.10),
    ("6-8%",   0.06,  0.08),
    ("3-6%",   0.03,  0.06),
    ("0-3%",   0.00,  0.03),
    ("<0%",    float("-inf"), 0.00),
]


def _resolve_thresholds(entry_signal_strength: float | None) -> tuple[float, float]:
    """Return (stop_loss_pct, trailing_activation_pct) using same logic as SimpleExitV2."""
    try:
        from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy
        return SimpleExitV2Strategy()._resolve_thresholds(entry_signal_strength)
    except Exception:
        if entry_signal_strength is None:
            return _CONSERVATIVE_STOP_LOSS, _CONSERVATIVE_TRAILING_ACTIVATION
        s = float(entry_signal_strength)
        if s >= 0.85:
            return -0.09, 0.06
        if s < 0.65:
            return _CONSERVATIVE_STOP_LOSS, _CONSERVATIVE_TRAILING_ACTIVATION
        return -0.07, 0.08


def _exit_attention(
    unrealized_pct: float | None,
    stop_loss_pct: float,
    trailing_activation_pct: float,
    WATCH_MARGIN: float = 0.02,
) -> str:
    if unrealized_pct is None:
        return "unknown"
    if unrealized_pct <= stop_loss_pct:
        return "exit_now"
    if unrealized_pct >= trailing_activation_pct:
        return "exit_now"
    if unrealized_pct <= (stop_loss_pct + WATCH_MARGIN):
        return "watch"
    if unrealized_pct >= (trailing_activation_pct - WATCH_MARGIN):
        return "watch"
    return "normal"


def _load_open_positions(project_root: Path) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    rows: list[dict] = []

    csv_path = project_root / "exports/open_positions.csv"
    if csv_path.exists():
        try:
            for r in csv.DictReader(csv_path.open(encoding="utf-8")):
                def _float(key: str) -> float | None:
                    v = r.get(key, "").strip()
                    try:
                        return float(v) if v and v.lower() not in ("none", "null", "") else None
                    except ValueError:
                        return None
                rows.append({
                    "symbol":               r.get("symbol", "?"),
                    "qty":                  _float("qty"),
                    "entry_price":          _float("entry_price"),
                    "peak_price":           _float("peak_price"),
                    "entry_signal_strength":_float("entry_signal_strength"),
                    "current_price":        None,   # not in static export
                })
            return rows, warnings
        except Exception as exc:
            warnings.append(f"Could not parse open_positions.csv: {exc}")

    # Fallback
    state_path = project_root / "data/tracking/pnl_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            for t in state.get("trades", []):
                if t.get("status") != "open":
                    continue
                rows.append({
                    "symbol":               str(t.get("symbol", "?")).upper(),
                    "qty":                  t.get("qty"),
                    "entry_price":          t.get("entry_price"),
                    "peak_price":           t.get("peak_price"),
                    "entry_signal_strength":t.get("entry_signal_strength"),
                    "current_price":        None,
                })
            return rows, warnings
        except Exception as exc:
            warnings.append(f"Could not parse pnl_state.json: {exc}")

    warnings.append("No open position data available")
    return [], warnings


def _peak_gain_pct(entry_price: float | None, peak_price: float | None) -> float | None:
    if not entry_price or not peak_price or entry_price <= 0:
        return None
    return (peak_price - entry_price) / entry_price


def get_open_position_risk(project_root: Path) -> dict[str, Any]:
    """Return per-position risk assessment with exit-threshold proximity.

    Args:
        project_root: Absolute path to repo root.
    """
    rows, warnings = _load_open_positions(project_root)

    positions: list[dict] = []
    entry_notional = 0.0
    missing_strength = 0
    conservative_count = 0

    for r in rows:
        entry_price  = r["entry_price"]
        peak_price   = r["peak_price"]
        current_price= r["current_price"]
        strength     = r["entry_signal_strength"]
        qty          = r["qty"] or 0

        if entry_price and qty:
            entry_notional += entry_price * qty

        stop, trail = _resolve_thresholds(strength)
        is_conservative = strength is None
        if is_conservative:
            missing_strength += 1
            conservative_count += 1

        # unrealized based on current_price (may be None for static export)
        unrealized_pct = None
        if current_price and entry_price and entry_price > 0:
            unrealized_pct = (current_price - entry_price) / entry_price

        peak_gain = _peak_gain_pct(entry_price, peak_price)

        attention = _exit_attention(
            unrealized_pct if unrealized_pct is not None else (peak_gain),
            stop, trail,
        )
        if current_price is None:
            attention = "unknown" if unrealized_pct is None else attention

        positions.append({
            "symbol":             r["symbol"],
            "qty":                qty,
            "entry_price":        entry_price,
            "current_price":      current_price,
            "unrealized_pct":     round(unrealized_pct, 4) if unrealized_pct is not None else None,
            "peak_gain_pct":      round(peak_gain, 4)      if peak_gain      is not None else None,
            "entry_signal_strength": strength,
            "threshold_policy":   "conservative_missing_strength" if is_conservative else "signal_strength_based",
            "stop_loss_pct":      stop,
            "take_profit_pct":    trail,
            "exit_attention":     attention,
        })

    # Bucket histogram for peak_gain_pct
    buckets: list[dict] = []
    for label, lo, hi in _BUCKETS:
        count = sum(
            1 for p in positions
            if p["peak_gain_pct"] is not None
            and lo <= p["peak_gain_pct"] < hi
        )
        buckets.append({"bucket": label, "count": count})

    # Sort by exit_attention priority
    _priority = {"exit_now": 0, "watch": 1, "normal": 2, "unknown": 3}
    positions.sort(key=lambda p: (_priority.get(p["exit_attention"], 9), p["symbol"]))

    return {
        "summary": {
            "open_positions": len(positions),
            "entry_notional": round(entry_notional, 2),
            "missing_entry_signal_strength": missing_strength,
            "conservative_threshold_positions": conservative_count,
        },
        "peak_gain_buckets": buckets,
        "positions": positions,
        "warnings": warnings,
    }
