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
WARN_PCT  = 0.04 (4% of equity)  → warn but allow buys
BLOCK_PCT = 0.06 (6% of equity)  → deny all new buy decisions

Sell decisions are NEVER blocked.
"""

from __future__ import annotations

import json
import math
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


def _unavailable_risk(reason: str) -> dict[str, Any]:
    """Unknown risk is not a measured zero and must deny new BUYs."""
    return {
        "status": "unavailable", "error": reason,
        "open_trades_count": None, "total_open_risk": None,
        "pct_of_equity": None, "warn_threshold": None, "block_threshold": None,
        "is_warn": False, "is_blocked": True, "per_symbol": [],
    }


def _finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a risk number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite risk number")
    return number


def compute_open_risk(project_root: Path, equity: float) -> dict[str, Any]:
    """Compute the existing stop-based estimate, or return explicit unknown.

    Confirmed empty ``trades`` is flat. Missing/malformed state, invalid open
    lots, and invalid equity are unknown; never expose a partial sum as total.
    This estimate is not a broker reconciliation or a guaranteed loss bound.
    """
    try:
        equity = _finite_number(equity)
        if equity <= 0:
            raise ValueError("non-positive equity")
    except (TypeError, ValueError, OverflowError):
        return _unavailable_risk("invalid_equity")

    state_path = project_root / "data" / "tracking" / "pnl_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _unavailable_risk("state_read_failed:" + type(exc).__name__)
    if not isinstance(state, dict) or not isinstance(state.get("trades"), list):
        return _unavailable_risk("invalid_state_schema")

    by_symbol: dict[str, dict] = {}
    open_count = 0
    for t in state["trades"]:
        if not isinstance(t, dict) or not isinstance(t.get("status"), str) or t["status"] not in {"open", "closed", "quarantined"}:
            return _unavailable_risk("invalid_trade_status")
        if t["status"] != "open":
            continue
        try:
            sym = t.get("symbol")
            if not isinstance(sym, str) or not sym.strip():
                raise ValueError("missing symbol")
            qty = _finite_number(t.get("qty"))
            entry = _finite_number(t.get("entry_price"))
            if qty <= 0 or entry <= 0:
                raise ValueError("non-positive open lot")
            sig = t.get("entry_signal_strength", t.get("signal_strength"))
            if sig is not None:
                sig = _finite_number(sig)
                if not 0 <= sig <= 1:
                    raise ValueError("invalid signal strength")
            notional = _finite_number(qty * entry)
            max_loss = _finite_number(notional * _stop_loss_pct(sig))
            row = by_symbol.setdefault(sym, {"symbol": sym, "lots": 0, "max_loss": 0.0, "market_value": 0.0})
            row["lots"] += 1
            row["max_loss"] = _finite_number(row["max_loss"] + max_loss)
            row["market_value"] = _finite_number(row["market_value"] + notional)
            open_count += 1
        except (TypeError, ValueError, OverflowError):
            return _unavailable_risk("invalid_open_lot")

    try:
        total = _finite_number(sum(v["max_loss"] for v in by_symbol.values()))
        pct = _finite_number(total / equity)
    except (ValueError, OverflowError):
        return _unavailable_risk("risk_aggregation_overflow")
    return {
        "status": "ok", "open_trades_count": open_count,
        "total_open_risk": total, "pct_of_equity": pct,
        "warn_threshold": equity * WARN_PCT, "block_threshold": equity * BLOCK_PCT,
        "is_warn": pct >= WARN_PCT, "is_blocked": pct >= BLOCK_PCT,
        "per_symbol": sorted(by_symbol.values(), key=lambda x: -x["max_loss"]),
    }
