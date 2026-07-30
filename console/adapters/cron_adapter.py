"""Adapter for cron jobs data."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from console.utils.structured_json import parse_json_from_output


class CronAdapter:
    """Read cron jobs from OpenClaw Gateway API."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
    
    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get all cron jobs from OpenClaw Gateway."""
        try:
            # Try to get from OpenClaw HTTP Gateway API
            import urllib.request
            import os

            gateway_token = os.environ.get('OPENCLAW_GATEWAY_TOKEN', '')
            req = urllib.request.Request(
                'http://localhost:8484/api/cron/list',
                headers={'Authorization': f'Bearer {gateway_token}'} if gateway_token else {}
            )

            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                jobs = data.get("jobs", [])
        except Exception:
            # Fallback: try CLI
            try:
                result = subprocess.run(
                    ['openclaw', 'cron', 'list', '--json'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode != 0:
                    return self._get_from_backup()

                parsed = parse_json_from_output(result.stdout)
                if not parsed.ok or not isinstance(parsed.data, dict):
                    return self._get_from_backup()
                data = parsed.data
                jobs = data.get("jobs", [])
            except Exception:
                return self._get_from_backup()

        return self._enrich_jobs(jobs)

    def get_run_history(self, job_id: str, *, limit: int = 3) -> Dict[str, Any]:
        """Return sanitized recent run history for a cron job.

        OpenClaw's `cron runs` command emits JSON by default, but some versions do
        not accept `--json`. We therefore parse the balanced JSON fragment from the
        plain stdout and treat any parse failure as critical evidence loss.
        """
        try:
            result = subprocess.run(
                ['openclaw', 'cron', 'runs', '--id', job_id, '--limit', str(limit)],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            return {"ok": False, "runs": [], "error": str(exc), "job_id": job_id}

        if result.returncode != 0:
            return {
                "ok": False,
                "runs": [],
                "job_id": job_id,
                "error": result.stderr.strip() or result.stdout.strip() or "command_failed",
            }

        parsed = parse_json_from_output(result.stdout)
        if not parsed.ok or not isinstance(parsed.data, dict):
            return {
                "ok": False,
                "runs": [],
                "job_id": job_id,
                "error": parsed.error or "invalid_json",
                "sanitized_text": parsed.sanitized_text,
            }

        payload = parsed.data
        runs = payload.get("entries")
        if not isinstance(runs, list):
            runs = payload.get("runs")
        if not isinstance(runs, list):
            runs = []
        return {
            "ok": True,
            "job_id": job_id,
            "runs": runs,
            "total": payload.get("total"),
            "limit": payload.get("limit"),
        }
    
    def _get_from_backup(self) -> List[Dict[str, Any]]:
        """Fallback: get jobs from backup file."""
        backup_file = self.project_root / "cron_backup" / "jobs.json"
        if not backup_file.exists():
            return []

        try:
            data = json.loads(backup_file.read_text())
            jobs = data.get("jobs", [])
            return self._enrich_jobs(jobs)
        except Exception:
            return []

    def _enrich_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = datetime.now(tz=timezone.utc)
        enriched_jobs: List[Dict[str, Any]] = []

        for raw_job in jobs:
            job = dict(raw_job)
            if "schedule" in job:
                job["schedule_display"] = self._format_schedule(job["schedule"])

            state = job.get("state") or {}
            last_run_ms = state.get("lastRunAtMs")
            next_run_ms = state.get("nextRunAtMs")

            if last_run_ms:
                last_run = datetime.fromtimestamp(last_run_ms / 1000, tz=timezone.utc).astimezone()
                job["last_run"] = last_run.isoformat()

            if next_run_ms:
                next_run = datetime.fromtimestamp(next_run_ms / 1000, tz=timezone.utc).astimezone()
                job["next_run"] = next_run.isoformat()
                running = str(state.get("lastStatus") or "").lower() == "running"
                if job.get("enabled") and not running and next_run.astimezone(timezone.utc) < now:
                    job["lag_seconds"] = int((now - next_run.astimezone(timezone.utc)).total_seconds())
                else:
                    job["lag_seconds"] = 0

            if "lastDurationMs" in state:
                job["last_duration_ms"] = state.get("lastDurationMs")
            if "lastRunStatus" in state:
                job["last_run_status"] = state.get("lastRunStatus")
            if state.get("lastError"):
                job["last_error"] = state.get("lastError")

            enriched_jobs.append(job)

        return enriched_jobs
    
    def _format_schedule(self, schedule: Dict[str, Any]) -> str:
        """Format schedule for display."""
        kind = schedule.get("kind", "")
        if kind == "cron":
            expr = schedule.get("expr", "")
            tz = schedule.get("tz", "UTC")
            return f"{expr} ({tz})"
        elif kind == "every":
            every_ms = schedule.get("everyMs", 0)
            minutes = every_ms // 60000
            return f"Every {minutes}min"
        elif kind == "at":
            at = schedule.get("at", "")
            return f"At {at}"
        return "Unknown"
