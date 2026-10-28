#!/usr/bin/env python3
"""Check genuine scheduled evidence separately from economic promotion.

Read-only unless --save is supplied. Never updates the ledger, Circuit
Breaker, economic-risk state or canonical console summary; never places orders.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from check_go_no_go import ECON_COHORT_START_DEFAULT, check_economic_viability
from stock_swing.guardrails.economic_risk_off import trading_session_dates_ending

ET = ZoneInfo("America/New_York")
SLOTS = (time(9, 25), time(9, 35), time(12), time(15, 55))


def expected_run_at(now: datetime) -> datetime:
    """Last scheduled paper slot, allowing ten minutes to complete."""
    cutoff = now.astimezone(ET) - timedelta(minutes=10)
    dates = trading_session_dates_ending(cutoff.date(), 2)
    candidates = [datetime.combine(datetime.fromisoformat(d).date(), slot, ET)
                  for d in dates for slot in SLOTS]
    return max(t for t in candidates if t <= cutoff).astimezone(timezone.utc)


def _read(path: Path) -> tuple[dict, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected object")
        return data, None
    except (OSError, ValueError, TypeError) as exc:
        return {}, type(exc).__name__


def _timestamp(value) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp if stamp.tzinfo is not None else None
    except ValueError:
        return None


def _fresh(value, expected: datetime, now: datetime) -> bool:
    stamp = _timestamp(value)
    return stamp is not None and expected <= stamp <= now + timedelta(minutes=1)


def _ready_candidates(history: list, lookback: int) -> int:
    """Count trailing independently reconstructible ready-session windows.

    This is not proof of promotion: replay, opportunity cost and approval are
    separate requirements. Invalid, duplicated or discontinuous dates fail closed.
    """
    dates = []
    for row in history:
        if not isinstance(row, dict):
            return 0
        try:
            day = datetime.fromisoformat(row["market_date"]).date()
            for key in ("start_equity", "latest_equity"):
                if not math.isfinite(float(row[key])) or float(row[key]) <= 0:
                    return 0
            for key in ("start_external_cash_flow", "latest_external_cash_flow"):
                if not math.isfinite(float(row[key])):
                    return 0
            first = _timestamp(row.get("first_observed_at"))
            last = _timestamp(row.get("last_observed_at"))
            if (first is None or last is None or first > last or
                first.astimezone(ET).date() != day or last.astimezone(ET).date() != day):
                return 0
            dates.append(day.isoformat())
        except (KeyError, ValueError, TypeError):
            return 0
    if dates != sorted(set(dates)):
        return 0
    count = 0
    for end in range(len(dates), lookback - 1, -1):
        window = dates[end - lookback:end]
        if window != trading_session_dates_ending(datetime.fromisoformat(window[-1]).date(), lookback):
            break
        count += 1
    return count


def _valid_observation(row: dict, now: datetime) -> bool:
    """Warm-up is healthy only with real, internally consistent observations."""
    if _ready_candidates([row], 1) != 1:
        return False
    stamp = _timestamp(row.get("last_observed_at"))
    return stamp is not None and stamp <= now + timedelta(minutes=1)


def assess(root: Path, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    expected = expected_run_at(now)
    summary, summary_error = _read(root / "reports/console/latest_console_summary.json")
    breaker, breaker_error = _read(root / "data/guardrails/circuit_breaker.json")
    risk, risk_error = _read(root / "data/guardrails/economic_risk_off.json")
    ledger, ledger_error = _read(root / "data/tracking/pnl_state.json")
    run = summary.get("run") if isinstance(summary.get("run"), dict) else {}
    history = risk.get("history") if isinstance(risk.get("history"), list) else []
    genuine = run.get("dry_run") is False and run.get("invocation_source") == "paper_demo_scheduled"
    console_fresh = genuine and _fresh(run.get("timestamp"), expected, now)
    breaker_fresh = _fresh(breaker.get("last_evaluated_at"), expected, now)
    latest_date = history[-1].get("market_date") if history and isinstance(history[-1], dict) else None
    observing = (not risk_error and bool(history) and latest_date == expected.astimezone(ET).date().isoformat()
                 and _valid_observation(history[-1], now)
                 and _fresh(risk.get("last_evaluated_at"), expected, now))
    if ledger_error or not isinstance(ledger.get("trades"), list):
        economics = {"pass": False, "actual": "ledger unavailable or corrupt", "cohort_start": ECON_COHORT_START_DEFAULT}
    else:
        economics = check_economic_viability(ledger, ECON_COHORT_START_DEFAULT)
        economics["cohort_start"] = ECON_COHORT_START_DEFAULT
    recovered = console_fresh and breaker_fresh and observing
    return {
        "as_of": now.isoformat(), "expected_run_at": expected.isoformat(),
        "operational_recovered": bool(recovered),
        "status": "recovered" if recovered else "awaiting_genuine_scheduled_evidence",
        "console": {"fresh": bool(console_fresh), "genuine": genuine, "timestamp": run.get("timestamp"), "error": summary_error},
        "circuit_breaker": {"fresh": bool(breaker_fresh), "status": breaker.get("status", "unknown"),
                            "last_evaluated_at": breaker.get("last_evaluated_at"), "error": breaker_error},
        "economic_risk_off": {"observing": bool(observing), "observed_sessions": len(history),
                              "ready_session_candidates": _ready_candidates(history, 5) if observing else 0,
                              "status": risk.get("status", "not_started"),
                              "data_status": risk.get("data_status", "no_forward_observations"), "error": risk_error},
        "economic_viability": economics,
        "promotion_authorized_by_this_check": False,
    }


def save_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".recovery-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--require-scheduled", action="store_true")
    args = parser.parse_args()
    report = assess(PROJECT_ROOT)
    if args.save:
        save_report(report, PROJECT_ROOT / "reports/operations/operational_recovery_status.json")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return int(args.require_scheduled and not report["operational_recovered"])


if __name__ == "__main__":
    raise SystemExit(main())
