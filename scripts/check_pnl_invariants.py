#!/usr/bin/env python3
"""G3: PnL invariant checker.

Acceptance criteria:
  abs(sum(clean_closed.pnl) - state.cumulative_realized_pnl) <= 1.00
  abs(state.cumulative_realized_pnl - performance_summary.realized_pnl) <= 1.00
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
STATE_PATH = PROJECT_ROOT / "data/tracking/pnl_state.json"
PERF_PATH = PROJECT_ROOT / "data/analysis/performance_summary.json"
TOLERANCE = 1.00


def main() -> int:
    ok = True
    with open(STATE_PATH) as f:
        state = json.load(f)

    trades = state.get("trades", [])
    closed = [t for t in trades if t.get("status") == "closed"]
    quarantined = state.get("quarantined_trades", [])

    clean_sum = sum(t.get("pnl", 0) or 0 for t in closed)
    state_cum = state.get("cumulative_realized_pnl", 0)

    print("=== PnL Invariant Check ===")
    print(f"  Clean closed trades:    {len(closed)}")
    print(f"  Quarantined trades:     {len(quarantined)}")
    print(f"  clean_closed_sum:       ${clean_sum:,.2f}")
    print(f"  state.cumulative:       ${state_cum:,.2f}")
    print(f"  Delta:                  ${clean_sum - state_cum:,.2f}")

    inv1 = abs(clean_sum - state_cum) <= TOLERANCE
    if inv1:
        print(f"  ✅ INV1: clean_sum ≈ state.cumulative (within ${TOLERANCE:.2f})")
    else:
        print(
            f"  ❌ INV1 FAIL: |{clean_sum:.2f} - {state_cum:.2f}| = "
            f"{abs(clean_sum - state_cum):.2f} > ${TOLERANCE:.2f}"
        )
        ok = False

    if PERF_PATH.exists():
        with open(PERF_PATH) as f:
            perf = json.load(f)
        perf_real = perf.get("realized_pnl", 0)
        print(f"  performance_summary.realized: ${perf_real:,.2f}")
        inv2 = abs(state_cum - perf_real) <= TOLERANCE
        if inv2:
            print("  ✅ INV2: state.cumulative ≈ performance_summary.realized")
        else:
            print(
                f"  ❌ INV2 FAIL: |{state_cum:.2f} - {perf_real:.2f}| = "
                f"{abs(state_cum - perf_real):.2f} > ${TOLERANCE:.2f}"
            )
            ok = False
    else:
        print("  ⚠️  performance_summary.json not found — INV2 skipped")

    # Check quarantined exclusion
    q_sum = sum(t.get("pnl", 0) or 0 for t in quarantined)
    print(f"\n  Quarantined PnL (excluded from official):  ${q_sum:,.2f}")
    print(f"  Total (clean + quarantined):               ${clean_sum + q_sum:,.2f}")

    if ok:
        print("\n  ✅ All invariants PASS")
        return 0

    print("\n  ❌ Some invariants FAILED — run scripts/rebuild_pnl_source_of_truth.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
