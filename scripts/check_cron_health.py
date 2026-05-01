#!/usr/bin/env python3
"""Check health of key OpenClaw cron jobs for stock_swing.

Examples:
    python scripts/check_cron_health.py
    python scripts/check_cron_health.py --only daily_report_morning
    python scripts/check_cron_health.py --only paper_demo_premarket,paper_demo_market_open
    python scripts/check_cron_health.py --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


@dataclass
class Thresholds:
    stale_warn_minutes: Optional[int] = None
    stale_critical_minutes: Optional[int] = None
    duration_warn_seconds: Optional[int] = None
    duration_critical_seconds: Optional[int] = None
    consecutive_fail_warn: Optional[int] = None
    consecutive_fail_critical: Optional[int] = None


@dataclass
class JobSpec:
    key: str
    job_id: str
    label: str
    thresholds: Thresholds
    expect_delivery: bool = False
    timeout_warn_only: bool = False


JOBS: List[JobSpec] = [
    JobSpec(
        key="reconciliation",
        job_id="73410e77-5a22-40f5-9b90-d2c6d286434e",
        label="stock_swing_order_reconciliation",
        thresholds=Thresholds(
            stale_warn_minutes=30,
            stale_critical_minutes=60,
            duration_warn_seconds=180,
            duration_critical_seconds=300,
            consecutive_fail_warn=2,
            consecutive_fail_critical=3,
        ),
    ),
    JobSpec(
        key="daily_report_morning",
        job_id="494e46d9-9214-492f-b83c-18a5e59bd5f7",
        label="daily_report_morning",
        thresholds=Thresholds(
            stale_warn_minutes=25 * 60,
            stale_critical_minutes=27 * 60,
            duration_warn_seconds=30,
            duration_critical_seconds=60,
            consecutive_fail_warn=1,
            consecutive_fail_critical=2,
        ),
        expect_delivery=True,
    ),
    JobSpec(
        key="news_collection",
        job_id="0a5ae126-cc03-44af-b4a8-b12b9821bd6f",
        label="stock_swing_news_collection",
        thresholds=Thresholds(
            stale_warn_minutes=180,
            stale_critical_minutes=360,
            duration_critical_seconds=300,
            consecutive_fail_warn=2,
            consecutive_fail_critical=6,
        ),
    ),
    JobSpec(
        key="paper_demo_premarket",
        job_id="d4fb64ec-6b22-4985-8945-552f986eec2b",
        label="stock_swing_paper_demo_premarket",
        thresholds=Thresholds(
            stale_warn_minutes=24 * 60,
            stale_critical_minutes=2 * 24 * 60,
            duration_warn_seconds=2400,
            duration_critical_seconds=3300,
            consecutive_fail_warn=1,
            consecutive_fail_critical=3,
        ),
        expect_delivery=True,
        timeout_warn_only=True,
    ),
    JobSpec(
        key="paper_demo_market_open",
        job_id="6eda856d-915a-4605-9428-8d5d13553176",
        label="stock_swing_paper_demo_market_open",
        thresholds=Thresholds(
            stale_warn_minutes=24 * 60,
            stale_critical_minutes=2 * 24 * 60,
            duration_warn_seconds=2400,
            duration_critical_seconds=3300,
            consecutive_fail_warn=1,
            consecutive_fail_critical=3,
        ),
        expect_delivery=True,
        timeout_warn_only=True,
    ),
    JobSpec(
        key="paper_demo_midday",
        job_id="a2986600-6e6a-4712-afa1-0ac8062e90fd",
        label="stock_swing_paper_demo_midday",
        thresholds=Thresholds(
            stale_warn_minutes=24 * 60,
            stale_critical_minutes=2 * 24 * 60,
            duration_warn_seconds=2400,
            duration_critical_seconds=3300,
            consecutive_fail_warn=1,
            consecutive_fail_critical=3,
        ),
        expect_delivery=True,
        timeout_warn_only=True,
    ),
    JobSpec(
        key="paper_demo_market_close",
        job_id="fc5f2185-2117-4413-9684-da79ac428869",
        label="stock_swing_paper_demo_market_close",
        thresholds=Thresholds(
            stale_warn_minutes=24 * 60,
            stale_critical_minutes=2 * 24 * 60,
            duration_warn_seconds=2400,
            duration_critical_seconds=3300,
            consecutive_fail_warn=1,
            consecutive_fail_critical=3,
        ),
        expect_delivery=True,
        timeout_warn_only=True,
    ),
]

STATUS_ORDER = {"ok": 0, "warn": 1, "critical": 2}
STATUS_ICON = {"ok": "✅", "warn": "⚠️", "critical": "🚨"}


def run_openclaw_json(args: List[str]) -> Dict:
    result = subprocess.run(
        ["openclaw"] + args,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "openclaw command failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse JSON from openclaw {' '.join(args)}: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check stock_swing cron health")
    parser.add_argument(
        "--only",
        type=str,
        help="Comma-separated job keys to check (e.g. daily_report_morning,paper_demo_midday)",
    )
    parser.add_argument("--limit", type=int, default=10, help="How many recent runs to inspect per job")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser.parse_args()


def pick_jobs(only_arg: Optional[str]) -> List[JobSpec]:
    if not only_arg:
        return JOBS
    wanted = {x.strip() for x in only_arg.split(",") if x.strip()}
    selected = [job for job in JOBS if job.key in wanted]
    missing = wanted.difference(job.key for job in selected)
    if missing:
        raise SystemExit(f"unknown job key(s): {', '.join(sorted(missing))}")
    return selected


def ts_to_local(ts_ms: Optional[int]) -> Optional[str]:
    if not ts_ms:
        return None
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def age_minutes(ts_ms: Optional[int]) -> Optional[float]:
    if not ts_ms:
        return None
    now = datetime.now(timezone.utc).timestamp() * 1000
    return max(0.0, (now - ts_ms) / 1000 / 60)


def is_timeout_error(entry: Dict) -> bool:
    error = (entry.get("error") or "").lower()
    return "timed out" in error or "timeout" in error


def is_incomplete_ok(entry: Dict) -> bool:
    summary = (entry.get("summary") or "").lower()
    return "did not finish cleanly" in summary or "sigterm" in summary


def is_blocked_ok(entry: Dict) -> bool:
    summary = (entry.get("summary") or "").lower()
    return (
        "approval required" in summary
        or "[blocked]" in summary
        or "status: blocked" in summary
        or "status=blocked" in summary
    )


def consecutive_failures(entries: List[Dict]) -> int:
    count = 0
    for entry in entries:
        status = entry.get("status")
        if status == "ok" and not is_incomplete_ok(entry) and not is_blocked_ok(entry):
            break
        count += 1
    return count


def bump(level: str, new_level: str) -> str:
    return new_level if STATUS_ORDER[new_level] > STATUS_ORDER[level] else level


def evaluate_job(job: JobSpec, entries: List[Dict]) -> Dict:
    issues: List[str] = []
    level = "ok"

    if not entries:
        return {
            "job": job.key,
            "label": job.label,
            "status": "critical",
            "issues": ["no run history found"],
            "last_run": None,
            "duration_seconds": None,
            "consecutive_failures": None,
            "delivery_status": None,
        }

    latest = entries[0]
    latest_status = latest.get("status", "unknown").lower()
    latest_run_ms = latest.get("runAtMs") or latest.get("ts")
    latest_duration_seconds = round((latest.get("durationMs") or 0) / 1000, 1)
    latest_delivery = latest.get("deliveryStatus")
    fail_streak = consecutive_failures(entries)

    if latest_status not in ["ok", "blocked"]:
        if job.timeout_warn_only and is_timeout_error(latest):
            level = bump(level, "warn")
            issues.append(f"latest run timed out ({latest_duration_seconds}s)")
        else:
            level = bump(level, "critical")
            issues.append(f"latest run status={latest_status}")
            if latest.get("error"):
                issues.append(str(latest.get("error")))

    if is_blocked_ok(latest):
        level = bump(level, "critical")
        issues.append("latest run was marked ok but blocked by exec approval / non-execution")

    if is_incomplete_ok(latest):
        level = bump(level, "warn")
        issues.append("latest run was marked ok but summary indicates SIGTERM / incomplete finish")

    th = job.thresholds
    if th.consecutive_fail_warn is not None and fail_streak >= th.consecutive_fail_warn:
        level = bump(level, "warn")
        issues.append(f"consecutive failures/incomplete runs={fail_streak}")
    if th.consecutive_fail_critical is not None and fail_streak >= th.consecutive_fail_critical:
        level = bump(level, "critical")

    if th.duration_warn_seconds is not None and latest_duration_seconds >= th.duration_warn_seconds:
        level = bump(level, "warn")
        issues.append(f"duration high ({latest_duration_seconds}s)")
    if th.duration_critical_seconds is not None and latest_duration_seconds >= th.duration_critical_seconds:
        level = bump(level, "critical")

    latest_age_minutes = age_minutes(latest_run_ms)
    if latest_age_minutes is not None and th.stale_warn_minutes is not None and latest_age_minutes >= th.stale_warn_minutes:
        level = bump(level, "warn")
        issues.append(f"last run is stale ({latest_age_minutes:.1f}m ago)")
    if latest_age_minutes is not None and th.stale_critical_minutes is not None and latest_age_minutes >= th.stale_critical_minutes:
        level = bump(level, "critical")

    if job.expect_delivery and latest_status == "ok" and latest_delivery not in {"delivered", "none", None}:
        level = bump(level, "warn")
        issues.append(f"unexpected delivery status={latest_delivery}")

    if not issues:
        issues.append("healthy")

    return {
        "job": job.key,
        "label": job.label,
        "status": level,
        "latest_status": latest_status,
        "issues": issues,
        "last_run": ts_to_local(latest_run_ms),
        "duration_seconds": latest_duration_seconds,
        "consecutive_failures": fail_streak,
        "delivery_status": latest_delivery,
        "next_run": ts_to_local(latest.get("nextRunAtMs")),
    }


def print_text(results: List[Dict]) -> int:
    overall = "ok"
    for item in results:
        overall = bump(overall, item["status"])

    print("=== stock_swing cron health ===")
    print(f"overall: {STATUS_ICON[overall]} {overall.upper()}")
    print()

    for item in results:
        print(f"{STATUS_ICON[item['status']]} {item['job']} ({item['label']})")
        print(f"  latest : {item.get('latest_status')} @ {item.get('last_run')}")
        print(f"  duration: {item.get('duration_seconds')}s")
        print(f"  delivery: {item.get('delivery_status')}")
        print(f"  next   : {item.get('next_run')}")
        print(f"  streak : {item.get('consecutive_failures')}")
        for issue in item["issues"]:
            print(f"  - {issue}")
        print()

    return 0 if overall == "ok" else 1


def main() -> int:
    args = parse_args()
    jobs = pick_jobs(args.only)
    results: List[Dict] = []

    for job in jobs:
        payload = run_openclaw_json(["cron", "runs", "--id", job.job_id, "--limit", str(args.limit)])
        entries = payload.get("entries", [])
        results.append(evaluate_job(job, entries))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    return print_text(results)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
