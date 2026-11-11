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
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PREFIX = "CRON_SUMMARY_JSON="
CONSOLE_PREFIX = "CONSOLE_SUMMARY_JSON "
OBSERVATION_JOBS = frozenset("stock_swing_paper_demo_" + slot
                             for slot in ("premarket", "market_open", "midday", "market_close"))
OBSERVATION_KEYS = frozenset("ENTRY_RESTRICTION_REVIEW_" + suffix
                            for suffix in ("ENABLED", "VERSION", "LEDGER_REVISION"))


def observation_environment(command: list[str], inherited: dict) -> dict[str, str]:
    """Read only allowlisted literal exports; never evaluate shell configuration.

    This intentionally accepts the existing managed job's simple export format,
    not a general shell language. Ambiguity becomes a diagnostic, not a gate.
    """
    values = {key: inherited[key] for key in OBSERVATION_KEYS if key in inherited}
    if len(command) != 3 or Path(command[0]).name != "bash" or command[1] != "-c":
        return values
    seen = set()
    for line in command[2].splitlines():
        if not any(key in line for key in OBSERVATION_KEYS):
            continue
        match = re.fullmatch(r"export (ENTRY_RESTRICTION_REVIEW_(?:ENABLED|VERSION|LEDGER_REVISION))=([A-Za-z0-9_.-]*)", line.strip())
        if not match or match[1] in seen:
            raise ValueError("nonliteral_or_duplicate_observation_configuration")
        seen.add(match[1]); values[match[1]] = match[2]
    return values


def _observation_preflight(command: list[str], root: Path) -> dict:
    try:
        # Script execution must use this checkout, not an editable sibling install.
        source = str(PROJECT_ROOT / "src")
        if source not in sys.path:
            sys.path.insert(0, source)
        from stock_swing.reporting.restriction_review_alerts import preflight_restriction_review
        environment = observation_environment(command, os.environ)
        return preflight_restriction_review(root, environment)
    except Exception:
        return {"status": "error", "reason": "configuration_preflight_unavailable",
                "as_of": datetime.now(timezone.utc).isoformat(),
                "eligible_to_trade": False, "automatic_release": False}


def observation_diagnostic(text: str, workflow: dict | None, preflight: dict) -> dict:
    """Use only this child output, never latest_console_summary's stale fallback."""
    result = {"status": "unknown", "source": "this_command_stdout",
              "as_of": datetime.now(timezone.utc).isoformat(), "preflight": preflight,
              "eligible_to_trade": False, "automatic_release": False}
    if workflow and workflow.get("dry_run") is True:
        result["status"] = "dry_run"
    elif workflow and workflow.get("status") == "skipped":
        result["status"] = "not_run"
    else:
        markers = [line[len(CONSOLE_PREFIX):] for line in text.splitlines()
                   if line.startswith(CONSOLE_PREFIX)]
        try:
            summary = json.loads(markers[-1]) if markers else {}
            review = summary["decision_funnel"]["entry_restriction_review"]
            run = summary["run"]
            if (run.get("dry_run") is False and isinstance(run.get("run_id"), str)
                    and run["run_id"] and isinstance(review, dict)
                    and review.get("eligible_to_trade") is False
                    and review.get("automatic_release") is False
                    and review.get("status") in {"observing", "error", "disabled", "unsupported_mode"}):
                result["status"] = review["status"]
                result["run_id"] = run["run_id"]
                result["observed_at"] = run.get("timestamp")
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    result["requires_attention"] = (result["status"] in {"error", "unknown", "unsupported_mode"}
                                    or preflight.get("status") == "error")
    if result["requires_attention"]:
        result["message"] = "PF観測診断を確認してください。売買結果とは別です。自動再実行は行いません。"
    return result


def run_logged(command: list[str], *, root: Path, name: str,
               require_summary: bool = False) -> tuple[int, dict]:
    if not command or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("non-empty command and a safe workflow name are required")
    log_dir = root / "logs" / "gateway_workflows"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    log_path = log_dir / f"{name}_{stamp}_{uuid4().hex[:8]}.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    preflight = _observation_preflight(command, root) if name in OBSERVATION_JOBS else None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            if preflight is not None:
                output.write("OBSERVATION_PREFLIGHT_JSON=" + json.dumps(preflight, ensure_ascii=False) + "\n")
                output.flush()
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
    if preflight is not None:
        report["observation"] = observation_diagnostic(text, summary, preflight)
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
