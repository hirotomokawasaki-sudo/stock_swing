#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="data/guardrails/circuit_breaker.json")
    parser.add_argument("--note", required=True)
    args = parser.parse_args()

    if len(args.note.strip()) < 12:
        raise SystemExit("--note must explain why reset is safe (min 12 chars)")

    store = CircuitBreakerStore(Path(args.state))
    state = store.clear(cleared_by=getpass.getuser(), note=args.note)
    print(json.dumps(asdict_compat(state), ensure_ascii=False, indent=2))
    return 0


def asdict_compat(state) -> dict:
    from dataclasses import asdict
    return asdict(state)


if __name__ == "__main__":
    raise SystemExit(main())
