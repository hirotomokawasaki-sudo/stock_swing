"""One-shot migration: initialize peak_price for open trades that have peak_price=None.

Uses broker current_price as the baseline (conservative: treats today's price
as the peak, meaning no trailing stop is immediately active unless the position
is already up >= trailing_activation_pct from entry).

Usage:
    cd ~/stock_swing
    source venv/bin/activate
    python scripts/init_peak_prices.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

with open(PROJECT_ROOT / ".env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k] = v

from stock_swing.sources.broker_client import BrokerClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize peak_price for open trades")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    # Load state
    state_path = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    open_trades = [t for t in state["trades"] if t["status"] == "open"]

    need_init = [t for t in open_trades if t.get("peak_price") is None]
    print(f"Open trades total : {len(open_trades)}")
    print(f"peak_price=None   : {len(need_init)}")

    if not need_init:
        print("Nothing to do.")
        return

    # Fetch broker positions for current prices
    broker = BrokerClient(
        api_key=os.environ["BROKER_API_KEY"],
        api_secret=os.environ["BROKER_API_SECRET"],
        paper_mode=True,
    )
    positions_resp = broker.fetch_positions()
    positions = positions_resp.payload if hasattr(positions_resp, "payload") else positions_resp

    price_map: dict[str, float] = {}
    for pos in positions:
        sym = pos.get("symbol") or ""
        cp = pos.get("current_price")
        if sym and cp:
            try:
                price_map[sym] = float(cp)
            except (TypeError, ValueError):
                pass

    print(f"Broker positions fetched: {len(price_map)} symbols")

    updated = 0
    skipped_no_price = 0
    for trade in need_init:
        symbol = trade.get("symbol", "")
        entry_price = float(trade.get("entry_price") or 0)
        current_price = price_map.get(symbol)

        if current_price is None or current_price <= 0:
            # Fallback: use entry_price as conservative baseline
            current_price = entry_price
            if current_price <= 0:
                skipped_no_price += 1
                continue

        # Conservative: use max(entry, current) so we don't fire trailing
        # stop immediately on positions that haven't moved much
        peak = max(entry_price, current_price)
        ret = (current_price - entry_price) / entry_price if entry_price else 0.0
        peak_ret = (peak - entry_price) / entry_price if entry_price else 0.0

        print(
            f"  {symbol:6s}  entry={entry_price:.2f}  current={current_price:.2f}  "
            f"return={ret:+.1%}  → peak={peak:.2f} ({peak_ret:+.1%})"
        )

        if not args.dry_run:
            trade["peak_price"] = round(peak, 4)
        updated += 1

    print(f"\nSummary: {updated} trades to update, {skipped_no_price} skipped (no price)")

    if args.dry_run:
        print("DRY RUN — no changes written.")
        return

    # Backup
    backup_path = state_path.with_name(
        f"pnl_state_backup_before_peak_init_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    backup_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Backup: {backup_path.name}")

    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written: {state_path}")
    print(f"Done. {updated} open trades now have peak_price initialized.")


if __name__ == "__main__":
    main()
