#!/usr/bin/env python3
"""Generate price overrides for stale broker position prices.

Uses Massive daily bars as the primary fresh-price source and writes
`data/price_overrides.json` for downstream consumers such as SimpleExitV2Strategy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.massive_client import MassiveClient
from stock_swing.utils.stale_price import apply_empty_override_guard, compute_stale_price_overrides


def load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")


def load_existing_overrides(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"overrides": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"overrides": {}}


def build_overrides(
    *,
    broker: BrokerClient,
    massive: MassiveClient,
    min_deviation_pct: float,
    previous_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    positions_env = broker.fetch_positions()
    positions = positions_env.payload if hasattr(positions_env, "payload") else positions_env
    return compute_stale_price_overrides(
        positions,
        massive,
        min_deviation_pct=min_deviation_pct,
        previous_overrides=previous_overrides,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-deviation-pct", type=float, default=5.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env()

    broker = BrokerClient(
        api_key=os.environ.get("BROKER_API_KEY", ""),
        api_secret=os.environ.get("BROKER_API_SECRET", ""),
        paper_mode=True,
    )
    massive = MassiveClient(api_key=os.environ.get("MASSIVE_API_KEY"))

    output_path = PROJECT_ROOT / "data" / "price_overrides.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    previous = load_existing_overrides(output_path)
    previous_overrides = previous.get("overrides", {}) if isinstance(previous, dict) else {}

    new_overrides, logs, errors = build_overrides(
        broker=broker,
        massive=massive,
        min_deviation_pct=args.min_deviation_pct,
        previous_overrides=previous_overrides,
    )

    generated_at = datetime.now(UTC).isoformat()
    final_overrides, guard_applied, clear_pending, clear_pending_since = apply_empty_override_guard(
        new_overrides=new_overrides,
        previous_payload=previous,
        generated_at=generated_at,
    )

    print("Fetching fresh prices for broker positions from Massive API...")
    for line in logs:
        print(line)
    if guard_applied:
        print("  🛡️  Empty override write guard preserved previous overrides; a second consecutive empty run is required to clear them")

    output: dict[str, Any] = {
        "schema_version": "v1",
        "generated_at": generated_at,
        "note": "Fresh prices from Massive API to override stale broker positions API prices",
        "overrides": final_overrides,
    }
    if clear_pending:
        output["clear_pending"] = True
        output["clear_pending_since"] = clear_pending_since

    if not args.dry_run:
        output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"\n✓ Generated price overrides for {len(final_overrides)} symbols")
    print(f"  Saved to: {output_path}")
    if errors:
        print(f"  Errors: {len(errors)}")
        for err in errors[:20]:
            print(f"    - {err}")
    else:
        print("  Errors: none")

    if args.dry_run:
        print("\n(dry-run: file not written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
