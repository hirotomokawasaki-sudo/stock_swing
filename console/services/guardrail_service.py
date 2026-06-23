"""Risk guardrail status service.

Reads P0 safety settings from source code + env, and audits open positions
for missing entry_signal_strength.  No broker credentials required.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any


def _etf_position_multiplier() -> tuple[float, str | None]:
    """Read ETF_POSITION_SIZE_MULTIPLIER from position_sizing module."""
    try:
        import importlib
        mod = importlib.import_module("stock_swing.risk.position_sizing")
        return float(mod.ETF_POSITION_SIZE_MULTIPLIER), None
    except Exception as exc:
        # Fallback: grep the source file
        try:
            src = Path(__file__).parents[2] / "src/stock_swing/risk/position_sizing.py"
            for line in src.read_text().splitlines():
                if "ETF_POSITION_SIZE_MULTIPLIER" in line and "=" in line:
                    val = line.split("=")[1].strip().split("#")[0].strip()
                    return float(val), None
        except Exception:
            pass
        return 0.35, f"Import failed ({exc}); using hardcoded fallback 0.35"


def _missing_strength_policy() -> dict[str, Any]:
    """Read _resolve_thresholds(None) from SimpleExitV2Strategy."""
    try:
        import importlib
        mod = importlib.import_module("stock_swing.strategy_engine.simple_exit_v2_strategy")
        strat = mod.SimpleExitV2Strategy()
        stop, trail = strat._resolve_thresholds(None)
        return {"mode": "conservative", "stop_loss_pct": stop, "take_profit_pct": trail}
    except Exception:
        return {"mode": "conservative", "stop_loss_pct": -0.05, "take_profit_pct": 0.10,
                "note": "fallback (import failed)"}


def _open_position_audit(project_root: Path) -> tuple[dict[str, Any], list[str]]:
    """Count open positions and missing entry_signal_strength."""
    warnings: list[str] = []

    # Try exports/open_positions.csv first
    csv_path = project_root / "exports/open_positions.csv"
    if csv_path.exists():
        try:
            rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
            total = len(rows)
            missing = sum(
                1 for r in rows
                if not r.get("entry_signal_strength") or r["entry_signal_strength"].strip() in ("", "None")
            )
            return {
                "total": total,
                "missing_entry_signal_strength": missing,
                "missing_strength_ratio": round(missing / total, 4) if total else 0.0,
                "source": "exports/open_positions.csv",
            }, warnings
        except Exception as exc:
            warnings.append(f"Could not parse open_positions.csv: {exc}")

    # Fallback: pnl_state.json
    state_path = project_root / "data/tracking/pnl_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            open_trades = [t for t in state.get("trades", []) if t.get("status") == "open"]
            total = len(open_trades)
            missing = sum(1 for t in open_trades if t.get("entry_signal_strength") is None)
            return {
                "total": total,
                "missing_entry_signal_strength": missing,
                "missing_strength_ratio": round(missing / total, 4) if total else 0.0,
                "source": "data/tracking/pnl_state.json",
            }, warnings
        except Exception as exc:
            warnings.append(f"Could not parse pnl_state.json: {exc}")

    warnings.append("No open position data available")
    return {"total": 0, "missing_entry_signal_strength": 0, "missing_strength_ratio": 0.0}, warnings


def get_guardrail_status(project_root: Path) -> dict[str, Any]:
    """Return current P0 guardrail settings and open-position audit.

    Args:
        project_root: Absolute path to repo root.
    """
    warnings: list[str] = []

    # ETF buy guardrail
    etf_buys_enabled = os.environ.get("PAPER_DEMO_ALLOW_ETF_BUYS", "").lower() == "true"

    # ETF position multiplier
    multiplier, mult_warn = _etf_position_multiplier()
    if mult_warn:
        warnings.append(mult_warn)

    # Missing price fallback: after P0, final_shares=0 (not proposed.qty=10)
    # We detect this by inspecting source; keep it as a static flag.
    missing_price_fallback_enabled = False  # P0 fixed: returns 0, not placeholder qty

    # Placeholder position limit: removed in P0
    placeholder_position_limit_enabled = False

    # Missing strength policy
    missing_policy = _missing_strength_policy()

    # Open position audit
    audit, audit_warns = _open_position_audit(project_root)
    warnings.extend(audit_warns)

    # ETF buys are now intentionally enabled (ETF PF=2.776 per broker data, 2026-06-23)
    # Guard against accidental disablement instead
    if not etf_buys_enabled:
        warnings.append(
            "ETF buys are disabled. "
            "Intentional? Set PAPER_DEMO_ALLOW_ETF_BUYS=true to re-enable "
            "(actual ETF PF=2.776, validated 2026-06-23)."
        )

    # Overall status
    risks = []
    # ETF cap: warn if multiplier significantly exceeds restored baseline of 0.70
    if multiplier > 1.0:
        risks.append(f"ETF position multiplier {multiplier} > 1.0 — unusually high")
    status = "at_risk" if risks else "guarded"

    return {
        "status": status,
        "etf_buys_enabled": etf_buys_enabled,
        "etf_position_multiplier": multiplier,
        "missing_price_fallback_enabled": missing_price_fallback_enabled,
        "placeholder_position_limit_enabled": placeholder_position_limit_enabled,
        "missing_strength_policy": missing_policy,
        "open_position_audit": audit,
        "risks": risks,
        "warnings": warnings,
    }
