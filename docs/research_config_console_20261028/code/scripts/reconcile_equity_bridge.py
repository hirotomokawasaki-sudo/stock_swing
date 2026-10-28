#!/usr/bin/env python3
"""Build a read-only broker cash-flow reconciliation for the equity bridge.

The default mode prints the result only. ``--save`` atomically updates the
audited adjustment consumed by ``paper_demo``; it never rewrites the trade
ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.reporting.equity_bridge_reconciliation import (  # noqa: E402
    build_reconciliation_snapshot,
    compute_order_cash_realized,
    summarize_account_activities,
)
from stock_swing.sources.broker_client import BrokerClient  # noqa: E402

OUTPUT_PATH = PROJECT_ROOT / "data" / "audits" / "equity_bridge_reconciliation.json"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _fetch_all_activities(
    broker: BrokerClient,
    *,
    baseline_date: str,
    page_size: int = 100,
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    start = date.fromisoformat(baseline_date) - timedelta(days=1)
    params: dict[str, Any] = {
        "direction": "asc",
        "page_size": page_size,
        "after": f"{start.isoformat()}T00:00:00Z",
    }
    activities: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(max_pages):
        if page_token:
            params["page_token"] = page_token
        payload = broker.fetch(endpoint="v2/account/activities", **params).payload
        batch = payload if isinstance(payload, list) else []
        if not batch:
            return activities
        activities.extend(batch)
        if len(batch) < page_size:
            return activities
        next_token = str(batch[-1].get("id") or "")
        if not next_token or next_token == page_token:
            raise RuntimeError("account activity pagination cursor did not advance")
        page_token = next_token
    raise RuntimeError("account activity pagination hit max_pages")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help=f"Atomically write {OUTPUT_PATH}")
    parser.add_argument(
        "--max-account-check-diff",
        type=float,
        default=25.0,
        help="Refuse --save when broker equity cannot be independently reproduced",
    )
    args = parser.parse_args()

    _load_env(PROJECT_ROOT / ".env")
    api_key = os.environ.get("BROKER_API_KEY")
    api_secret = os.environ.get("BROKER_API_SECRET")
    if not api_key or not api_secret:
        print("ERROR: broker credentials are not configured", file=sys.stderr)
        return 2

    state_path = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    baseline_date = str(state.get("baseline_date") or "")
    baseline_equity = float(state.get("baseline_equity") or 0)
    if not baseline_date or baseline_equity <= 0:
        print("ERROR: pnl_state baseline metadata is missing", file=sys.stderr)
        return 2

    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
    orders_payload = broker.fetch_all_orders(status="all").payload
    if not isinstance(orders_payload, dict) or orders_payload.get("truncated"):
        print("ERROR: broker order history is incomplete", file=sys.stderr)
        return 2
    orders = list(orders_payload.get("orders") or [])
    positions = list(broker.fetch_positions().payload or [])
    account = dict(broker.fetch_account().payload or {})
    activities = _fetch_all_activities(broker, baseline_date=baseline_date)
    if any(float(position.get("qty") or 0) < 0 for position in positions):
        print("ERROR: short positions are not supported by this reconciliation", file=sys.stderr)
        return 2
    broker_account_id = account.get("account_number") or account.get("id")
    state_account_id = state.get("broker_account_id")
    if state_account_id and broker_account_id != state_account_id:
        print("ERROR: broker account does not match pnl_state", file=sys.stderr)
        return 2

    broker_realized, broker_by_symbol = compute_order_cash_realized(orders, positions)
    tracker_by_symbol: dict[str, float] = defaultdict(float)
    for trade in state.get("trades", []):
        if trade.get("status") == "closed":
            tracker_by_symbol[str(trade.get("symbol") or "").upper()] += float(trade.get("pnl") or 0)
    trade_sum_realized = sum(tracker_by_symbol.values())
    tracker_realized = float(state.get("cumulative_realized_pnl") or 0)
    if abs(trade_sum_realized - tracker_realized) > 0.01:
        print("ERROR: pnl_state cumulative realized does not match closed-trade sum", file=sys.stderr)
        return 2
    activity_summary = summarize_account_activities(activities, baseline_date=baseline_date)
    broker_unrealized = sum(float(position.get("unrealized_pl") or 0) for position in positions)
    quarantine = list(state.get("quarantined_trades") or [])
    last_filled_at = max(
        (str(order.get("filled_at") or "") for order in orders if float(order.get("filled_qty") or 0) > 0),
        default=None,
    )

    snapshot = build_reconciliation_snapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        broker_account_id=broker_account_id,
        baseline_date=baseline_date,
        baseline_equity=baseline_equity,
        tracker_realized=tracker_realized,
        broker_equity=float(account.get("equity") or 0),
        broker_unrealized=broker_unrealized,
        broker_order_cash_realized=broker_realized,
        broker_realized_by_symbol=broker_by_symbol,
        tracker_realized_by_symbol=dict(tracker_by_symbol),
        fees=float(activity_summary["fees"]),
        external_cash_adjustment=float(activity_summary["external_cash_adjustment"]),
        order_count=len(orders),
        activity_count=len(activities),
        last_filled_at=last_filled_at,
        quarantined_pnl_raw=sum(float(trade.get("pnl") or 0) for trade in quarantine),
        quarantine_count=len(quarantine),
        tracker_trades=state.get("trades", []),
    )
    snapshot["activity_counts"] = activity_summary["activity_counts"]

    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    if abs(float(snapshot["account_check_diff"])) > args.max_account_check_diff:
        print("ERROR: independent account check exceeded tolerance; not saving", file=sys.stderr)
        return 1
    if args.save:
        _atomic_write_json(OUTPUT_PATH, snapshot)
        print(f"Saved: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
