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
from typing import Any


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


def _load_circuit_breaker(root: Path) -> dict:
    """サーキットブレーカーの現在状態を読み込む。"""
    cb_path = root / "data" / "guardrails" / "circuit_breaker.json"
    if not cb_path.exists():
        return {"status": "unknown"}
    try:
        return json.loads(cb_path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "unknown"}


def _load_console_summary(root: Path) -> dict:
    """最新コンソールサマリーを読み込む（存在しなければ空 dict）。"""
    path = root / "reports" / "console" / "latest_console_summary.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _exit_attribution_from_tracker(root: Path) -> dict[str, dict]:
    """PnL state から決済理由別実績を集計する。"""
    state_path = root / "data" / "tracking" / "pnl_state.json"
    if not state_path.exists():
        return {}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    from collections import defaultdict
    by_reason: dict[str, list[float]] = defaultdict(list)
    for t in state.get("trades", []):
        if t.get("status") != "closed":
            continue
        reason = t.get("exit_reason") or "不明"
        pnl = t.get("pnl") or 0.0
        by_reason[reason].append(float(pnl))

    result = {}
    for reason, pnls in by_reason.items():
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gp = sum(wins)
        gl = abs(sum(losses))
        pf: float | None = round(gp / gl, 2) if gl > 0 else (None if gp > 0 else 0.0)
        result[reason] = {
            "count": len(pnls),
            "net": sum(pnls),
            "pf": pf,
            "wr": len(wins) / len(pnls) if pnls else 0.0,
        }
    return result


def _milestone_text() -> str | None:
    """今週の重要マイルストーンを返す（該当なければ None）。"""
    jst = timezone(timedelta(hours=9))
    today = datetime.now(timezone.utc).astimezone(jst).date()
    gonogo_date = date(2026, 7, 31)
    diff = (gonogo_date - today).days
    if 0 <= diff <= 7:
        if diff == 0:
            return "🎯 本日: Go/No-Go 最終判定"
        return f"🎯 Go/No-Go 判定まであと {diff} 日  (07-31)"
    return None


def _build_report(
    today: str,
    runtime_mode: str,
    snapshot: Any,
    latest_sizing: list,
    account_summaries: dict | None = None,
    mode: str = "full",
) -> list[str]:
    jst = timezone(timedelta(hours=9))
    generated_at = datetime.now(timezone.utc).astimezone(jst).strftime("%Y-%m-%d %H:%M JST")

    cb = _load_circuit_breaker(project_root)
    cb_status = cb.get("status", "unknown")
    cs = _load_console_summary(project_root)

    lines: list[str] = []

    # ── HALT バナー（最優先）──────────────────────────────────────────
    if cb_status in ("halted", "recovery_pending"):
        triggered_at_raw = cb.get("triggered_at") or ""
        try:
            triggered_jst = (
                datetime.fromisoformat(triggered_at_raw.replace("Z", "+00:00"))
                .astimezone(jst)
                .strftime("%m/%d %H:%M JST")
            )
        except Exception:
            triggered_jst = triggered_at_raw[:16]

        rules = cb.get("triggered_rules") or []
        rule_text = "、".join(r.get("name", "?") for r in rules[:3]) if rules else "不明"

        lines.append("🚨━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━🚨")
        if cb_status == "halted":
            lines.append("⛔ サーキットブレーカー 発動中")
            lines.append("  ⚠️ 全トレード 一時停止")
        else:
            lines.append("⚠️ サーキットブレーカー 解除待ち (recovery_pending)")
            lines.append("  手動承認が必要です")
        lines.append(f"  発動時刻 : {triggered_jst}")
        lines.append(f"  発動原因 : {rule_text}")
        lines.append("🚨━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━🚨")
        lines.append("")

    # ── ヘッダー ─────────────────────────────────────────────────────
    lines.append("📈 stock_swing 日次レポート")
    lines.append(f"🗓 {today}  |  モード: {_format_runtime_mode(runtime_mode)}")
    lines.append(f"🕒 集計: {generated_at}")
    lines.append("")

    # ── システム状態 ──────────────────────────────────────────────────
    ledger_status = (cs.get("health") or {}).get("ledger_gate_status", "不明")
    ledger_icon = "✅" if ledger_status == "VALID" else ("❌" if ledger_status == "INVALID" else "❓")
    cb_icon = "✅ 正常" if cb_status == "ok" else (
        "⛔ 停止中" if cb_status == "halted" else
        "⚠️ 解除待ち" if cb_status == "recovery_pending" else f"❓ {cb_status}"
    )

    lines.append("🛡 システム状態")
    lines.append(f"  サーキットブレーカー: {cb_icon}")
    lines.append(f"  台帳品質            : {ledger_icon} {ledger_status}")

    # アラートがあれば追加
    alerts = snapshot.alerts or []
    if alerts:
        lines.append("")
        lines.append("⚠️ アラート")
        for alert in alerts:
            lines.append(f"  • {alert.get('message', '')}")
    lines.append("")

    # ── 資産状況 ─────────────────────────────────────────────────────
    baseline = 1_000_000.0
    equity = snapshot.equity or 0.0
    baseline_ret = (equity - baseline) / baseline if baseline else 0.0
    ret_icon = "🔥" if baseline_ret >= 0.05 else ("✅" if baseline_ret >= 0 else ("⚠️" if baseline_ret >= -0.05 else "❌"))

    lines.append(f"💰 資産状況  {ret_icon} 元本比 {baseline_ret:+.2%}")
    lines.append(f"  資産総額  : ${equity:>12,.2f}")
    lines.append(f"  確定損益  : ${snapshot.cumulative_realized_pnl:>+12,.2f}")
    lines.append(f"  含み損益  : ${snapshot.unrealized_pnl:>+12,.2f}")
    lines.append(f"  合計損益  : ${snapshot.total_pnl:>+12,.2f}")
    lines.append("")

    # ── パフォーマンス ────────────────────────────────────────────────
    wr = snapshot.win_rate or 0.0
    wr_icon = "🔥" if wr >= 0.6 else ("⚠️" if wr < 0.4 else "")
    lines.append("📊 パフォーマンス (全期間)")
    lines.append(f"  決済件数  : {snapshot.closed_trades}件  勝/負: {snapshot.winning_trades}/{snapshot.losing_trades}")
    lines.append(f"  勝率      : {wr:.1%} {wr_icon}  平均損益: ${snapshot.avg_pnl_per_trade:>+,.0f}/件")
    if mode == "full":
        avg_ret = snapshot.avg_return_per_trade
        lines.append(f"  平均騰落率: {avg_ret:>+.2%}" if avg_ret is not None else "  平均騰落率: 取得不可")
        lines.append(f"  最大DD    : {snapshot.max_drawdown_pct:.2%}  取引日数: {snapshot.trading_days}日")
    lines.append("")

    # ── 決済理由別実績（full のみ）────────────────────────────────────
    if mode == "full":
        attribution = _exit_attribution_from_tracker(project_root)
        if attribution:
            _REASON_JA = {
                "trailing_stop":  "利確(追跡)",
                "breakeven_stop": "利確(BEP)",
                "stop_loss":      "損切り",
                "time_based":     "期間満了",
                "broker_fill":    "手動/不明",
                "corporate_action": "コーポレート",
            }
            lines.append("📋 決済理由別実績")
            # 並び順: net_pnl 降順
            for reason, m in sorted(attribution.items(), key=lambda x: x[1]["net"], reverse=True):
                if m["count"] == 0:
                    continue
                ja = _REASON_JA.get(reason, reason)
                pf_str = f"PF={m['pf']:.2f}" if m["pf"] is not None else "PF=∞"
                net_str = f"${m['net']:>+,.0f}"
                icon = "✅" if m["net"] > 0 else "❌"
                # stop_loss には正しい止損率を別途表示
                if reason == "stop_loss":
                    lines.append(f"  {icon} {ja:<10} {m['count']:>3}件  {net_str}  ※正しい止損率=89.6%")
                else:
                    lines.append(f"  {icon} {ja:<10} {m['count']:>3}件  {pf_str}  {net_str}")
            lines.append("")

    # ── 保有ポジション ────────────────────────────────────────────────
    open_pos = snapshot.open_positions or []
    if open_pos:
        lines.append(f"📂 保有ポジション ({len(open_pos)}件)")
        if mode == "brief":
            symbols = [p.get("symbol", "?") for p in open_pos]
            lines.append(f"  {', '.join(symbols)}")
        else:
            for pos in open_pos:
                sym = pos.get("symbol", "?")
                entry = float(pos.get("entry_price") or pos.get("avg_entry_price") or 0.0)
                qty = pos.get("qty") or 0
                curr = pos.get("current_price") or (snapshot.current_prices or {}).get(sym)
                unreal = pos.get("unrealized_pnl")
                unreal_pct = pos.get("unrealized_pnl_pct")
                if curr:
                    curr = float(curr)
                    qty_val = float(qty)
                    if unreal is None:
                        unreal = (curr - entry) * qty_val
                    if unreal_pct is None and entry:
                        unreal_pct = (curr - entry) / entry
                    pct_val = float(unreal_pct or 0.0)
                    pct_icon = "📈" if pct_val > 0.01 else ("📉" if pct_val < -0.05 else "")
                    lines.append(
                        f"  {sym:<6} {qty:>4}株  取得=${entry:,.2f}→現在=${curr:,.2f}"
                        f"  {pct_val:>+.1%} (${float(unreal or 0):>+,.0f}) {pct_icon}"
                    )
                else:
                    lines.append(f"  {sym:<6} {qty:>4}株  取得=${entry:,.2f}")
        lines.append("")
    else:
        lines.append("📂 保有ポジション: なし")
        lines.append("")

    # ── 直近の決済取引 ────────────────────────────────────────────────
    recent = snapshot.recent_trades or []
    if recent:
        display_count = 3 if mode == "brief" else 5
        lines.append(f"🔄 直近の決済 ({display_count}件)")
        for t in list(reversed(recent))[:display_count]:
            pnl = t.get("pnl") or 0
            ret = t.get("return_pct") or 0
            icon = "✅" if pnl >= 0 else "❌"
            sym = t.get("symbol") or "?"
            reason = t.get("exit_reason") or "不明"
            reason_ja = {
                "trailing_stop": "利確(追跡)",
                "breakeven_stop": "利確(BEP)",
                "stop_loss": "損切り",
                "time_based": "期間満了",
                "broker_fill": "手動",
                "corporate_action": "コーポレート",
            }.get(reason, reason)
            lines.append(
                f"  {icon} {sym:<6}  {reason_ja:<9}  ${pnl:>+,.0f}  ({float(ret)*100 if abs(float(ret)) < 1 else float(ret):>+.1f}%)"
            )
        lines.append("")
    else:
        lines.append("🔄 決済取引なし")
        lines.append("")

    # ── 止損状況（止損健全性）────────────────────────────────────────
    slh = cs.get("stop_loss_health") or {}
    recent_30d = slh.get("recent_30d") or {}
    suppression = slh.get("suppression") or {}
    pec = slh.get("post_exit_check") or {}
    tiered_on = slh.get("tiered_min_hold_enabled", False)

    if recent_30d or tiered_on:
        lines.append("🔒 止損状況")
        lines.append(f"  段階的 min_hold: {'✅ 有効' if tiered_on else '— 無効'}")
        if recent_30d:
            cnt = recent_30d.get("count", 0)
            net = recent_30d.get("net_pnl", 0)
            lines.append(f"  30日止損実績   : {cnt}件  合計 ${net:>+,.0f}")
        sup_total = suppression.get("total", 0)
        if sup_total:
            lines.append(f"  今回run 抑制数 : {sup_total}件 (ノイズ止損を保留)")
        checked = pec.get("checked", 0)
        if checked:
            rate = pec.get("correct_rate", 0)
            rate_icon = "✅" if rate >= 0.70 else ("⚠️" if rate >= 0.50 else "❌")
            lines.append(f"  正しい止損率   : {rate * 100:.0f}% {rate_icon}  (目標≥70%)")
        lines.append("")

    # ── マイルストーン ────────────────────────────────────────────────
    milestone = _milestone_text()
    if milestone:
        lines.append(f"📅 {milestone}")
        lines.append("")

    # ── フッター ─────────────────────────────────────────────────────
    lines.append("─" * 36)
    lines.append(_next_report_schedule_text())
    return lines


def _format_for_telegram(lines: list[str]) -> str:
    """プレーンテキストを Telegram HTML フォーマットに変換する。

    - セクションヘッダー（絵文字付き行）→ 太字
    - インデント行 → 等幅コード
    - HALT バナー行 → そのまま（絵文字が目立つ）
    - 区切り線 → 省略
    """
    # Telegram のメッセージ上限は 4096 文字
    MAX_LEN = 4000
    HEADER_EMOJIS = {"📈","💰","📊","📂","🔄","🔒","🛡","📋","📅","⚠️","🚨","⛔"}

    html_lines = []
    for line in lines:
        if line.startswith("─"):
            continue
        first_char = line[:2] if len(line) >= 2 else line
        if any(e in first_char for e in HEADER_EMOJIS) or any(e in line[:3] for e in HEADER_EMOJIS):
            html_lines.append(f"<b>{line}</b>")
        elif line.startswith("  "):
            # HTML エスケープ
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_lines.append(f"<code>{safe}</code>")
        else:
            html_lines.append(line)

    result = "\n".join(html_lines)
    if len(result) > MAX_LEN:
        result = result[:MAX_LEN] + "\n…(省略)"
    return result


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
