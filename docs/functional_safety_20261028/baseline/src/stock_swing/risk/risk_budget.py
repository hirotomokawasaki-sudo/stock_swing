"""Risk budget guard: compute portfolio open risk and block new buys when over threshold.

Open Risk Definition
--------------------
For each open trade: max_loss = qty × entry_price × stop_loss_pct
Stop-loss pct is determined by signal_strength (same logic as SimpleExitV2):
  - signal_strength >= 0.85  →  9%  (high conviction)
  - signal_strength >= 0.70  →  8%  (standard)
  - missing / below 0.70     →  5%  (conservative)

Total open risk = sum of max_loss across all open trades.

Thresholds
----------
WARN_PCT  = 0.05 (5% of equity)  → warn but allow buys
BLOCK_PCT = 0.08 (8% of equity)  → deny all new buy decisions

Sell decisions are NEVER blocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── Thresholds ─────────────────────────────────────────────────────────────────
# NOTE: All open trades without entry_signal_strength default to conservative 5%
# stop, which underestimates true max-loss by ~1.6x vs the 8% standard stop.
# Thresholds are set tighter than nominal to compensate for this underestimation.
WARN_PCT  = 0.04  # 4% of equity — emit warning  (≈ 6.4% true risk at 8% stop)
BLOCK_PCT = 0.06  # 6% of equity — block all new buys (≈ 9.6% true risk at 8% stop)


def _stop_loss_pct(signal_strength: float | None) -> float:
    """Return stop-loss fraction (positive) for max-loss estimation."""
    if signal_strength is None:
        return 0.05  # conservative
    if signal_strength >= 0.85:
        return 0.09  # high conviction
    if signal_strength >= 0.70:
        return 0.08  # standard
    return 0.05       # low conviction / conservative


def compute_open_risk(project_root: Path, equity: float) -> dict[str, Any]:
    """Compute current open risk from pnl_state.json.

    Returns
    -------
    dict with keys:
        open_trades_count   int
        total_open_risk     float  — sum of (qty × entry_price × stop_loss_pct)
        pct_of_equity       float  — total_open_risk / equity
        warn_threshold      float  — WARN_PCT × equity
        block_threshold     float  — BLOCK_PCT × equity
        is_warn             bool
        is_blocked          bool
        per_symbol          list[dict]  — per-symbol breakdown
    """
    state_path = project_root / "data" / "tracking" / "pnl_state.json"

    if not state_path.exists():
        # No state → no risk
        return {
            "open_trades_count": 0,
            "total_open_risk": 0.0,
            "pct_of_equity": 0.0,
            "warn_threshold": equity * WARN_PCT,
            "block_threshold": equity * BLOCK_PCT,
            "is_warn": False,
            "is_blocked": False,
            "per_symbol": [],
            "error": "pnl_state.json not found",
        }

    try:
        state = json.loads(state_path.read_text())
    except Exception as exc:
        return {
            "open_trades_count": 0,
            "total_open_risk": 0.0,
            "pct_of_equity": 0.0,
            "warn_threshold": equity * WARN_PCT,
            "block_threshold": equity * BLOCK_PCT,
            "is_warn": False,
            "is_blocked": False,
            "per_symbol": [],
            "error": str(exc),
        }

    trades: list[dict] = state.get("trades", [])
    open_trades = [t for t in trades if t.get("status") == "open"]

    # Aggregate per symbol
    by_symbol: dict[str, dict] = {}
    for t in open_trades:
        sym = t.get("symbol", "?")
        qty = float(t.get("qty", 0))
        entry = float(t.get("entry_price", 0))
        sig = t.get("entry_signal_strength", t.get("signal_strength", None))  # entry_signal_strength preferred; signal_strength kept for backward compat
        if sig is not None:
            try:
                sig = float(sig)
            except (TypeError, ValueError):
                sig = None

        stop_pct = _stop_loss_pct(sig)
        max_loss = qty * entry * stop_pct

        if sym not in by_symbol:
            by_symbol[sym] = {"symbol": sym, "lots": 0, "max_loss": 0.0, "market_value": 0.0}
        by_symbol[sym]["lots"] += 1
        by_symbol[sym]["max_loss"] += max_loss
        by_symbol[sym]["market_value"] += qty * entry

    total_open_risk = sum(v["max_loss"] for v in by_symbol.values())
    pct = total_open_risk / equity if equity > 0 else 0.0
    per_symbol = sorted(by_symbol.values(), key=lambda x: -x["max_loss"])

    return {
        "open_trades_count": len(open_trades),
        "total_open_risk": total_open_risk,
        "pct_of_equity": pct,
        "warn_threshold": equity * WARN_PCT,
        "block_threshold": equity * BLOCK_PCT,
        "is_warn": pct >= WARN_PCT,
        "is_blocked": pct >= BLOCK_PCT,
        "per_symbol": per_symbol,
    }
