#!/usr/bin/env python3
"""Create today's stock_swing daily improvement log if it does not exist."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "docs" / "daily_logs"
TASK_FILE = PROJECT_ROOT / "docs" / "console_improvement_tasks.md"


def extract_today_first() -> list[str]:
    if not TASK_FILE.exists():
        return []
    lines = TASK_FILE.read_text(encoding="utf-8").splitlines()
    in_today = False
    tasks = []
    for line in lines:
        if line.strip() == "## Today First":
            in_today = True
            continue
        if in_today and line.startswith("## "):
            break
        if in_today and line.strip().startswith("- [ ]"):
            tasks.append(line.strip()[6:].strip())
    return tasks


def main() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{today}.md"
    if log_path.exists():
        print(log_path)
        return 0

    today_tasks = extract_today_first()
    tasks_block = "\n".join(f"- {t}" for t in today_tasks) if today_tasks else "- T?"

    content = f"""# stock_swing Daily Improvement Log

## Date
- {today}

## 今日着手したタスク
{tasks_block}

## 実施内容
- 

## 確認結果
- 

## ブロッカー
- なし / あり:

## 次アクション
- 

## 反映確認
- [ ] API
- [ ] UI
- [ ] tracker / broker truth
- [ ] logs / cron
"""
    log_path.write_text(content, encoding="utf-8")
    print(log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
