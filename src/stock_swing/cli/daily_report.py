#!/usr/bin/env python3
"""Daily performance report CLI.

Prints (and optionally saves) the daily P&L summary for Telegram notification.

Usage:
    python -m stock_swing.cli.daily_report
    python -m stock_swing.cli.daily_report --json
    python -m stock_swing.cli.daily_report --save
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root / "src"))


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(project_root / ".env")

from stock_swing.core.runtime import read_runtime_mode
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.pnl_tracker import PnLTracker


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily P&L report")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--save", action="store_true", help="Save report to data/audits/")
    args = parser.parse_args()

    tracker = PnLTracker(project_root)
    summary = tracker.get_summary()
    open_pos = tracker.get_open_positions()
    recent = tracker.get_recent_trades(5)

    # Fetch live account equity from broker
    equity = 100_000.0
    buying_power = 100_000.0
    account_status = "UNKNOWN"
    try:
        broker = BrokerClient(
            api_key=os.environ["BROKER_API_KEY"],
            api_secret=os.environ["BROKER_API_SECRET"],
            paper_mode=True,
            base_url=os.environ["BROKER_BASE_URL"],
        )
        acct = broker.fetch_account().payload
        equity = float(acct.get("equity", equity))
        buying_power = float(acct.get("buying_power", buying_power))
        account_status = acct.get("status", "UNKNOWN")

        # Fetch current prices for open positions
        current_prices: dict[str, float] = {}
        for pos in open_pos:
            sym = pos["symbol"]
            try:
                q = broker.fetch_latest_quote(sym).payload
                quote = q.get("quote", q)
                bid = quote.get("bp", 0) or 0
                ask = quote.get("ap", 0) or 0
                if bid and ask:
                    current_prices[sym] = round((bid + ask) / 2, 4)
            except Exception:
                pass

        # Record daily snapshot
        today_audit = project_root / "data" / "audits"
        today_audit.mkdir(parents=True, exist_ok=True)
        snap = tracker.record_daily_snapshot(
            equity=equity,
            current_prices=current_prices,
        )
    except Exception as exc:
        snap = None
        current_prices = {}
        print(f"[WARN] Broker fetch failed: {exc}", file=sys.stderr)

    today = datetime.now(timezone.utc).date().isoformat()
    runtime_mode = "?"
    try:
        runtime_mode = read_runtime_mode(project_root)
    except Exception:
        pass

    if args.json:
        out = {
            "report_date": today,
            "runtime_mode": runtime_mode,
            "account": {
                "status": account_status,
                "equity": equity,
                "buying_power": buying_power,
            },
            "performance": summary,
            "open_positions": open_pos,
            "recent_trades": recent,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    # Human-readable report (Telegram-friendly)
    lines = _build_report(
        today=today,
        runtime_mode=runtime_mode,
        account_status=account_status,
        equity=equity,
        buying_power=buying_power,
        summary=summary,
        open_pos=open_pos,
        recent=recent,
        current_prices=current_prices,
    )
    report_text = "\n".join(lines)
    print(report_text)

    if args.save:
        report_path = project_root / "data" / "audits" / f"daily_report_{today}.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
        print(f"\nSaved: {report_path}")

    return 0


def _build_report(
    today: str,
    runtime_mode: str,
    account_status: str,
    equity: float,
    buying_power: float,
    summary: dict,
    open_pos: list,
    recent: list,
    current_prices: dict,
) -> list[str]:
    lines = []
    lines.append("📈 stock_swing Daily Report")
    lines.append(f"🗓  {today}  |  mode: {runtime_mode}")
    lines.append("")

    # Account
    lines.append("💰 Account (Paper)")
    lines.append(f"  Status      : {account_status}")
    lines.append(f"  Equity      : ${equity:>12,.2f}")
    lines.append(f"  Buying power: ${buying_power:>12,.2f}")
    lines.append(f"  Cumul. P&L  : ${summary['cumulative_realized_pnl']:>+12,.2f}")
    lines.append("")

    # Performance
    lines.append("📊 Performance (since start)")
    lines.append(f"  Closed trades : {summary['closed_trades']}")
    lines.append(f"  Win / Loss    : {summary['winning_trades']} / {summary['losing_trades']}")
    wr = summary['win_rate']
    lines.append(f"  Win rate      : {wr:.1%}" + (" 🔥" if wr >= 0.6 else (" ⚠️" if wr < 0.4 else "")))
    lines.append(f"  Avg return    : {summary['avg_return_per_trade']:>+.2%}")
    lines.append(f"  Avg P&L/trade : ${summary['avg_pnl_per_trade']:>+,.2f}")
    lines.append(f"  Max drawdown  : {summary['max_drawdown_pct']:.2%}")
    lines.append(f"  Trading days  : {summary['trading_days']}")
    lines.append("")

    # Open positions
    if open_pos:
        lines.append(f"📂 Open Positions ({len(open_pos)})")
        for pos in open_pos:
            sym = pos["symbol"]
            entry = pos["entry_price"]
            qty = pos["qty"]
            curr = current_prices.get(sym)
            if curr:
                unreal = (curr - entry) * qty
                unreal_pct = (curr - entry) / entry
                lines.append(
                    f"  {sym:<6} {qty:>4}sh  entry=${entry:,.2f}"
                    f"  now=${curr:,.2f}"
                    f"  unreal={unreal_pct:>+.1%} (${unreal:>+,.0f})"
                )
            else:
                lines.append(f"  {sym:<6} {qty:>4}sh  entry=${entry:,.2f}")
        lines.append("")
    else:
        lines.append("📂 Open Positions: (none)")
        lines.append("")

    # Recent trades
    if recent:
        lines.append(f"🔄 Recent Closed Trades (last {len(recent)})")
        for t in reversed(recent):
            pnl = t.get("pnl") or 0
            ret = t.get("return_pct") or 0
            icon = "✅" if pnl >= 0 else "❌"
            lines.append(
                f"  {icon} {t['symbol']:<6} {t['side'].upper()}"
                f"  P&L: ${pnl:>+,.2f} ({ret:>+.1%})"
                f"  [{t['strategy_id']}]"
            )
        lines.append("")
    else:
        lines.append("🔄 No closed trades yet")
        lines.append("")

    lines.append("─" * 40)
    lines.append(f"Next run: JST 22:30 (US pre-market)")
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
