#!/usr/bin/env python3
"""Build performance summary with correct semantics (P1-B)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.cli.paper_demo import _load_env

_load_env(PROJECT_ROOT / ".env")

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.pnl_tracker import PnLTracker


def main() -> None:
    broker = BrokerClient(
        api_key=os.environ["BROKER_API_KEY"],
        api_secret=os.environ["BROKER_API_SECRET"],
        paper_mode=True,
    )
    tracker = PnLTracker(PROJECT_ROOT)

    acct = broker.fetch_account().payload
    account_equity = float(acct.get("equity", 0))
    baseline_equity = tracker.state.baseline_equity or 100_000.0

    summary = tracker.get_summary()
    closed = [t for t in tracker.state.trades if t.get("status") == "closed"]
    open_trades = [t for t in tracker.state.trades if t.get("status") == "open"]

    realized_pnl = sum(t.get("pnl", 0) or 0 for t in closed)

    try:
        pos_env = broker.fetch_positions()
        positions = pos_env.payload if hasattr(pos_env, "payload") else pos_env
        pos_by_sym = {}
        if isinstance(positions, list):
            for pos in positions:
                sym = str(pos.get("symbol", "")).upper()
                pos_by_sym[sym] = {
                    "current_price": float(pos.get("current_price", 0) or 0),
                    "unrealized_pl": float(pos.get("unrealized_pl", 0) or 0),
                }
        unrealized_pnl = sum(v["unrealized_pl"] for v in pos_by_sym.values())
    except Exception:
        unrealized_pnl = 0.0

    total_pnl = realized_pnl + unrealized_pnl
    wins = [t for t in closed if (t.get("pnl") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl") or 0) < 0]
    gross_win = sum(t.get("pnl", 0) or 0 for t in wins)
    gross_loss = abs(sum(t.get("pnl", 0) or 0 for t in losses))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": {
            "realized_pnl": "sum of pnl from all closed trades in tracker",
            "unrealized_pnl": "sum of unrealized_pl from broker positions",
            "total_pnl": "realized_pnl + unrealized_pnl",
            "account_equity": "broker account.equity (includes cash + open positions)",
            "baseline_equity": "equity at tracking start",
        },
        "baseline_equity": round(baseline_equity, 2),
        "account_equity": round(account_equity, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "pnl_vs_baseline": round(account_equity - baseline_equity, 2),
        "closed_trades": len(closed),
        "open_trades": len(open_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / len(closed), 4) if closed else 0,
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else None,
        "gross_win": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "consistency_check": {
            "realized_matches_tracker": abs(
                realized_pnl - (summary.get("cumulative_realized_pnl") or 0)
            ) < 1.0,
            "note": "account_equity != baseline + total_pnl is normal due to cash flows and timing",
        },
    }

    out_path = PROJECT_ROOT / "data" / "analysis" / "performance_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
