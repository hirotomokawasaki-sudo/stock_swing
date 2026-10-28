#!/usr/bin/env python3
"""G3: Rebuild PnL source-of-truth.

Clean closed trades の pnl 合計を公式 realized PnL にする。
quarantined trades は除外。
実行後に check_pnl_invariants.py を実行して検証できること。
"""

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
STATE_PATH = PROJECT_ROOT / "data/tracking/pnl_state.json"
PERF_PATH = PROJECT_ROOT / "data/analysis/performance_summary.json"


def main() -> int:
    # 1. load state
    with open(STATE_PATH) as f:
        state = json.load(f)

    trades = state.get("trades", [])
    closed = [t for t in trades if t.get("status") == "closed"]
    quarantined = state.get("quarantined_trades", [])

    # 2. compute clean closed sum
    clean_closed_sum = sum(t.get("pnl", 0) or 0 for t in closed)

    # 3. before values
    old_cumulative = state.get("cumulative_realized_pnl", 0)

    # 4. print report
    print("=== G3: PnL Source-of-Truth Rebuild ===")
    print(f"  Clean closed trades: {len(closed)}")
    print(f"  Quarantined trades:  {len(quarantined)}")
    print(f"  Clean closed PnL sum: ${clean_closed_sum:,.2f}")
    print(f"  State cumulative (before): ${old_cumulative:,.2f}")
    print(f"  Discrepancy: ${clean_closed_sum - old_cumulative:,.2f}")

    if abs(clean_closed_sum - old_cumulative) < 1.0:
        print("  ✅ Already consistent (within $1.00 tolerance).")
        return 0

    # 5. backup
    backup = STATE_PATH.with_suffix(
        f".pnl_sotr_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    shutil.copy2(STATE_PATH, backup)
    print(f"  Backup: {backup}")

    # 6. update state
    state["cumulative_realized_pnl"] = clean_closed_sum
    state["pnl_source_of_truth"] = "clean_closed_trades"
    state["pnl_sotr_updated_at"] = datetime.now(timezone.utc).isoformat()
    state["pnl_sotr_note"] = (
        f"G3 rebuild: cumulative_realized_pnl set to sum of {len(closed)} clean closed trades. "
        f"Quarantined {len(quarantined)} trades excluded. "
        f"Old value was {old_cumulative:.2f}."
    )

    # atomic write
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, STATE_PATH)
    print(f"  State updated: cumulative_realized_pnl = ${clean_closed_sum:,.2f}")

    # 7. update performance_summary.json if it exists
    if PERF_PATH.exists():
        with open(PERF_PATH) as f:
            perf = json.load(f)
        old_perf = perf.get("realized_pnl", 0)
        perf["realized_pnl"] = clean_closed_sum
        perf["realized_pnl_source"] = "clean_closed_trades"
        perf["realized_pnl_updated_at"] = datetime.now(timezone.utc).isoformat()
        perf["clean_closed_count"] = len(closed)
        perf["quarantined_count"] = len(quarantined)
        tmp2 = PERF_PATH.with_suffix(".tmp")
        with open(tmp2, "w") as f:
            json.dump(perf, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp2, PERF_PATH)
        print(
            f"  Performance summary updated: realized_pnl ${old_perf:,.2f} → ${clean_closed_sum:,.2f}"
        )

    print()
    print("  ✅ Done. Run scripts/check_pnl_invariants.py to verify.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
