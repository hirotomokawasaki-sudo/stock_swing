#!/usr/bin/env python3
"""G1: Manual circuit breaker clear (operator command).

使い方:
  python3 scripts/clear_circuit_breaker.py \
    --operator "HirotomoO" \
    --reason "SKYY phantom quarantined, META Lot2 verified filled, fresh broker fetch shows mismatch=0" \
    --confirmed-mismatch-count 0

circuit_breaker.json を halted → ok に変更する。
mismatch_count > 0 の場合は実行を拒否する。
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CB_PATH = PROJECT_ROOT / "data/guardrails/circuit_breaker.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator", required=True, help="Operator name/id")
    parser.add_argument(
        "--reason", required=True, help="Clear reason (why mismatch is resolved)"
    )
    parser.add_argument(
        "--confirmed-mismatch-count",
        type=int,
        required=True,
        help="Confirmed broker/tracker mismatch count from fresh broker fetch (must be 0)",
    )
    args = parser.parse_args()

    if args.confirmed_mismatch_count != 0:
        print(
            f"REFUSED: confirmed_mismatch_count={args.confirmed_mismatch_count} must be 0 before clearing."
        )
        return 1

    with open(CB_PATH, encoding="utf-8") as f:
        cb = json.load(f)

    if cb.get("status") != "halted":
        print(f"Circuit breaker is not halted (status={cb.get('status')}). No action needed.")
        return 0

    print("=== Circuit Breaker Clear Request ===")
    print(f"  Operator: {args.operator}")
    print(f"  Reason: {args.reason}")
    print(f"  Confirmed mismatch count: {args.confirmed_mismatch_count}")
    print(f"  Current status: {cb.get('status')}")
    confirm = input("Proceed? [yes/no]: ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return 0

    cb["status"] = "ok"
    cb["action"] = "none"
    cb["cleared_at"] = datetime.now(timezone.utc).isoformat()
    cb["cleared_by"] = args.operator
    cb["clear_note"] = args.reason
    cb["clear_confirmed_mismatch_count"] = args.confirmed_mismatch_count

    backup = CB_PATH.with_suffix(
        f".halted_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    shutil.copy2(CB_PATH, backup)

    tmp = CB_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cb, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CB_PATH)

    print(f"Circuit breaker cleared. Backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
