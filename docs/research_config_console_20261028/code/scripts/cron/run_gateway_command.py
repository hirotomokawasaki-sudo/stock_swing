#!/usr/bin/env python3
"""Run an existing workflow once, without an LLM; retain its complete log.

Never retries commands: replaying an order workflow after an ambiguous failure
could duplicate orders. The Gateway owns deadlines and process-tree cleanup.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PREFIX = "CRON_SUMMARY_JSON="


def run_logged(command: list[str], *, root: Path, name: str,
               require_summary: bool = False) -> tuple[int, dict]:
    if not command or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("non-empty command and a safe workflow name are required")
    log_dir = root / "logs" / "gateway_workflows"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    log_path = log_dir / f"{name}_{stamp}_{uuid4().hex[:8]}.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            result = subprocess.run(command, cwd=root, stdout=output,
                                    stderr=subprocess.STDOUT, check=False)
        code = result.returncode
        if code < 0:
            code = 128 - code
    except OSError as exc:
        return 127, {"job": name, "status": "error", "exit_code": 127,
                     "reason": f"command_start_failed:{type(exc).__name__}",
                     "log_file": str(log_path)}

    text = log_path.read_text(encoding="utf-8", errors="replace")
    markers = [line[len(SUMMARY_PREFIX):] for line in text.splitlines()
               if line.startswith(SUMMARY_PREFIX)]
    summary = None
    if markers:
        try:
            candidate = json.loads(markers[-1])
            if isinstance(candidate, dict):
                summary = candidate
        except (TypeError, ValueError):
            pass
    reason = None
    if require_summary and (summary is None or summary.get("status") not in
                            {"ok", "skipped", "success"}):
        reason = "missing_or_unsuccessful_workflow_summary"
        code = code or 1
    if summary is not None and summary.get("status") in {"error", "failed"}:
        reason = "workflow_reported_error"
        code = code or 1
    report = {"job": name, "status": "ok" if code == 0 else "error",
              "exit_code": code, "log_file": str(log_path)}
    if summary is not None:
        report["workflow"] = summary
    if reason:
        report["reason"] = reason
    if code or summary is None:
        report["output_tail"] = "\n".join(text.splitlines()[-8:])[-2400:]
    return code, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--require-summary", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    code, report = run_logged(command, root=PROJECT_ROOT, name=args.name,
                              require_summary=args.require_summary)
    print(json.dumps(report, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
