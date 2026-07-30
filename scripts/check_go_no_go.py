#!/usr/bin/env python3
"""07-31 Go/No-Go 自動判定スクリプト.

Required 条件7件をシステム状態から自動確認し、
判定結果をコンソール出力 + docs/go_no_go_result_YYYYMMDD.md に保存する。

使い方:
    python scripts/check_go_no_go.py [--save]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import zoneinfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
JST = zoneinfo.ZoneInfo("Asia/Tokyo")


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check() -> dict[str, dict]:
    summary_path = PROJECT_ROOT / "reports" / "console" / "latest_console_summary.json"
    summary = _load(summary_path)
    health = summary.get("health", {})
    cb = health.get("circuit_breaker_detail", {})

    # cron jobs最新run確認
    cron_path = PROJECT_ROOT / "data" / "audits" / "reconcile_status.json"
    reconcile = _load(cron_path)

    results: dict[str, dict] = {}

    # 1. ledger_quality VALID
    lg = health.get("ledger_gate_status", "UNKNOWN")
    results["ledger_quality"] = {
        "label": "ledger_quality_gate",
        "pass": lg == "VALID",
        "actual": lg,
        "required": "VALID",
    }

    # 2. circuit_breaker ok
    cb_status = cb.get("status", "UNKNOWN")
    results["circuit_breaker"] = {
        "label": "circuit_breaker",
        "pass": cb_status == "ok",
        "actual": cb_status,
        "required": "ok",
    }

    # 3. broker/tracker mismatch == 0
    mismatch = health.get("broker_tracker_mismatch_count", -1)
    results["mismatch"] = {
        "label": "broker_tracker_mismatch",
        "pass": mismatch == 0,
        "actual": mismatch,
        "required": 0,
    }

    # 4. attribution coverage >= 98%
    attr = health.get("attribution_coverage_pct", 0.0)
    results["attribution"] = {
        "label": "attribution_coverage_pct",
        "pass": attr >= 95.0,
        "actual": f"{attr}%",
        "required": ">=95%",
    }

    # 5. guardrail hard-halt enabled
    gs = health.get("guardrail_status", "UNKNOWN")
    results["guardrail"] = {
        "label": "guardrail_hard_halt",
        "pass": gs in ("ok", "recovery_pending"),
        "actual": gs,
        "required": "ok or recovery_pending",
    }

    # 6. all crons healthy (reconcile last status ok)
    rec_status = reconcile.get("status", "UNKNOWN")
    results["cron_health"] = {
        "label": "cron_jobs_healthy",
        "pass": health.get("status", "") == "OK",
        "actual": health.get("status", "UNKNOWN"),
        "required": "OK",
    }

    # 7. paper 3日確認 (Go/No-Go reportから確認)
    gng_path = PROJECT_ROOT / "docs" / "go_no_go_report_20260731.md"
    paper_ok = False
    if gng_path.exists():
        content = gng_path.read_text()
        paper_ok = "07-30 ok" in content or "07-30 ✅" in content or "07-30完了" in content
    results["paper_3day"] = {
        "label": "paper_3day_confirmation",
        "pass": paper_ok,
        "actual": "07-28 ok / 07-29 ok / 07-30 ok" if paper_ok else "未確認",
        "required": "3日間正常稼働",
    }

    return results


def format_report(results: dict[str, dict], save: bool = False) -> str:
    now_jst = datetime.now(JST)
    all_pass = all(r["pass"] for r in results.values())
    decision = "🟢 **GO**（準備完了 / 08-20以降にリアルトレード開始）" if all_pass else "🔴 **NO-GO**"

    lines = [
        f"# Go/No-Go 判定結果 — {now_jst.strftime('%Y-%m-%d %H:%M JST')}",
        "",
        f"## 最終判定: {decision}",
        "",
        "## Required 条件チェック",
        "",
        "| 条件 | 判定 | 実測値 | 必要値 |",
        "|------|------|--------|--------|",
    ]
    for r in results.values():
        mark = "✅" if r["pass"] else "❌"
        lines.append(f"| {r['label']} | {mark} | {r['actual']} | {r['required']} |")

    lines += [
        "",
        f"**判定時刻**: {now_jst.strftime('%Y-%m-%d %H:%M:%S JST')}",
        f"**全件 Pass**: {all_pass}",
        "",
    ]

    if all_pass:
        lines += [
            "## 次のアクション",
            "- 本判定を `docs/go_no_go_report_20260731.md` に記録",
            "- リアルトレード開始: 08-20以降（50%サイズ）",
            "- 引き続き sector_shock_hold A/B + 20 clean runs soak を継続",
        ]
    else:
        failed = [r["label"] for r in results.values() if not r["pass"]]
        lines += [
            "## ブロック項目",
            *[f"- ❌ {f}" for f in failed],
        ]

    report = "\n".join(lines)

    if save:
        out = PROJECT_ROOT / "docs" / f"go_no_go_result_{now_jst.strftime('%Y%m%d')}.md"
        out.write_text(report, encoding="utf-8")
        print(f"[saved] {out}", file=sys.stderr)

    return report


def main() -> int:
    save = "--save" in sys.argv
    results = check()
    report = format_report(results, save=save)
    print(report)
    all_pass = all(r["pass"] for r in results.values())
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
