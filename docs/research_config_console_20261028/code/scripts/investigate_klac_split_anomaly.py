#!/usr/bin/env python3
"""FIX-LEDGER-3: Investigate KLAC split anomaly in pnl_state.json.

broker_match_0117_KLAC:
  entry_price=2126.92  exit_price=253.5  qty=21  pnl=-39341.89

This is consistent with an unadjusted split:
  2126.92 / 8 = 265.87  (post-split expected range ~$240-270 in Jun 2026)
  The entry_price was recorded at pre-split prices, while the exit used post-split prices.
  Or: entry was pre-split (×8 quantity error).

This script:
1. Loads the closed KLAC trades and identifies the anomaly.
2. Checks corporate_actions.json for a KLAC split event.
3. Outputs a JSON report with evidence.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

project_root = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    ps_path = project_root / "data/tracking/pnl_state.json"
    ca_path = project_root / "data/corporate_actions.json"

    ps = json.loads(ps_path.read_text())
    closed = ps.get("trades", [])
    klac_trades = [t for t in closed if t.get("symbol") == "KLAC"]

    print(f"KLAC closed trades: {len(klac_trades)}")
    for t in klac_trades:
        ep = t.get("entry_price", 0)
        xp = t.get("exit_price", 0)
        ratio = round(ep / xp, 2) if xp else None
        print(
            f"  {t['trade_id']}: entry=${ep:.2f} exit=${xp:.2f} qty={t.get('qty')} "
            f"pnl=${t.get('pnl', 0):.2f} ratio={ratio}"
        )

    # Identify anomalous trade
    anomalous = [t for t in klac_trades if t.get("entry_price", 0) > 1000]
    print(f"\nAnomalous (entry>$1000): {len(anomalous)}")
    for t in anomalous:
        print(f"  {json.dumps(t, default=str)}")

    # Check corporate actions
    ca_data = {}
    if ca_path.exists():
        ca_data = json.loads(ca_path.read_text())
    klac_actions = [
        a for a in ca_data.get("corporate_actions", [])
        if a.get("symbol") == "KLAC"
    ] if isinstance(ca_data, dict) else []
    print(f"\nKLAC corporate actions in registry: {len(klac_actions)}")
    for a in klac_actions:
        print(f"  {json.dumps(a, default=str)}")

    # Analysis
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": "KLAC",
        "anomalous_trades": anomalous,
        "corporate_actions_found": klac_actions,
        "analysis": {
            "hypothesis": (
                "broker_match_0117_KLAC entry_price=2126.92 is pre-split (×8 split ratio: "
                "2126.92/8=265.87 matches post-split trading range of $240-270 in Jun 2026). "
                "Exit at $253.50 is in the post-split range. The trade tracker recorded "
                "the entry at pre-split price but exit at post-split price, causing a "
                "spurious loss of -$39,341.89."
            ),
            "split_ratio_implied": round(anomalous[0]["entry_price"] / anomalous[0]["exit_price"], 2) if anomalous else None,
            "correction_needed": (
                "entry_price should be adjusted to entry_price/split_ratio (~$265.87), "
                "OR the trade should be quarantined as a split-affected record. "
                "Requires confirmation against broker fill activity for 2026-06-09 to 2026-06-12."
            ),
        },
        "all_klac_trades": klac_trades,
    }

    report_path = project_root / "data/audits/klac_split_investigation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nReport written to: {report_path.relative_to(project_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
