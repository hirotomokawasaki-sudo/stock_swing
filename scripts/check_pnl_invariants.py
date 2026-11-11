#!/usr/bin/env python3
"""Descriptive PnL invariants for one coherent active-ledger observation.

The performance export must name the same ledger revision and exact state/event
hashes. A local accounting match is not qualified performance, G-M or promotion.
Exit 2 denotes an incomplete diagnostic (missing optional performance export).
No ledger repair or recovery is performed by this reader.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from stock_swing.tracking.compatibility import read_analysis_snapshot
from stock_swing.tracking.ledger_transaction import LedgerConflict

STATE_PATH = PROJECT_ROOT / "data/tracking/pnl_state.json"
PERF_PATH = PROJECT_ROOT / "data/analysis/performance_summary.json"
TOLERANCE = 1.00
PROVENANCE_KEYS = ("ledger_revision", "state_sha256", "events_sha256")


def _finite(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"invalid {field}: expected finite numeric value")
    return float(value)


def _sum(rows: list, field: str) -> float:
    return _finite(math.fsum(_finite(row.get("pnl"), field) for row in rows), field + " sum")


def assess(state_path: Path, perf_path: Path) -> dict:
    """Read coherent inputs and return scoped accounting checks without mutation."""
    report = {"status": "failed", "measurement_provenance": None,
              "scope": "descriptive_active_ledger_invariants_not_performance_qualification",
              "performance_qualified": False, "promotion_ready": False,
              "invariants": {}, "errors": []}
    try:
        state, context = read_analysis_snapshot(state_path)
        report["measurement_provenance"] = context
        if not isinstance(state.get("trades"), list):
            raise ValueError("invalid or missing trades collection")
        closed = [row for row in state["trades"] if row.get("status") == "closed"]
        quarantined = state.get("quarantined_trades", [])
        clean_sum = _sum(closed, "closed PnL")
        quarantine_sum = _sum(quarantined, "quarantined reference PnL")
        state_cum = _finite(state.get("cumulative_realized_pnl"), "cumulative_realized_pnl")
        delta = _finite(clean_sum - state_cum, "clean/state delta")
        report["closed_count"] = len(closed)
        report["quarantined_count"] = len(quarantined)
        report["clean_closed_pnl"] = clean_sum
        report["cumulative_realized_pnl"] = state_cum
        report["quarantined_reference_pnl"] = quarantine_sum
        report["invariants"]["clean_sum_matches_state"] = abs(delta) <= TOLERANCE
        if not report["invariants"]["clean_sum_matches_state"]:
            report["errors"].append("clean closed PnL differs from state cumulative beyond $1.00")
        try:
            raw = Path(perf_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            report["invariants"]["performance_export"] = "skipped_missing_export"
            if not report["errors"]:
                report["status"] = "diagnostic_only"
            return report
        perf = json.loads(raw)
        if not isinstance(perf, dict):
            raise ValueError("invalid performance summary: expected object")
        provenance = perf.get("measurement_provenance")
        if not isinstance(provenance, dict) or any(
                key not in provenance or provenance[key] != context[key] for key in PROVENANCE_KEYS):
            raise ValueError("performance summary provenance does not match exact active state/events observation")
        perf_real = _finite(perf.get("realized_pnl"), "performance realized_pnl")
        perf_delta = _finite(state_cum - perf_real, "state/performance delta")
        report["performance_realized_pnl"] = perf_real
        report["invariants"]["performance_export"] = abs(perf_delta) <= TOLERANCE
        if not report["invariants"]["performance_export"]:
            report["errors"].append("state cumulative differs from version-matched performance summary beyond $1.00")
        if not report["errors"]:
            report["status"] = "diagnostic_pass"
    except (OSError, ValueError, TypeError, OverflowError, LedgerConflict) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    return report


def main() -> int:
    report = assess(STATE_PATH, PERF_PATH)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return {"diagnostic_pass": 0, "diagnostic_only": 2}.get(report["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
