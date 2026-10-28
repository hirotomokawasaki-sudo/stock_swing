#!/usr/bin/env python3
"""Paper demo wrapper with error handling and Telegram notifications.

This wrapper runs the paper demo and sends Telegram notifications on both
success and failure cases.
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
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


def send_error_notification(error_type: str, error_msg: str, traceback_str: str = "") -> None:
    """Send error notification to Telegram."""
    try:
        from stock_swing.utils.telegram_notifier import send_notification
        
        jst = timezone(timedelta(hours=9))
        jst_time = datetime.now(timezone.utc).astimezone(jst).strftime('%Y-%m-%d %H:%M JST')
        
        # Truncate long error messages
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."
        
        # Truncate traceback
        if traceback_str and len(traceback_str) > 300:
            lines = traceback_str.split('\n')
            # Keep first 2 and last 5 lines
            if len(lines) > 10:
                traceback_str = '\n'.join(lines[:2] + ['...'] + lines[-5:])
        
        message = f"""<b>🚨 Paper Demo エラー</b>
🗓 {jst_time}

<b>エラー種別:</b>
<code>{error_type}</code>

<b>エラー内容:</b>
<code>{error_msg}</code>"""
        
        if traceback_str:
            message += f"""

<b>トレースバック:</b>
<code>{traceback_str}</code>"""
        
        message += """

<b>対応:</b>
• ログを確認してください
• 必要に応じて手動で実行
• システム管理者に連絡"""
        
        send_notification(message)
    except Exception as e:
        print(f"[ERROR] Failed to send error notification: {e}", file=sys.stderr)


def send_timeout_notification(elapsed_seconds: int) -> None:
    """Send timeout notification to Telegram."""
    try:
        from stock_swing.utils.telegram_notifier import send_notification
        
        jst = timezone(timedelta(hours=9))
        jst_time = datetime.now(timezone.utc).astimezone(jst).strftime('%Y-%m-%d %H:%M JST')
        
        message = f"""<b>⏱️ Paper Demo タイムアウト</b>
🗓 {jst_time}

<b>実行時間:</b>
<code>{elapsed_seconds}秒で停止</code>

<b>考えられる原因:</b>
• API応答の遅延
• ネットワーク問題
• データ取得の失敗

<b>対応:</b>
• 手動で再実行を試みる
• API接続を確認
• ログファイルを確認"""
        
        send_notification(message)
    except Exception as e:
        print(f"[ERROR] Failed to send timeout notification: {e}", file=sys.stderr)


def main() -> int:
    """Run paper demo with error handling."""
    import sys
    from datetime import datetime
    
    start_time = datetime.now()
    
    # Build command
    cmd = [
        sys.executable,
        "-m",
        "stock_swing.cli.paper_demo",
        "--allow-outside-hours",
        "--telegram",
    ]
    
    # Add any additional arguments passed to this wrapper
    if len(sys.argv) > 1:
        cmd.extend(sys.argv[1:])
    
    print(f"[INFO] Running: {' '.join(cmd)}")
    print(f"[INFO] Start time: {start_time}")
    
    try:
        # Run the paper demo
        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=900,  # 15 minutes
        )
        
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"[INFO] Completed in {elapsed:.1f} seconds")
        print(f"[INFO] Exit code: {result.returncode}")
        
        # Print output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        
        # Check for errors
        if result.returncode != 0:
            # Extract error from stderr or stdout
            error_msg = result.stderr.strip() if result.stderr else result.stdout.strip()
            if not error_msg:
                error_msg = f"プロセスが終了コード {result.returncode} で終了しました"
            
            # Determine error type
            if "Kill switch" in error_msg or "kill_switch" in error_msg.lower():
                error_type = "キルスイッチ発動"
            elif "Broker" in error_msg or "API" in error_msg:
                error_type = "ブローカーAPI エラー"
            elif "Market" in error_msg or "market" in error_msg.lower():
                error_type = "マーケット関連エラー"
            elif "Runtime" in error_msg or "mode" in error_msg.lower():
                error_type = "ランタイムモード エラー"
            else:
                error_type = "実行エラー"
            
            send_error_notification(
                error_type=error_type,
                error_msg=error_msg,
                traceback_str="",
            )
            
            return result.returncode
        
        return 0
        
    except subprocess.TimeoutExpired:
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"[ERROR] Process timed out after {elapsed:.1f} seconds", file=sys.stderr)
        send_timeout_notification(int(elapsed))
        return 124  # Standard timeout exit code
        
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"[ERROR] Unexpected error after {elapsed:.1f} seconds: {e}", file=sys.stderr)
        
        tb = traceback.format_exc()
        send_error_notification(
            error_type="予期しないエラー",
            error_msg=str(e),
            traceback_str=tb,
        )
        
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
