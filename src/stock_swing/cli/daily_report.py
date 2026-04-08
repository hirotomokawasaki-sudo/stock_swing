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


def _load_latest_decision_sizing() -> list[dict]:
    decisions_dir = project_root / "data" / "decisions"
    if not decisions_dir.exists():
        return []
    items = []
    for p in sorted(decisions_dir.glob("decision_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            sizing = data.get("sizing") or ((data.get("evidence") or {}).get("sizing") if isinstance(data.get("evidence"), dict) else None)
            if sizing:
                items.append({
                    "symbol": data.get("symbol"),
                    "action": data.get("action"),
                    "sizing": sizing,
                })
        except Exception:
            pass
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily P&L report")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--save", action="store_true", help="Save report to data/audits/")
    parser.add_argument("--telegram", action="store_true", help="Send report to Telegram")
    parser.add_argument("--silent", action="store_true", help="Send Telegram notification silently")
    args = parser.parse_args()
    
    try:
        return _main_impl(args)
    except Exception as exc:
        # Send error notification
        if args.telegram:
            _send_error_notification(exc)
        raise


def _main_impl(args) -> int:

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

    latest_sizing = _load_latest_decision_sizing()

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
            "latest_sizing": latest_sizing,
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
        latest_sizing=latest_sizing,
    )
    report_text = "\n".join(lines)
    print(report_text)

    if args.save:
        report_path = project_root / "data" / "audits" / f"daily_report_{today}.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
        print(f"\nSaved: {report_path}")

    if args.telegram:
        from stock_swing.utils.telegram_notifier import send_notification
        # Convert to HTML format for Telegram
        telegram_text = _format_for_telegram(lines)
        success = send_notification(telegram_text, silent=args.silent)
        if success:
            print("\n✅ Sent to Telegram")
        else:
            print("\n⚠️  Telegram send failed")

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
    latest_sizing: list,
) -> list[str]:
    lines = []
    lines.append("📈 stock_swing 日次レポート")
    lines.append(f"🗓  {today}  |  モード: {runtime_mode}")
    lines.append("")

    # Account
    lines.append("💰 口座情報 (ペーパー)")
    lines.append(f"  ステータス    : {account_status}")
    lines.append(f"  資産総額      : ${equity:>12,.2f}")
    lines.append(f"  買付余力      : ${buying_power:>12,.2f}")
    lines.append(f"  累積損益      : ${summary['cumulative_realized_pnl']:>+12,.2f}")
    lines.append("")

    # Performance
    lines.append("📊 パフォーマンス (運用開始以降)")
    lines.append(f"  決済取引数    : {summary['closed_trades']}")
    lines.append(f"  勝 / 負       : {summary['winning_trades']} / {summary['losing_trades']}")
    wr = summary['win_rate']
    lines.append(f"  勝率          : {wr:.1%}" + (" 🔥" if wr >= 0.6 else (" ⚠️" if wr < 0.4 else "")))
    lines.append(f"  平均リターン  : {summary['avg_return_per_trade']:>+.2%}")
    lines.append(f"  平均損益/取引 : ${summary['avg_pnl_per_trade']:>+,.2f}")
    lines.append(f"  最大DD        : {summary['max_drawdown_pct']:.2%}")
    lines.append(f"  取引日数      : {summary['trading_days']}")
    lines.append("")

    # Open positions
    if open_pos:
        lines.append(f"📂 保有ポジション ({len(open_pos)}件)")
        for pos in open_pos:
            sym = pos["symbol"]
            entry = pos["entry_price"]
            qty = pos["qty"]
            curr = current_prices.get(sym)
            if curr:
                unreal = (curr - entry) * qty
                unreal_pct = (curr - entry) / entry
                lines.append(
                    f"  {sym:<6} {qty:>4}株  取得=${entry:,.2f}"
                    f"  現在=${curr:,.2f}"
                    f"  含損益={unreal_pct:>+.1%} (${unreal:>+,.0f})"
                )
            else:
                lines.append(f"  {sym:<6} {qty:>4}株  取得=${entry:,.2f}")
        lines.append("")
    else:
        lines.append("📂 保有ポジション: なし")
        lines.append("")

    # Recent trades
    if recent:
        lines.append(f"🔄 最近の決済取引 (直近{len(recent)}件)")
        for t in reversed(recent):
            pnl = t.get("pnl") or 0
            ret = t.get("return_pct") or 0
            icon = "✅" if pnl >= 0 else "❌"
            side_ja = "買い" if t['side'].upper() == "BUY" else "売り"
            lines.append(
                f"  {icon} {t['symbol']:<6} {side_ja}"
                f"  損益: ${pnl:>+,.2f} ({ret:>+.1%})"
                f"  [{t['strategy_id']}]"
            )
        lines.append("")
    else:
        lines.append("🔄 決済取引なし")
        lines.append("")

    if latest_sizing:
        lines.append(f"📏 最新のポジションサイズ根拠 (直近{min(len(latest_sizing), 5)}件)")
        seen = set()
        count = 0
        for item in latest_sizing:
            sym = item.get("symbol")
            if not sym or sym in seen:
                continue
            seen.add(sym)
            sizing = item.get("sizing") or {}
            lines.append(
                f"  {sym:<6} 採用={sizing.get('final_shares')}株 "
                f"[risk={sizing.get('shares_by_risk')} / notional={sizing.get('shares_by_notional')} / exposure={sizing.get('shares_by_exposure')}]"
            )
            lines.append(
                f"         採用制約={sizing.get('applied_constraint') or '—'} 相場regime={sizing.get('regime_used') or '—'} 資産クラス={sizing.get('asset_class_used') or '—'} セクター={sizing.get('sector_used') or '—'} confidence={sizing.get('confidence') or '—'} "
                f"資産=${sizing.get('account_equity')} 株価=${sizing.get('current_price')} 最大許容損失=${sizing.get('max_loss_usd')} 最大投入額=${sizing.get('max_position_notional_usd')}"
            )
            count += 1
            if count >= 5:
                break
        lines.append("")

    lines.append("─" * 40)
    lines.append(f"次回実行: 日本時間 22:30 (米国プレマーケット)")
    return lines


def _format_for_telegram(lines: list[str]) -> str:
    """Convert plain text report to HTML-formatted Telegram message."""
    html_lines = []
    for line in lines:
        # Skip separator lines
        if line.startswith("─"):
            continue
        # Bold headers (lines with emoji)
        if any(emoji in line for emoji in ["📈", "💰", "📊", "📂", "🔄"]):
            html_lines.append(f"<b>{line}</b>")
        # Monospace for data lines (indented)
        elif line.startswith("  "):
            html_lines.append(f"<code>{line}</code>")
        else:
            html_lines.append(line)
    return "\n".join(html_lines)


def _send_error_notification(exc: Exception) -> None:
    """Send error notification to Telegram."""
    try:
        from stock_swing.utils.telegram_notifier import send_notification
        import traceback
        
        jst = timezone(timedelta(hours=9))
        jst_time = datetime.now(timezone.utc).astimezone(jst).strftime('%Y-%m-%d %H:%M JST')
        
        error_msg = str(exc)
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."
        
        # Get short traceback
        tb = traceback.format_exc()
        tb_lines = tb.split('\n')
        if len(tb_lines) > 8:
            tb_short = '\n'.join(tb_lines[:3] + ['...'] + tb_lines[-4:])
        else:
            tb_short = tb
        
        if len(tb_short) > 400:
            tb_short = tb_short[:400] + "..."
        
        message = f"""<b>🚨 Daily Report エラー</b>
🗓 {jst_time}

<b>エラー内容:</b>
<code>{error_msg}</code>

<b>トレースバック:</b>
<code>{tb_short}</code>

<b>対応:</b>
• ログを確認
• ブローカーAPI接続を確認
• 手動で再実行"""
        
        send_notification(message)
    except Exception as e:
        print(f"[ERROR] Failed to send error notification: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
