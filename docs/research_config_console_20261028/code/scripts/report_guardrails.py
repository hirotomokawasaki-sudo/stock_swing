#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="data/guardrails/circuit_breaker.json")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    state = CircuitBreakerStore(Path(args.state)).load()
    lines = [
        "# Guardrail Status",
        "",
        f"- status: {state.status}",
        f"- action: {state.action}",
        f"- reason: {state.reason}",
        f"- triggered_at: {state.triggered_at}",
        f"- cleared_at: {state.cleared_at}",
        "",
        "## Triggered Rules",
        "",
    ]

    if state.triggered_rules:
        for rule in state.triggered_rules:
            lines.append(
                f"- {rule.get('name')}: {rule.get('metric')}={rule.get('observed')} "
                f"{rule.get('operator')} {rule.get('threshold')} -> {rule.get('action')}"
            )
    else:
        lines.append("- none")

    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
