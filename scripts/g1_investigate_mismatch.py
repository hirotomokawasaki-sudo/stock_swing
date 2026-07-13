#!/usr/bin/env python3
"""G1: Broker/Tracker mismatch investigation report.

Produces a reconciliation report for the 2026-07-10 phantom positions.
Does NOT auto-clear circuit breaker.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def main():
    with open(PROJECT_ROOT / "data/tracking/pnl_state.json", encoding="utf-8") as f:
        state = json.load(f)
    with open(PROJECT_ROOT / "data/guardrails/circuit_breaker.json", encoding="utf-8") as f:
        cb = json.load(f)

    trades = state.get("trades", [])
    open_t = [t for t in trades if t.get("status") == "open"]

    skyy = [t for t in open_t if t.get("symbol") == "SKYY"]
    meta = [t for t in open_t if t.get("symbol") == "META"]

    print("=== G1: Broker/Tracker Mismatch Investigation ===")
    print(f"\nCircuit Breaker Status: {cb.get('status')}")
    print(f"Triggered at: {cb.get('triggered_at')}")
    print(f"Reason: {cb.get('reason')}")

    print("\n--- SKYY (tracker-only phantom) ---")
    for t in skyy:
        print(f"  trade_id: {t.get('trade_id')}")
        print(f"  qty: {t.get('qty')}")
        print(f"  entry_time: {t.get('entry_time')}")
        print(f"  broker_order_id: {t.get('broker_order_id')}")
        print(f"  entry_price: {t.get('entry_price')}")
        print("  ROOT CAUSE: Submitted 2s before circuit breaker fired at 13:35:56.")
        print("  BROKER: 0 qty (unfilled or rejected)")
        print(
            "  ACTION NEEDED: Close/cancel this phantom position after broker order verification."
        )

    print("\n--- META (qty mismatch) ---")
    for t in meta:
        print(f"  trade_id: {t.get('trade_id')}")
        print(f"  qty: {t.get('qty')}")
        print(f"  entry_time: {t.get('entry_time')}")
        print(f"  broker_order_id: {t.get('broker_order_id')}")
    total_meta_qty = sum(t.get("qty", 0) for t in meta)
    print(f"  TRACKER total qty: {total_meta_qty} (Lot1=33 + Lot2=45)")
    print("  BROKER qty: 33 (Lot1 confirmed only)")
    print(
        "  ROOT CAUSE: Lot2 (45 shares) submitted at 13:35:47, broker confirmation uncertain."
    )
    print(
        "  ACTION NEEDED: Verify broker_order_id ff2b3a4f status. If unfilled, remove Lot2 from tracker."
    )

    print("\n--- Resolution Path ---")
    print("  1. Verify broker order status via Alpaca API:")
    print("     GET /v2/orders/adc2721b-28d2-401d-aca8-ded0d9fbe090  (SKYY)")
    print("     GET /v2/orders/ff2b3a4f-c144-4979-a95e-f24eaf0a29a8  (META Lot2)")
    print("  2. If status=canceled/rejected/expired: quarantine phantom trades")
    print("  3. Run scripts/clear_circuit_breaker.py with mismatch_count=0 confirmed")
    print(
        "  4. circuit_breaker.json must not be cleared until fresh broker fetch shows mismatch_count=0"
    )

    print("\n  [!] DO NOT clear circuit breaker without fresh broker fetch confirming mismatch_count=0")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "circuit_breaker": cb,
        "skyy_phantom": skyy,
        "meta_lots": meta,
        "meta_tracker_total_qty": total_meta_qty,
        "meta_broker_qty": 33,
        "root_cause": "Orders submitted immediately before circuit breaker halt at 2026-07-10T13:35:56Z",
        "resolution_required": True,
        "blocker": "Must verify broker order status before clearing circuit breaker",
    }

    out = PROJECT_ROOT / "data/analysis/g1_mismatch_investigation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Report saved: {out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
