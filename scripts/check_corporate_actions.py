#!/usr/bin/env python3
"""Corporate Action Detector — R7-A 基礎版

Compares broker avg_entry_price with tracker entry_price for open positions.
Flags potential unrecorded splits / reverse-splits by detecting price ratios
close to common corporate-action factors.

Usage:
    python scripts/check_corporate_actions.py [--dry-run] [--threshold 0.05]

Exit codes:
    0 — no anomalies detected
    1 — anomalies found (see stdout)
    2 — runtime error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

CORPORATE_ACTIONS_PATH = PROJECT_ROOT / "data" / "corporate_actions.json"
PNL_STATE_PATH = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"

# Common split / reverse-split ratios to test against
CANDIDATE_RATIOS = [2.0, 3.0, 4.0, 5.0, 10.0, 0.5, 0.333, 0.25, 0.2, 0.1]
RATIO_TOLERANCE = 0.08   # within 8% of a candidate ratio → flag as potential split


def _load_env() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def _load_known_actions() -> set[tuple[str, str]]:
    """Return set of (symbol, ex_date) for already-recorded actions."""
    if not CORPORATE_ACTIONS_PATH.exists():
        return set()
    try:
        data = json.loads(CORPORATE_ACTIONS_PATH.read_text(encoding="utf-8"))
        return {
            (a["symbol"].upper(), a.get("ex_date", ""))
            for a in data.get("actions", [])
        }
    except Exception:
        return set()


def _get_broker_positions() -> list[dict]:
    try:
        from console.services.dashboard_service import DashboardService
        dashboard = DashboardService(PROJECT_ROOT)
        return dashboard._get_broker_positions()
    except Exception as exc:
        print(f"[WARN] Could not fetch broker positions: {exc}", file=sys.stderr)
        return []


def _get_tracker_open() -> dict[str, dict]:
    """Return {symbol: trade} for open tracker positions."""
    if not PNL_STATE_PATH.exists():
        return {}
    try:
        state = json.loads(PNL_STATE_PATH.read_text(encoding="utf-8"))
        result: dict[str, dict] = {}
        for t in state.get("trades", []):
            if t.get("status") == "open":
                sym = str(t.get("symbol") or "").upper()
                # keep highest-qty entry if duplicate
                if sym not in result or (t.get("qty") or 0) > (result[sym].get("qty") or 0):
                    result[sym] = t
        return result
    except Exception as exc:
        print(f"[WARN] Could not read pnl_state.json: {exc}", file=sys.stderr)
        return {}


def _closest_ratio(observed: float) -> tuple[float, float] | None:
    """Return (candidate_ratio, distance) if observed is close to a known split ratio."""
    best: tuple[float, float] | None = None
    for r in CANDIDATE_RATIOS:
        dist = abs(observed - r) / r
        if dist <= RATIO_TOLERANCE:
            if best is None or dist < best[1]:
                best = (r, dist)
    return best


def detect_anomalies(threshold: float = 0.05) -> list[dict]:
    """Compare broker vs tracker entry prices; return list of anomaly dicts."""
    known = _load_known_actions()
    broker_pos = _get_broker_positions()
    tracker_open = _get_tracker_open()
    anomalies: list[dict] = []

    for bp in broker_pos:
        sym = str(bp.get("symbol") or "").upper()
        broker_entry = float(bp.get("avg_entry_price") or 0.0)
        broker_current = float(bp.get("current_price") or 0.0)
        tracker = tracker_open.get(sym)

        if not tracker or not broker_entry:
            continue

        tracker_entry = float(tracker.get("entry_price") or 0.0)
        if not tracker_entry:
            continue

        # Price ratio: broker_entry / tracker_entry
        ratio = broker_entry / tracker_entry

        # Already close to 1.0 → no issue
        if abs(ratio - 1.0) <= threshold:
            continue

        # Check if it looks like a known split ratio
        match = _closest_ratio(ratio)
        anomaly: dict = {
            "symbol": sym,
            "broker_entry": broker_entry,
            "tracker_entry": tracker_entry,
            "ratio": round(ratio, 4),
            "broker_current": broker_current,
            "broker_qty": int(float(bp.get("qty") or 0)),
            "tracker_qty": int(float(tracker.get("qty") or 0)),
            "already_recorded": any(k[0] == sym for k in known),
        }
        if match:
            candidate_ratio, dist = match
            if candidate_ratio > 1.0:
                action_type = f"forward split ~1:{int(candidate_ratio)}"
            else:
                action_type = f"reverse split ~{candidate_ratio:.2f}:1"
            anomaly["suspected_action"] = action_type
            anomaly["candidate_ratio"] = candidate_ratio
        else:
            anomaly["suspected_action"] = "unknown_price_discrepancy"

        anomalies.append(anomaly)

    return anomalies


def register_action(action: dict) -> None:
    """Append a new action to corporate_actions.json."""
    if CORPORATE_ACTIONS_PATH.exists():
        data = json.loads(CORPORATE_ACTIONS_PATH.read_text(encoding="utf-8"))
    else:
        data = {"_schema": "corporate_actions_v1", "actions": []}
    data["actions"].append(action)
    tmp = CORPORATE_ACTIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CORPORATE_ACTIONS_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect unrecorded corporate actions")
    parser.add_argument("--threshold", type=float, default=0.05,
                        help="Acceptable price ratio deviation from 1.0 (default: 0.05 = 5%%)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    _load_env()
    anomalies = detect_anomalies(threshold=args.threshold)

    if args.json:
        print(json.dumps({
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
        }, ensure_ascii=False, indent=2))
        return 1 if anomalies else 0

    if not anomalies:
        print("✅  No corporate action anomalies detected.")
        return 0

    print(f"⚠️  {len(anomalies)} potential corporate action(s) detected:\n")
    for a in anomalies:
        recorded = "（登録済み）" if a.get("already_recorded") else "【未登録】"
        print(f"  {a['symbol']:8} {recorded}")
        print(f"    suspected : {a.get('suspected_action', 'unknown')}")
        print(f"    ratio     : broker_entry ${a['broker_entry']:.2f} / tracker_entry ${a['tracker_entry']:.2f} = {a['ratio']:.4f}x")
        print(f"    qty       : broker={a['broker_qty']}  tracker={a['tracker_qty']}")
        print(f"    current   : ${a['broker_current']:.2f}")
        print()

    if any(not a.get("already_recorded") for a in anomalies):
        print("→ 未登録の anomaly があります。data/corporate_actions.json に追記してください。")
        print("  または scripts/check_corporate_actions.py で register_action() を呼び出してください。")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
