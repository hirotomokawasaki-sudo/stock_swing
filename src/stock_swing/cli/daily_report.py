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
from datetime import date, datetime, timedelta, timezone
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
from stock_swing.reporting.performance_snapshot import build_snapshot
from stock_swing.tracking.pnl_tracker import PnLTracker


def _format_runtime_mode(runtime_mode: str) -> str:
    mapping = {
        "paper": "ペーパー",
        "live": "ライブ",
        "backtest": "バックテスト",
    }
    return mapping.get(str(runtime_mode or "").strip().lower(), runtime_mode or "不明")


def _next_report_schedule_text(today_utc: date | None = None) -> str:
    today_utc = today_utc or datetime.now(timezone.utc).date()
    jst = timezone(timedelta(hours=9))
    today_jst = datetime.combine(today_utc, datetime.min.time(), tzinfo=timezone.utc).astimezone(jst).date()
    weekday = today_jst.weekday()

    if weekday <= 3:  # Mon-Thu JST -> next day 09:00 JST
        next_date = today_jst + timedelta(days=1)
    elif weekday == 4:  # Fri JST -> Saturday report for Friday US session
        next_date = today_jst + timedelta(days=1)
    elif weekday == 5:  # Sat JST -> next Tuesday 09:00 JST
        next_date = today_jst + timedelta(days=3)
    else:  # Sun JST -> next Tuesday 09:00 JST
        next_date = today_jst + timedelta(days=2)

    return f"次回レポート予定: {next_date.isoformat()} 09:00 JST"





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
    parser.add_argument("--mode", choices=["brief", "full"], default="full", help="Report mode: brief (morning summary) or full (detailed)")
    args = parser.parse_args()
    
    try:
        return _main_impl(args)
    except Exception as exc:
        # Send error notification
        if args.telegram:
            _send_error_notification(exc)
        raise


def _main_impl(args) -> int:

    # Build unified snapshot
    try:
        snapshot = build_snapshot(project_root)
    except Exception as exc:
        print(f"[ERROR] Failed to build performance snapshot: {exc}", file=sys.stderr)
        raise

    # Account-specific summaries
    tracker = PnLTracker(project_root)
    tracker.state = tracker._load_state()
    accounts = tracker.list_accounts()
    account_summaries = {acc: tracker.get_summary_by_account(acc) for acc in accounts}

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
                "status": snapshot.account_status,
                "equity": snapshot.equity,
                "buying_power": snapshot.buying_power,
            },
            "performance": {
                "cumulative_realized_pnl": snapshot.cumulative_realized_pnl,
                "closed_trades": snapshot.closed_trades,
                "winning_trades": snapshot.winning_trades,
                "losing_trades": snapshot.losing_trades,
                "win_rate": snapshot.win_rate,
                "avg_return_per_trade": snapshot.avg_return_per_trade,
                "avg_pnl_per_trade": snapshot.avg_pnl_per_trade,
                "max_drawdown_pct": snapshot.max_drawdown_pct,
                "trading_days": snapshot.trading_days,
            },
            "unrealized_pnl": snapshot.unrealized_pnl,
            "total_pnl": snapshot.total_pnl,
            "positions_source": snapshot.positions_source,
            "open_positions": snapshot.open_positions,
            "recent_trades": snapshot.recent_trades,
            "latest_sizing": latest_sizing,
            "alerts": snapshot.alerts,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    # Human-readable report (Telegram-friendly)
    lines = _build_report(
        today=today,
        runtime_mode=runtime_mode,
        snapshot=snapshot,
        latest_sizing=latest_sizing,
        account_summaries=account_summaries,
        mode=args.mode,
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
    snapshot: Any,
    latest_sizing: list,
    account_summaries: dict | None = None,
    mode: str = "full",
) -> list[str]:
    lines = []
    lines.append("📈 stock_swing 日次レポート")
    generated_at = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    lines.append(f"🗓  {today}  |  モード: {_format_runtime_mode(runtime_mode)}")
    lines.append(f"🕒  集計時刻: {generated_at}")
    lines.append("")

    # Account
    lines.append(f"💰 口座情報 ({_format_runtime_mode(runtime_mode)})")
    lines.append(f"  ステータス    : {snapshot.account_status}")
    lines.append(f"  資産総額      : ${snapshot.equity:>12,.2f}")
    lines.append(f"  買付余力      : ${snapshot.buying_power:>12,.2f}")
    lines.append(f"  確定損益(累積): ${snapshot.cumulative_realized_pnl:>+12,.2f}")
    lines.append(f"  含み損益(現在): ${snapshot.unrealized_pnl:>+12,.2f}")
    lines.append(f"  合計損益(現在): ${snapshot.total_pnl:>+12,.2f}")
    lines.append("")

    # Alerts
    if snapshot.alerts:
        lines.append("⚠️  アラート")
        for alert in snapshot.alerts:
            lines.append(f"  • {alert['message']}")
        lines.append("")

    # Performance
    lines.append("📊 パフォーマンス (運用開始以降)")
    if mode == "brief":
        lines.append(f"  決済取引数    : {snapshot.closed_trades}")
        wr = snapshot.win_rate
        lines.append(f"  勝率          : {wr:.1%}" + (" 🔥" if wr >= 0.6 else (" ⚠️" if wr < 0.4 else "")))
    else:
        lines.append(f"  決済取引数    : {snapshot.closed_trades}")
        lines.append(f"  勝 / 負       : {snapshot.winning_trades} / {snapshot.losing_trades}")
        wr = snapshot.win_rate
        lines.append(f"  勝率          : {wr:.1%}" + (" 🔥" if wr >= 0.6 else (" ⚠️" if wr < 0.4 else "")))
        avg_return = snapshot.avg_return_per_trade
        lines.append(f"  平均リターン  : {avg_return:>+.2%}" if avg_return is not None else "  平均リターン  : 取得不可")
        lines.append(f"  平均損益/取引 : ${snapshot.avg_pnl_per_trade:>+,.2f}")
        lines.append(f"  最大DD        : {snapshot.max_drawdown_pct:.2%}")
        lines.append(f"  取引日数      : {snapshot.trading_days}")
    lines.append("")
    
    # Account-specific summaries (if multiple accounts)
    if account_summaries and len(account_summaries) > 1:
        lines.append("🏦 口座別サマリー")
        for acc_id, acc_sum in account_summaries.items():
            acc_short = acc_id[:8] if len(acc_id) > 8 else acc_id
            lines.append(f"  [{acc_short}]")
            lines.append(f"    決済: {acc_sum['closed_trades']}件  勝率: {acc_sum['win_rate']:.1%}")
            lines.append(f"    累積損益: ${acc_sum['cumulative_realized_pnl']:>+,.2f}")
        lines.append("")

    # Open positions
    open_pos = snapshot.open_positions
    if open_pos:
        source_label = "ブローカー" if snapshot.positions_source == "broker" else "トラッカー"
        lines.append(f"📂 保有ポジション ({len(open_pos)}件 / ソース: {source_label})")
        if mode == "brief":
            # Brief mode: just list symbols
            symbols = [pos.get("symbol") or "?" for pos in open_pos]
            lines.append(f"  {', '.join(symbols)}")
        else:
            # Full mode: show details
            for pos in open_pos:
                sym = pos["symbol"]
                entry = float(pos.get("entry_price") or pos.get("avg_entry_price") or 0.0)
                qty = pos.get("qty")
                curr = pos.get("current_price") or snapshot.current_prices.get(sym)
                unreal = pos.get("unrealized_pnl")
                unreal_pct = pos.get("unrealized_pnl_pct")
                if curr:
                    curr = float(curr)
                    qty_val = float(qty or 0.0)
                    if unreal is None:
                        unreal = (curr - entry) * qty_val
                    if unreal_pct is None and entry:
                        unreal_pct = (curr - entry) / entry
                    lines.append(
                        f"  {sym:<6} {qty:>4}株  取得=${entry:,.2f}"
                        f"  現在=${curr:,.2f}"
                        f"  含損益={(float(unreal_pct) if unreal_pct is not None else 0.0):>+.1%} (${float(unreal):>+,.0f})"
                    )
                else:
                    lines.append(f"  {sym:<6} {qty:>4}株  取得=${entry:,.2f}")
        lines.append("")
    else:
        lines.append("📂 保有ポジション: なし")
        lines.append("")

    # Recent trades
    recent = snapshot.recent_trades
    if recent:
        display_count = 3 if mode == "brief" else len(recent)
        lines.append(f"🔄 最近の決済取引 (直近{display_count}件)")
        for t in list(reversed(recent))[:display_count]:
            pnl = t.get("pnl") or 0
            ret = t.get("return_pct") or 0
            icon = "✅" if pnl >= 0 else "❌"
            side = str(t.get("side") or t.get("entry_side") or "BUY").upper()
            side_ja = "買い" if side == "BUY" else "売り"
            symbol = t.get("symbol") or "?"
            strategy_id = t.get("strategy_id") or t.get("strategy") or "unknown"
            if mode == "brief":
                lines.append(f"  {icon} {symbol:<6}  ${pnl:>+,.2f} ({ret:>+.1%})")
            else:
                lines.append(
                    f"  {icon} {symbol:<6} {side_ja}"
                    f"  損益: ${pnl:>+,.2f} ({ret:>+.1%})"
                    f"  [{strategy_id}]"
                )
        lines.append("")
    else:
        lines.append("🔄 決済取引なし")
        lines.append("")

    if mode == "full" and latest_sizing:
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
    lines.append(_next_report_schedule_text())
    return lines


def _format_for_telegram(lines: list[str]) -> str:
    """Convert plain text report to HTML-formatted Telegram message."""
    html_lines = []
    for line in lines:
        # Skip separator lines
        if line.startswith("─"):
            continue
        # Bold headers (lines with emoji)
        if any(emoji in line for emoji in ["📈", "💰", "📊", "📂", "🔄", "📏", "⚠️"]):
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
        import socket
        
        jst = timezone(timedelta(hours=9))
        jst_time = datetime.now(timezone.utc).astimezone(jst).strftime('%Y-%m-%d %H:%M JST')
        
        error_msg = str(exc)
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."
        
        # Get exception type
        exc_type = type(exc).__name__
        
        # Get short traceback
        tb = traceback.format_exc()
        tb_lines = tb.split('\n')
        if len(tb_lines) > 8:
            tb_short = '\n'.join(tb_lines[:3] + ['...'] + tb_lines[-4:])
        else:
            tb_short = tb
        
        if len(tb_short) > 400:
            tb_short = tb_short[:400] + "..."
        
        # Network connectivity check
        connectivity = "OK"
        try:
            socket.create_connection(("api.telegram.org", 443), timeout=3)
        except Exception:
            connectivity = "NG (network issue detected)"
        
        message = f"""<b>🚨 Daily Report エラー</b>
🗓 {jst_time}
🌐 Network: {connectivity}

<b>エラー種別:</b> {exc_type}
<b>エラー内容:</b>
<code>{error_msg}</code>

<b>トレースバック:</b>
<code>{tb_short}</code>

<b>対応:</b>
• ログを確認
• ブローカーAPI接続を確認
• 手動で再実行: <code>cd ~/stock_swing && source venv/bin/activate && python -m stock_swing.cli.daily_report --telegram</code>"""
        
        # Try to send with retry logic
        success = send_notification(message)
        if not success:
            print(f"[ERROR] Failed to send error notification to Telegram after retries", file=sys.stderr)
            # Fall back to local log
            error_log = project_root / "logs" / f"daily_report_error_{jst_time.replace(' ', '_').replace(':', '')}.log"
            error_log.parent.mkdir(parents=True, exist_ok=True)
            error_log.write_text(f"{jst_time}\n{exc_type}: {error_msg}\n\n{tb}", encoding="utf-8")
            print(f"[INFO] Error logged to: {error_log}", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Failed to send error notification: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    raise SystemExit(main())
