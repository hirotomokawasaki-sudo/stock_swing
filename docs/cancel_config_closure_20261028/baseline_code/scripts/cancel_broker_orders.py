#!/usr/bin/env python3
"""Preview or cancel specific broker orders.

Usage:
    python scripts/cancel_broker_orders.py --preset stale-paper-demo-20260527
    python scripts/cancel_broker_orders.py --order-id <id> --order-id <id> --execute
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(PROJECT_ROOT / ".env")

from stock_swing.sources.broker_client import BrokerClient


OPEN_STATUSES = {"accepted", "new", "pending_new", "submitted", "partially_filled"}
KNOWN_PRESETS: dict[str, list[tuple[str, str]]] = {
    "stale-paper-demo-20260527": [
        ("SMCI", "c1475b84-d1c3-4fb8-bfde-6468c49d3d1c"),
        ("RBRK", "9751c88d-9fca-4eea-9a6a-087f6189840c"),
        ("PANW", "5ae6d11e-03ea-4cfe-9131-5648c25b65e7"),
        ("QCOM", "6330ca5a-2f03-48b9-81d4-8575dcb6cc3b"),
        ("DDOG", "ab9de2f0-73eb-499a-ac71-13a266bcc054"),
        ("MDB", "4842ca25-8358-40a6-9930-fa934d96ed3d"),
        ("SNOW", "2bf460f1-f749-4f34-8ef4-0c7ffdca2071"),
    ],
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        choices=sorted(KNOWN_PRESETS.keys()),
        help="Use a named set of known order IDs.",
    )
    parser.add_argument(
        "--order-id",
        action="append",
        default=[],
        help="Broker order ID to inspect/cancel. Can be passed multiple times.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually submit cancel requests. Without this flag the script only previews.",
    )
    return parser


def _resolve_targets(args: argparse.Namespace) -> list[tuple[str | None, str]]:
    targets: list[tuple[str | None, str]] = []
    if args.preset:
        targets.extend(KNOWN_PRESETS[args.preset])
    targets.extend((None, oid) for oid in args.order_id)

    seen: set[str] = set()
    resolved: list[tuple[str | None, str]] = []
    for symbol, order_id in targets:
        if order_id in seen:
            continue
        seen.add(order_id)
        resolved.append((symbol, order_id))
    return resolved


def main() -> int:
    args = _build_parser().parse_args()
    targets = _resolve_targets(args)
    if not targets:
        print("ERROR: specify --preset or at least one --order-id", file=sys.stderr)
        return 2

    api_key = os.environ.get("BROKER_API_KEY", "")
    api_secret = os.environ.get("BROKER_API_SECRET", "")
    if not api_key or not api_secret:
        print("ERROR: BROKER_API_KEY / BROKER_API_SECRET missing", file=sys.stderr)
        return 2

    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)

    print(f"MODE: {'EXECUTE' if args.execute else 'PREVIEW'}")
    print(f"TARGET_COUNT: {len(targets)}")

    cancelable: list[tuple[str, str]] = []
    for expected_symbol, order_id in targets:
        order_env = broker.fetch_order(order_id)
        order = order_env.payload if hasattr(order_env, "payload") else order_env
        symbol = str(order.get("symbol") or expected_symbol or "unknown").upper()
        status = str(order.get("status") or "").lower()
        qty = order.get("qty")
        filled_qty = order.get("filled_qty")
        submitted_at = order.get("submitted_at")
        expires_at = order.get("expires_at") or order.get("expired_at")
        extended_hours = order.get("extended_hours")
        is_cancelable = status in OPEN_STATUSES

        print(
            f"{symbol}\t{order_id}\tstatus={status}\tqty={qty}\tfilled_qty={filled_qty}"
            f"\tsubmitted_at={submitted_at}\texpires_at={expires_at}\textended_hours={extended_hours}"
        )
        if is_cancelable:
            cancelable.append((symbol, order_id))

    print(f"CANCELABLE_COUNT: {len(cancelable)}")
    if not args.execute:
        print("Preview only. Re-run with --execute to submit DELETE requests.")
        return 0

    canceled = 0
    for symbol, order_id in cancelable:
        broker.fetch(endpoint=f"v2/orders/{order_id}", method="DELETE")
        print(f"CANCEL_REQUESTED: {symbol} {order_id}")
        canceled += 1

    print(f"CANCEL_REQUESTED_COUNT: {canceled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
