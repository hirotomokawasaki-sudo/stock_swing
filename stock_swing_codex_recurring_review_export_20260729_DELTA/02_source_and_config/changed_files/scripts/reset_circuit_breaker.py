#!/usr/bin/env python3
"""Reset the circuit breaker after a HALT.

Normal usage (safe default):
    python scripts/reset_circuit_breaker.py --note "..."
    → status: recovery_pending (requires next clean scheduled run to return to ok)

Emergency override (audit-logged):
    python scripts/reset_circuit_breaker.py --note "..." --force-ok
    → status: ok (immediate, skips verification run)
    → Use only when you have confirmed the root cause and cleanup is complete.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore
from stock_swing.core.runtime import read_circuit_breaker_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", default="data/guardrails/circuit_breaker.json")
    parser.add_argument("--note", required=True, help="Explain why this reset is safe (min 12 chars)")
    parser.add_argument(
        "--force-ok",
        action="store_true",
        default=False,
        help=(
            "Skip recovery_pending and go directly to ok. "
            "Use only in emergencies. The override is recorded in the state file."
        ),
    )
    args = parser.parse_args()

    if len(args.note.strip()) < 12:
        raise SystemExit("--note must explain why reset is safe (min 12 chars)")

    # Read config to determine default behavior
    cb_cfg = read_circuit_breaker_config(PROJECT_ROOT)
    require_by_config = bool(cb_cfg.get("require_clean_run_after_manual_clear", True))

    # Determine require_verification:
    # - config says True AND caller did NOT pass --force-ok → require_verification=True
    # - config says False OR caller passed --force-ok → require_verification=False
    if args.force_ok:
        require_verification = False
        print("[WARN] --force-ok: skipping recovery_pending (override will be recorded)")
    else:
        require_verification = require_by_config
        if require_verification:
            print(
                "[INFO] require_clean_run_after_manual_clear=true: "
                "status will be recovery_pending until next clean scheduled run."
            )

    store = CircuitBreakerStore(PROJECT_ROOT / args.state)
    state = store.clear(
        cleared_by=getpass.getuser(),
        note=args.note,
        require_verification=require_verification,
    )
    print(json.dumps(asdict_compat(state), ensure_ascii=False, indent=2))
    return 0


def asdict_compat(state) -> dict:
    from dataclasses import asdict
    return asdict(state)


if __name__ == "__main__":
    raise SystemExit(main())
