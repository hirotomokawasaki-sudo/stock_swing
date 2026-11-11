#!/usr/bin/env python3
"""Corporate Action Detector — R7-A 基礎版

Compares broker avg_entry_price with the quantity-weighted tracker entry price
for open positions.
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
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from stock_swing.tracking.compatibility import read_analysis_snapshot, legacy_entrypoint

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
    data = json.loads(CORPORATE_ACTIONS_PATH.read_text(encoding="utf-8"))
    actions = data.get('actions') if isinstance(data, dict) else None
    if not isinstance(actions, list) or any(
        not isinstance(a, dict) or not isinstance(a.get('symbol'), str)
        or not a['symbol'].strip() for a in actions
    ):
        raise ValueError('invalid recorded corporate actions')
    return {(a['symbol'].upper(), a.get('ex_date', '')) for a in actions}


def _get_broker_positions() -> list[dict]:
    # DashboardService constructs PnLTracker and can recover a prepared write.
    # A broker-only GET must never instantiate that local ledger writer.
    from stock_swing.sources.broker_client import BrokerClient
    key, secret = os.environ.get('BROKER_API_KEY'), os.environ.get('BROKER_API_SECRET')
    if not key or not secret:
        raise RuntimeError('broker credentials unavailable')
    result = BrokerClient(api_key=key, api_secret=secret, paper_mode=True).fetch_positions()
    rows = result.payload if hasattr(result, 'payload') else result
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('invalid broker positions response')
    return rows


def _finite_number(value, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f'invalid {label}')
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f'invalid {label}')
    return result


def _get_tracker_open(state: dict | None = None) -> dict[str, dict]:
    """Return aggregate open tracker positions keyed by symbol.

    The tracker stores each entry lot as a separate trade while the broker
    exposes one blended average cost per symbol.  Comparing the broker average
    with a single tracker lot creates false corporate-action alerts, so combine
    every valid open lot using a quantity-weighted entry price.
    """
    if state is None:
        state, _ = read_analysis_snapshot(PNL_STATE_PATH)
    totals: dict[str, dict[str, float]] = {}
    for t in state.get('trades', []):
        if t.get('status') != 'open':
            continue
        symbol = t.get('symbol')
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError('invalid tracker symbol')
        symbol = symbol.upper()
        qty = _finite_number(t.get('qty'), 'tracker qty', positive=True)
        entry = _finite_number(t.get('entry_price'), 'tracker entry', positive=True)
        aggregate = totals.setdefault(symbol, {'qty': 0.0, 'cost': 0.0})
        aggregate['qty'] = _finite_number(aggregate['qty'] + qty, 'aggregate qty', positive=True)
        aggregate['cost'] = _finite_number(aggregate['cost'] + qty * entry, 'aggregate cost', positive=True)
    return {
        symbol: {
            'symbol': symbol,
            'status': 'open',
            'qty': aggregate['qty'],
            'entry_price': aggregate['cost'] / aggregate['qty'],
        }
        for symbol, aggregate in totals.items()
    }


def _closest_ratio(observed: float) -> tuple[float, float] | None:
    """Return (candidate_ratio, distance) if observed is close to a known split ratio."""
    best: tuple[float, float] | None = None
    for r in CANDIDATE_RATIOS:
        dist = abs(observed - r) / r
        if dist <= RATIO_TOLERANCE:
            if best is None or dist < best[1]:
                best = (r, dist)
    return best


def detect_anomalies(threshold: float = 0.05, *, tracker_open: dict | None = None) -> list[dict]:
    """Compare broker vs tracker entry prices; return list of anomaly dicts."""
    if isinstance(threshold, bool) or not math.isfinite(threshold) or threshold < 0:
        raise ValueError('invalid anomaly threshold')
    # Validate local inputs before any broker access or possible side effects.
    tracker_open = _get_tracker_open() if tracker_open is None else tracker_open
    known = _load_known_actions()
    broker_pos = _get_broker_positions()
    anomalies: list[dict] = []

    for bp in broker_pos:
        sym = bp.get('symbol')
        if not isinstance(sym, str) or not sym.strip():
            raise ValueError('invalid broker symbol')
        sym = sym.upper()
        broker_entry = _finite_number(bp.get('avg_entry_price'), 'broker entry', positive=True)
        broker_current = _finite_number(bp.get('current_price', 0.0), 'broker current')
        broker_qty = _finite_number(bp.get('qty'), 'broker qty')
        tracker = tracker_open.get(sym)

        if not tracker or not broker_entry:
            continue

        tracker_entry = _finite_number(tracker.get('entry_price'), 'tracker entry', positive=True)
        tracker_qty = _finite_number(tracker.get('qty'), 'tracker qty', positive=True)

        # Price ratio: broker_entry / tracker_entry
        ratio = _finite_number(broker_entry / tracker_entry, 'entry ratio', positive=True)

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
            "broker_qty": broker_qty,
            "tracker_qty": tracker_qty,
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


@legacy_entrypoint(lambda *a, **kw: CORPORATE_ACTIONS_PATH.parent.parent)
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
    try:
        state, provenance = read_analysis_snapshot(PNL_STATE_PATH)
        anomalies = detect_anomalies(threshold=args.threshold, tracker_open=_get_tracker_open(state))
    except Exception as exc:
        print(f'UNAVAILABLE: corporate action input: {exc}', file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "measurement_provenance": provenance,
            "scope": "open_position_comparison_only_not_historical_CA_clearance",
        }, ensure_ascii=False, indent=2))
        return 1 if anomalies else 0

    print('MEASUREMENT_PROVENANCE_JSON=' + json.dumps(provenance, sort_keys=True))
    print('Scope: current open positions only; no historical corporate-action clearance or promotion.')
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
