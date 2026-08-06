"""Adapter for evidence-based system health."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from console.utils.structured_json import parse_json_from_output

# 2026-08-04: the console HTTP server is started by launchd (see
# ~/Library/LaunchAgents/com.hirotomookawasaki.stock_swing.console.watchdog.plist),
# whose default environment PATH is only /usr/bin:/bin:/usr/sbin:/sbin -- it
# does NOT include /opt/homebrew/bin, where `openclaw` actually lives on this
# host. shutil.which("openclaw") under that inherited PATH silently returns
# None, so subprocess.run(["openclaw", ...]) always raised
# FileNotFoundError, making cron_run_history permanently "critical: not ok"
# and keeping the overall system health score capped at 49 ("blocked") around
# the clock, even when everything else was fine. Resolve a usable absolute
# path once at import time, falling back to common install locations when
# PATH doesn't have it. See docs/daily_logs/2026-08-04.md.
_OPENCLAW_FALLBACK_PATHS = (
    "/opt/homebrew/bin/openclaw",
    "/usr/local/bin/openclaw",
)


def _resolve_openclaw_bin() -> str:
    found = shutil.which("openclaw")
    if found:
        return found
    for candidate in _OPENCLAW_FALLBACK_PATHS:
        if os.path.exists(candidate):
            return candidate
    return "openclaw"  # preserve original behavior/error message if truly absent


def _subprocess_env() -> dict[str, str]:
    """Env for subprocess calls to `openclaw`.

    `openclaw` is a `#!/usr/bin/env node` script, so PATH must also resolve
    `node`, not just the `openclaw` binary itself. Under launchd's minimal
    default PATH (/usr/bin:/bin:/usr/sbin:/sbin), `env node` fails even after
    resolving an absolute path to `openclaw`. Augment PATH with the same
    Homebrew bin directories used to locate `openclaw`, without discarding
    whatever PATH the process already has.
    """
    env = dict(os.environ)
    extra_dirs = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin"]
    current = env.get("PATH", "")
    current_parts = current.split(os.pathsep) if current else []
    merged = current_parts + [d for d in extra_dirs if d not in current_parts]
    env["PATH"] = os.pathsep.join(merged)
    return env


_OPENCLAW_BIN = _resolve_openclaw_bin()
_OPENCLAW_ENV = _subprocess_env()

try:
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "src"))
    from stock_swing.cli.collect_data import finnhub_news_row_succeeded
except Exception:  # pragma: no cover - defensive fallback if import layout changes
    def finnhub_news_row_succeeded(row: dict) -> bool:  # type: ignore[misc]
        if row.get("used_fallback"):
            return False
        reason = str(row.get("reason") or "ok")
        if reason == "ok":
            return int(row.get("news_count", 0) or 0) > 0
        return reason == "no_company_news"

_LEDGER_STALENESS_S = 86400
_GUARDRAIL_STALENESS_S = 18 * 3600
_BROKER_STALENESS_S = 3600
_CONSOLE_STALENESS_S = 900
_SOURCE_STALENESS_S = 48 * 3600
_CRON_TIMEOUT_S = 10
_REQUIRED_FINNHUB_COVERAGE = 0.995
_CURRENT_CONSOLE_SUMMARY = Path("reports/console/latest_console_summary.json")


def _age_seconds(iso_str: str | None) -> float | None:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())


def _mtime_age_seconds(path: Path) -> float | None:
    if not path.exists():
        return None
    return max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)


def _current_market_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class SystemAdapter:
    """Read system health and configuration."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.runtime_config = project_root / "config" / "runtime" / "current_mode.yaml"
        self.env_file = project_root / ".env"

    def get_health(self) -> dict[str, Any]:
        runtime_mode = self._get_runtime_mode()
        api_ok = self._check_api_keys()
        venv_ok = (self.project_root / "venv").exists()

        evidence = self._collect_evidence()
        critical_failures = [name for name, row in evidence.items() if row["critical"] and not row["ok"]]
        noncritical_issues = [name for name, row in evidence.items() if not row["critical"] and not row["ok"]]

        score = 0
        if runtime_mode == "paper":
            score += 25
        if api_ok:
            score += 15
        if venv_ok:
            score += 10

        total = len(evidence)
        ok_count = sum(1 for row in evidence.values() if row["ok"])
        if total:
            score += round(50 * ok_count / total)

        if critical_failures:
            score = min(score, 49)
            status = "blocked"
        elif noncritical_issues:
            score = min(score, 79)
            status = "degraded"
        else:
            score = min(score, 100)
            status = "healthy"

        return {
            "runtime_mode": runtime_mode,
            "api_keys_configured": api_ok,
            "venv_exists": venv_ok,
            "score": score,
            "status": status,
            "evidence": evidence,
            "critical_missing": critical_failures,
            "noncritical_issues": noncritical_issues,
            "evidence_status": "invalid" if critical_failures else "valid",
        }

    def _collect_evidence(self) -> dict[str, dict[str, Any]]:
        return {
            "ledger_validity": self._check_ledger_validity(),
            "guardrail_metric_freshness": self._check_guardrail_freshness(),
            "broker_tracker_reconciliation": self._check_broker_tracker_freshness(),
            "console_summary_freshness": self._check_console_summary_freshness(),
            "source_sla": self._check_source_sla(),
            "cron_run_history": self._check_cron_run_history(),
        }

    def _check_ledger_validity(self) -> dict[str, Any]:
        try:
            cfg = yaml.safe_load(self.runtime_config.read_text(encoding="utf-8")) if self.runtime_config.exists() else {}
            gate = cfg.get("ledger_quality_gate", {}) or {}
            status = str(gate.get("current_status", "UNKNOWN")).upper()
            last_checked = gate.get("last_checked")
            age = _age_seconds(f"{last_checked}T00:00:00+00:00") if last_checked else None
            stale = age is None or age > _LEDGER_STALENESS_S
            return {
                "critical": True,
                "ok": status == "VALID" and not stale,
                "status": status,
                "last_checked": last_checked,
                "age_seconds": None if age is None else round(age),
                "stale": stale,
                "detail": "config/runtime/current_mode.yaml:ledger_quality_gate",
            }
        except Exception as exc:
            return {"critical": True, "ok": False, "error": str(exc)}

    def _check_guardrail_freshness(self) -> dict[str, Any]:
        cb_path = self.project_root / "data" / "guardrails" / "circuit_breaker.json"
        day_start_path = self.project_root / "data" / "guardrails" / "day_start_snapshot.json"
        try:
            cb = json.loads(cb_path.read_text(encoding="utf-8")) if cb_path.exists() else {}
            day_start = json.loads(day_start_path.read_text(encoding="utf-8")) if day_start_path.exists() else {}
        except Exception as exc:
            return {"critical": True, "ok": False, "error": str(exc)}

        market_date = _current_market_date()
        cb_as_of = cb.get("cleared_at") or cb.get("triggered_at")
        cb_age = _age_seconds(cb_as_of)
        cb_status = str(cb.get("status") or "unknown")
        day_start_missing = list(day_start.get("missing_fields") or [])
        day_start_age = _age_seconds(day_start.get("captured_at"))
        problems: list[str] = []
        if not cb_path.exists():
            problems.append("missing_circuit_breaker")
        if cb_age is None or cb_age > _GUARDRAIL_STALENESS_S:
            problems.append("stale_circuit_breaker")
        if not day_start_path.exists():
            problems.append("missing_day_start_snapshot")
        if day_start.get("market_date") != market_date:
            problems.append("market_date_mismatch")
        if not day_start.get("captured_at"):
            problems.append("missing_captured_at")
        if not day_start.get("source"):
            problems.append("missing_source")
        if day_start_age is None or day_start_age > _GUARDRAIL_STALENESS_S:
            problems.append("stale_day_start_snapshot")
        if day_start_missing:
            problems.append("missing_day_start_metrics")

        # recovery_pending = circuit breaker was manually cleared but a clean run has
        # not yet confirmed broker/tracker parity.  Surface as a non-blocking warning
        # (not ok) so the operator knows a clean scheduled run is still required.
        if cb_status == "recovery_pending" and not problems:
            problems.append("cb_recovery_pending")

        return {
            "critical": True,
            "ok": not problems and cb_status in {"ok"},
            "cb_status": cb_status,
            "cb_as_of": cb_as_of,
            "cb_age_seconds": None if cb_age is None else round(cb_age),
            "market_date": day_start.get("market_date"),
            "expected_market_date": market_date,
            "captured_at": day_start.get("captured_at"),
            "captured_age_seconds": None if day_start_age is None else round(day_start_age),
            "source": day_start.get("source"),
            "missing_fields": day_start_missing,
            "problems": problems,
            "detail": "data/guardrails/circuit_breaker.json + day_start_snapshot.json",
        }

    def _check_broker_tracker_freshness(self) -> dict[str, Any]:
        audit_path = self.project_root / "data" / "audits" / "reconcile_status.json"
        try:
            if not audit_path.exists():
                return {
                    "critical": True,
                    "ok": False,
                    "detail": "data/audits/reconcile_status.json missing",
                }
            data = json.loads(audit_path.read_text(encoding="utf-8"))
            as_of = data.get("as_of") or data.get("time")
            age = _age_seconds(as_of)
            mismatch = int(data.get("unexplained_mismatch_count", 1))
            stale = age is None or age > _BROKER_STALENESS_S
            return {
                "critical": True,
                "ok": mismatch == 0 and not stale,
                "as_of": as_of,
                "age_seconds": None if age is None else round(age),
                "mismatch_count": mismatch,
                "stale": stale,
                "detail": "data/audits/reconcile_status.json",
            }
        except Exception as exc:
            return {"critical": True, "ok": False, "error": str(exc)}

    def _check_console_summary_freshness(self) -> dict[str, Any]:
        summary_path = self.project_root / _CURRENT_CONSOLE_SUMMARY
        try:
            age = _mtime_age_seconds(summary_path)
            stale = age is None or age > _CONSOLE_STALENESS_S
            return {
                "critical": True,
                "ok": not stale,
                "age_seconds": None if age is None else round(age),
                "stale": stale,
                "detail": str(_CURRENT_CONSOLE_SUMMARY),
            }
        except Exception as exc:
            return {"critical": True, "ok": False, "error": str(exc)}

    def _check_source_sla(self) -> dict[str, Any]:
        sources_dir = self.project_root / "config" / "sources"
        required_sources: list[str] = []
        try:
            for path in sorted(sources_dir.glob("*.yaml")):
                cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if cfg.get("required"):
                    required_sources.append(path.stem)
        except Exception as exc:
            return {"critical": True, "ok": False, "error": str(exc)}

        required_results: list[dict[str, Any]] = []
        failures: list[str] = []
        for source in required_sources:
            row = self._evaluate_required_source(source)
            required_results.append(row)
            if not row["ok"]:
                failures.append(source)

        return {
            "critical": True,
            "ok": not failures,
            "required_sources": required_sources,
            "failing_sources": failures,
            "sources": required_results,
            "detail": "config/sources/*.yaml + data/audits/*_status.json",
        }

    def _evaluate_required_source(self, source: str) -> dict[str, Any]:
        if source == "finnhub":
            status_path = self.project_root / "data" / "audits" / "news_collection_status.json"
            if not status_path.exists():
                return {"source": source, "ok": False, "reason": "missing_status"}
            data = json.loads(status_path.read_text(encoding="utf-8"))
            rows = list(data.get("symbols") or [])
            age = _age_seconds(data.get("time"))
            total = len(rows)
            # 2026-08-04: 'no_company_news' is a legitimate successful-but-empty
            # result (see collect_data.finnhub_news_row_succeeded docstring),
            # not a collection failure. Shared with collect_data.py so the
            # cron pass/fail decision and this health check agree.
            ok_rows = sum(1 for row in rows if finnhub_news_row_succeeded(row))
            coverage = (ok_rows / total) if total else 0.0
            failure_reasons = sorted(
                {
                    str(row.get("reason") or "unknown")
                    for row in rows
                    if not finnhub_news_row_succeeded(row)
                }
            )
            stale = age is None or age > _SOURCE_STALENESS_S
            ok = not stale and not data.get("timed_out") and coverage >= _REQUIRED_FINNHUB_COVERAGE and not failure_reasons
            return {
                "source": source,
                "ok": ok,
                "as_of": data.get("time"),
                "age_seconds": None if age is None else round(age),
                "timed_out": bool(data.get("timed_out")),
                "coverage_ratio": round(coverage, 6),
                "coverage_pct": round(coverage * 100, 3),
                "required_min_coverage": _REQUIRED_FINNHUB_COVERAGE,
                "failure_reasons": failure_reasons,
                "stale": stale,
            }

        status_candidates = [
            self.project_root / "data" / "audits" / f"{source}_collection_status.json",
            self.project_root / "data" / "audits" / f"{source}_quotes_status.json",
            self.project_root / "data" / "audits" / f"{source}_bars_status.json",
        ]
        found = [path for path in status_candidates if path.exists()]
        if not found:
            return {"source": source, "ok": False, "reason": "missing_status"}
        statuses: list[dict[str, Any]] = []
        ok = True
        for path in found:
            data = json.loads(path.read_text(encoding="utf-8"))
            status = str(data.get("status") or "unknown")
            age = _age_seconds(data.get("time"))
            stale = age is None or age > _SOURCE_STALENESS_S
            row_ok = status == "ok" and not stale
            ok = ok and row_ok
            statuses.append(
                {
                    "path": path.name,
                    "status": status,
                    "age_seconds": None if age is None else round(age),
                    "stale": stale,
                }
            )
        return {"source": source, "ok": ok, "statuses": statuses}

    def _fetch_one_job_runs(self, job: dict[str, Any]) -> dict[str, Any] | None:
        """Fetch run history for a single cron job. Returns an error dict on
        failure, or None on success. Runs in a worker thread; subprocess.run
        releases the GIL while waiting on the child process, so this is safe
        to parallelize across jobs.
        """
        job_id = str(job.get("id") or "")
        if not job_id:
            return {"job": job.get("name") or "unknown", "error": "missing_job_id"}
        try:
            result = subprocess.run(
                [_OPENCLAW_BIN, "cron", "runs", "--id", job_id, "--limit", "3"],
                capture_output=True,
                text=True,
                check=False,
                timeout=_CRON_TIMEOUT_S,
                env=_OPENCLAW_ENV,
            )
        except Exception as exc:
            return {"job": job.get("name") or job_id, "job_id": job_id, "error": str(exc)}
        if result.returncode != 0:
            return {
                "job": job.get("name") or job_id,
                "job_id": job_id,
                "error": result.stderr.strip() or result.stdout.strip() or "command_failed",
            }
        parsed = parse_json_from_output(result.stdout)
        if not parsed.ok:
            return {"job": job.get("name") or job_id, "job_id": job_id, "error": parsed.error}
        if not isinstance(parsed.data, dict):
            return {
                "job": job.get("name") or job_id,
                "job_id": job_id,
                "error": f"unexpected payload type: {type(parsed.data).__name__}",
            }
        return None

    def _check_cron_run_history(self) -> dict[str, Any]:
        try:
            jobs_payload = self._run_openclaw_json(["cron", "list", "--json"])
        except Exception as exc:
            return {"critical": True, "ok": False, "error": str(exc)}

        jobs = list(jobs_payload.get("jobs") or [])
        enabled_jobs = [job for job in jobs if job.get("enabled", True)]
        parse_errors: list[dict[str, Any]] = []
        total_jobs = len(enabled_jobs)

        # 2026-08-06: this used to shell out to `openclaw cron runs` once per
        # job, sequentially. With 14 enabled jobs that took ~11.7s total,
        # which was slower than the console watchdog's 5s /health timeout
        # and caused an infinite restart loop (see docs/daily_logs/2026-08-06.md).
        # Run the subprocess calls concurrently instead; each call still has
        # its own _CRON_TIMEOUT_S timeout, so a single slow/hung job can no
        # longer stall the whole check by (jobs * timeout).
        if total_jobs:
            with ThreadPoolExecutor(max_workers=min(total_jobs, 8)) as pool:
                futures = [pool.submit(self._fetch_one_job_runs, job) for job in enabled_jobs]
                for future in as_completed(futures):
                    err = future.result()
                    if err is not None:
                        parse_errors.append(err)

        parsed_jobs = total_jobs - len(parse_errors)
        coverage = (parsed_jobs / total_jobs) if total_jobs else 0.0
        return {
            "critical": True,
            "ok": total_jobs > 0 and not parse_errors and coverage == 1.0,
            "enabled_jobs": total_jobs,
            "parsed_jobs": parsed_jobs,
            "parse_coverage": round(coverage, 6),
            "parse_errors": parse_errors,
            "detail": "openclaw cron list --json + openclaw cron runs --limit",
        }

    def _run_openclaw_json(self, args: list[str]) -> dict[str, Any]:
        result = subprocess.run(
            [_OPENCLAW_BIN] + args,
            capture_output=True,
            text=True,
            check=False,
            timeout=_CRON_TIMEOUT_S,
            env=_OPENCLAW_ENV,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "openclaw command failed")
        parsed = parse_json_from_output(result.stdout)
        if not parsed.ok:
            raise RuntimeError(parsed.error or "invalid JSON")
        if not isinstance(parsed.data, dict):
            raise RuntimeError(f"unexpected payload type: {type(parsed.data).__name__}")
        return parsed.data

    def _get_runtime_mode(self) -> str:
        if not self.runtime_config.exists():
            return "unknown"
        try:
            data = yaml.safe_load(self.runtime_config.read_text(encoding="utf-8")) or {}
            return str(data.get("mode", "unknown"))
        except Exception:
            return "error"

    def _check_api_keys(self) -> bool:
        if not self.env_file.exists():
            return False
        content = self.env_file.read_text(encoding="utf-8")
        required_keys = ["FINNHUB_API_KEY"]
        for key in required_keys:
            if f"{key}=your_key_here" in content or f"{key}=" not in content:
                return False
        return True
