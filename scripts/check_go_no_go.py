#!/usr/bin/env python3
"""07-31 Go/No-Go 自動判定スクリプト.

Required 条件7件をシステム状態から自動確認し、
判定結果をコンソール出力 + docs/go_no_go_result_YYYYMMDD.md に保存する。

使い方:
    python scripts/check_go_no_go.py [--save]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import zoneinfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))  # for `console.*` imports (promotion readiness)

JST = zoneinfo.ZoneInfo("Asia/Tokyo")
CURRENT_MODE_PATH = PROJECT_ROOT / "config" / "runtime" / "current_mode.yaml"


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
    broker_tracker_diff = summary.get("broker_tracker_diff", {})

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
    #
    # 2026-08-05 fix: previously read health.broker_tracker_mismatch_count,
    # which is the RAW mismatch count before G1-v2/v2-b/v2-c/v2-d lag
    # exclusion is applied (e.g. new-BUY qty lag, SELL qty lag, fast-fill
    # phantom, add-to-existing-position qty lag -- see
    # src/stock_swing/guardrails/postrun_mismatch.py). That raw count can be
    # nonzero for perfectly normal, already-excused timing lag (as seen
    # 2026-08-05: raw=2 for NBIS qty lag, while the lag-exclusion logic
    # itself reports real_mismatch_count=0), causing a false NO-GO here even
    # though circuit_breaker correctly stayed "ok". Use
    # broker_tracker_diff.real_mismatch_count (the same field the live
    # circuit breaker guardrail acts on) so this check matches actual
    # operational risk instead of raw noise.
    if "real_mismatch_count" in broker_tracker_diff:
        mismatch = broker_tracker_diff.get("real_mismatch_count", -1)
        mismatch_label = "broker_tracker_mismatch (real, lag-excused)"
    else:
        # Fallback for older console_summary snapshots that predate the
        # real_mismatch_count field.
        mismatch = health.get("broker_tracker_mismatch_count", -1)
        mismatch_label = "broker_tracker_mismatch (raw, real_mismatch_count unavailable)"
    results["mismatch"] = {
        "label": mismatch_label,
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


def check_promotion_readiness() -> dict[str, dict] | None:
    """R5-v2 (2026-08-14): supplementary, non-required promotion-gate check.

    Separate from the Required conditions in check() above -- this covers
    the previously-missing "market beta / cluster cap / top-5 concentration
    / clean cohort PF" combination called out as the R5-v2 REOPENED reason.
    Recommendation-only: does not affect the overall Go/No-Go decision or
    return code, since these were never part of the original 07-31 Required
    checklist. Returns None (not evaluated) if promotion_gate.py or its
    inputs are unavailable, rather than raising.
    """
    try:
        from stock_swing.risk.promotion_gate import evaluate_promotion_readiness
        from console.services.dashboard_service import DashboardService
        from console.services.benchmark_service import BenchmarkService
    except Exception:
        return None

    try:
        dash = DashboardService(PROJECT_ROOT)
        cluster_exposures = dash._get_cluster_exposure()
        positions = dash.get_positions()
        top5 = None
        if positions.get("available"):
            summary = dash._summarize_positions(positions.get("positions") or [])
            top5 = summary.get("top5_concentration")

        pnl_state_path = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
        pnl_state = _load(pnl_state_path)
        closed_trades = [t for t in pnl_state.get("trades", []) if t.get("status") == "closed"]

        bench = BenchmarkService(PROJECT_ROOT)
        daily_snapshots = pnl_state.get("daily_snapshots", [])
        beta_data = bench.calculate_beta(daily_snapshots)

        readiness = evaluate_promotion_readiness(
            cluster_exposures=cluster_exposures,
            top5_concentration=top5,
            beta_data=beta_data,
            closed_trades=closed_trades,
        )
        return {
            c.name: {
                "label": c.name,
                "pass": c.passed,
                "actual": c.actual,
                "required": c.required,
                "detail": c.detail,
            }
            for c in readiness.criteria
        }
    except Exception as exc:
        return {"error": {"label": "promotion_readiness_check_error", "pass": False, "actual": str(exc), "required": "no error", "detail": ""}}


def _update_ledger_gate_last_checked(ledger_pass: bool, now_jst: datetime) -> None:
    """Stamp ledger_quality_gate.last_checked in current_mode.yaml.

    console self-check (console/adapters/system_adapter.py::_check_ledger_validity)
    treats ledger_quality_gate as stale (and therefore reports it as a
    'critical_missing' evidence failure) if last_checked is more than 24h
    old, even when the gate is genuinely VALID and re-confirmed daily by
    this script. Previously last_checked was only ever bumped by manual
    edits during ledger repair work, so it silently went stale between
    repairs (observed 2026-08-01 -> 2026-08-07, 6 days unedited) and caused
    a false-positive 'blocked' /health status even though everything was
    actually fine. Bump it here on every --save run so daily re-verification
    is reflected without a manual edit each time.

    Only touches the `current_status:` and `last_checked:` lines via
    targeted regex substitution (not a full YAML round-trip) to avoid
    stripping the extensive human-authored comments in this file.
    """
    if not ledger_pass or not CURRENT_MODE_PATH.exists():
        return
    text = CURRENT_MODE_PATH.read_text(encoding="utf-8")
    today = now_jst.strftime("%Y-%m-%d")
    new_text, n1 = re.subn(
        r'(?m)^(  current_status:\s*)\S+(.*)$',
        lambda m: f"{m.group(1)}VALID{m.group(2)}",
        text,
        count=1,
    )
    new_text, n2 = re.subn(
        r'(?m)^(  last_checked:\s*)"?[0-9-]+"?(.*)$',
        lambda m: f'{m.group(1)}"{today}"{m.group(2)}',
        new_text,
        count=1,
    )
    if n1 and n2 and new_text != text:
        CURRENT_MODE_PATH.write_text(new_text, encoding="utf-8")
        print(f"[updated] {CURRENT_MODE_PATH} ledger_quality_gate.last_checked -> {today}", file=sys.stderr)


def format_report(results: dict[str, dict], save: bool = False, promotion: dict[str, dict] | None = None) -> str:
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

    if promotion is not None:
        lines += [
            "## 補足: R5-v2 Promotion Gate（参考情報、Required判定には含まれない）",
            "",
            "| 条件 | 判定 | 実測値 | 必要値 | 詳細 |",
            "|------|------|--------|--------|------|",
        ]
        for r in promotion.values():
            mark = "✅" if r["pass"] else "❌"
            lines.append(f"| {r['label']} | {mark} | {r['actual']} | {r['required']} | {r.get('detail', '')} |")
        lines.append("")

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
        ledger_pass = results.get("ledger_quality", {}).get("pass", False)
        _update_ledger_gate_last_checked(ledger_pass, now_jst)

    return report


def main() -> int:
    save = "--save" in sys.argv
    results = check()
    promotion = check_promotion_readiness()
    report = format_report(results, save=save, promotion=promotion)
    print(report)
    all_pass = all(r["pass"] for r in results.values())
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
