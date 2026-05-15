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
from datetime import datetime, timedelta, timezone
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


def _format_runtime_mode(runtime_mode: str) -> str:
    mapping = {
        "paper": "ペーパー",
        "live": "ライブ",
        "backtest": "バックテスト",
    }
    return mapping.get(str(runtime_mode or "").strip().lower(), runtime_mode or "不明")


def _load_broker_snapshot(tracker_open_positions: list[dict]) -> dict[str, object]:
    equity = 100_000.0
    buying_power = 100_000.0
    account_status = "UNKNOWN"
    current_prices: dict[str, float] = {}
    open_positions: list[dict] = [dict(pos) for pos in tracker_open_positions]
    unrealized_pnl = 0.0
    positions_source = "tracker"

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

    broker_positions = broker.fetch_positions().payload
    normalized_positions: list[dict] = []
    for pos in broker_positions or []:
        symbol = str(pos.get("symbol") or "").strip()
        if not symbol:
            continue
        qty = float(pos.get("qty") or 0.0)
        entry_price = float(pos.get("avg_entry_price") or 0.0)
        current_price = float(pos.get("current_price") or 0.0)
        position_unrealized = float(pos.get("unrealized_pl") or 0.0)
        current_prices[symbol] = current_price
        unrealized_pnl += position_unrealized
        normalized_positions.append(
            {
                "symbol": symbol,
                "qty": int(qty) if qty.is_integer() else qty,
                "entry_price": entry_price,
                "current_price": current_price,
                "unrealized_pnl": position_unrealized,
                "unrealized_pnl_pct": float(pos.get("unrealized_plpc") or 0.0),
                "side": pos.get("side") or "long",
                "market_value": float(pos.get("market_value") or 0.0),
                "cost_basis": float(pos.get("cost_basis") or 0.0),
            }
        )

    if normalized_positions:
        open_positions = normalized_positions
        positions_source = "broker"
    else:
        for pos in open_positions:
            sym = pos.get("symbol")
            if not sym:
                continue
            try:
                q = broker.fetch_latest_quote(sym).payload
                quote = q.get("quote", q)
                bid = quote.get("bp", 0) or 0
                ask = quote.get("ap", 0) or 0
                if bid and ask:
                    current_prices[sym] = round((bid + ask) / 2, 4)
            except Exception:
                pass

    return {
        "equity": equity,
        "buying_power": buying_power,
        "account_status": account_status,
        "current_prices": current_prices,
        "open_positions": open_positions,
        "unrealized_pnl": round(unrealized_pnl, 2),
        "positions_source": positions_source,
    }


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
    open_pos = tracker.get_open_positions()

    # Fetch live account equity from broker
    equity = 100_000.0
    buying_power = 100_000.0
    account_status = "UNKNOWN"
    unrealized_pnl = 0.0
    positions_source = "tracker"
    try:
        broker_snapshot = _load_broker_snapshot(open_pos)
        equity = float(broker_snapshot["equity"])
        buying_power = float(broker_snapshot["buying_power"])
        account_status = str(broker_snapshot["account_status"])
        current_prices = dict(broker_snapshot["current_prices"])
        open_pos = list(broker_snapshot["open_positions"])
        unrealized_pnl = float(broker_snapshot["unrealized_pnl"])
        positions_source = str(broker_snapshot["positions_source"])

        # Record daily snapshot
        today_audit = project_root / "data" / "audits"
        today_audit.mkdir(parents=True, exist_ok=True)
        tracker.record_daily_snapshot(
            equity=equity,
            current_prices=current_prices,
        )
    except Exception as exc:
        current_prices = {}
        print(f"[WARN] Broker fetch failed: {exc}", file=sys.stderr)

    tracker.state = tracker._load_state()
    summary = tracker.get_summary()
    recent = tracker.get_recent_trades(5)

    # Account-specific summaries
    accounts = tracker.list_accounts()
    account_summaries = {acc: tracker.get_summary_by_account(acc) for acc in accounts}

    if positions_source != "broker":
        unrealized_pnl = round(
            sum(
                ((float(current_prices.get(pos.get("symbol"), 0.0)) - float(pos.get("entry_price") or 0.0)) * float(pos.get("qty") or 0.0))
                for pos in open_pos
                if pos.get("symbol") in current_prices and float(pos.get("entry_price") or 0.0) > 0
            ),
            2,
        )

    total_pnl = round(float(summary.get("cumulative_realized_pnl") or 0.0) + unrealized_pnl, 2)

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
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": total_pnl,
            "positions_source": positions_source,
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
        unrealized_pnl=unrealized_pnl,
        total_pnl=total_pnl,
        open_pos=open_pos,
        recent=recent,
        current_prices=current_prices,
        latest_sizing=latest_sizing,
        account_summaries=account_summaries,
        positions_source=positions_source,
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
    unrealized_pnl: float,
    total_pnl: float,
    open_pos: list,
    recent: list,
    current_prices: dict,
    latest_sizing: list,
    account_summaries: dict | None = None,
    positions_source: str = "tracker",
) -> list[str]:
    lines = []
    lines.append("📈 stock_swing 日次レポート")
    lines.append(f"🗓  {today}  |  モード: {_format_runtime_mode(runtime_mode)}")
    lines.append("")

    # Account
    lines.append("💰 口座情報 (ペーパー)")
    lines.append(f"  ステータス    : {account_status}")
    lines.append(f"  資産総額      : ${equity:>12,.2f}")
    lines.append(f"  買付余力      : ${buying_power:>12,.2f}")
    lines.append(f"  確定損益(累積): ${summary['cumulative_realized_pnl']:>+12,.2f}")
    lines.append(f"  含み損益(現在): ${unrealized_pnl:>+12,.2f}")
    lines.append(f"  合計損益(現在): ${total_pnl:>+12,.2f}")
    lines.append("")

    # Performance
    lines.append("📊 パフォーマンス (運用開始以降)")
    lines.append(f"  決済取引数    : {summary['closed_trades']}")
    lines.append(f"  勝 / 負       : {summary['winning_trades']} / {summary['losing_trades']}")
    wr = summary['win_rate']
    lines.append(f"  勝率          : {wr:.1%}" + (" 🔥" if wr >= 0.6 else (" ⚠️" if wr < 0.4 else "")))
    avg_return = summary.get('avg_return_per_trade')
    lines.append(f"  平均リターン  : {avg_return:>+.2%}" if avg_return is not None else "  平均リターン  : 取得不可")
    lines.append(f"  平均損益/取引 : ${summary['avg_pnl_per_trade']:>+,.2f}")
    lines.append(f"  最大DD        : {summary['max_drawdown_pct']:.2%}")
    lines.append(f"  取引日数      : {summary['trading_days']}")
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
    if open_pos:
        source_label = "ブローカー" if positions_source == "broker" else "トラッカー"
        lines.append(f"📂 保有ポジション ({len(open_pos)}件 / ソース: {source_label})")
        for pos in open_pos:
            sym = pos["symbol"]
            entry = float(pos.get("entry_price") or pos.get("avg_entry_price") or 0.0)
            qty = pos.get("qty")
            curr = pos.get("current_price") or current_prices.get(sym)
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
    if recent:
        lines.append(f"🔄 最近の決済取引 (直近{len(recent)}件)")
        for t in reversed(recent):
            pnl = t.get("pnl") or 0
            ret = t.get("return_pct") or 0
            icon = "✅" if pnl >= 0 else "❌"
            side = str(t.get("side") or t.get("entry_side") or "BUY").upper()
            side_ja = "買い" if side == "BUY" else "売り"
            symbol = t.get("symbol") or "?"
            strategy_id = t.get("strategy_id") or t.get("strategy") or "unknown"
            lines.append(
                f"  {icon} {symbol:<6} {side_ja}"
                f"  損益: ${pnl:>+,.2f} ({ret:>+.1%})"
                f"  [{strategy_id}]"
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
