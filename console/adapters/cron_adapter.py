"""Adapter for cron jobs data."""

import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime


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
        except Exception as e:
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
                
                data = json.loads(result.stdout)
                jobs = data.get("jobs", [])
            except Exception:
                return self._get_from_backup()
            
            # Enrich with readable info
            for job in jobs:
                if "schedule" in job:
                    schedule = job["schedule"]
                    job["schedule_display"] = self._format_schedule(schedule)
                
                # Extract last_run from state
                if "state" in job:
                    state = job["state"]
                    if "lastRunAtMs" in state:
                        last_run_ms = state["lastRunAtMs"]
                        last_run = datetime.fromtimestamp(last_run_ms / 1000)
                        job["last_run"] = last_run.isoformat()
                    
                    if "nextRunAtMs" in state:
                        next_run_ms = state["nextRunAtMs"]
                        next_run = datetime.fromtimestamp(next_run_ms / 1000)
                        job["next_run"] = next_run.isoformat()
                    
                    if "lastDurationMs" in state:
                        duration_ms = state["lastDurationMs"]
                        job["last_duration_ms"] = duration_ms
                    
                    # Calculate lag
                    if "lastRunAtMs" in state:
                        now_ms = datetime.now().timestamp() * 1000
                        lag_ms = now_ms - state["lastRunAtMs"]
                        job["lag_seconds"] = int(lag_ms / 1000)
            
            return jobs
        except Exception as e:
            return self._get_from_backup()
    
    def _get_from_backup(self) -> List[Dict[str, Any]]:
        """Fallback: get jobs from backup file."""
        backup_file = self.project_root / "cron_backup" / "jobs.json"
        if not backup_file.exists():
            return []
        
        try:
            data = json.loads(backup_file.read_text())
            jobs = data.get("jobs", [])
            
            for job in jobs:
                if "schedule" in job:
                    schedule = job["schedule"]
                    job["schedule_display"] = self._format_schedule(schedule)
                
                if "state" in job and "nextRunAtMs" in job["state"]:
                    next_run_ms = job["state"]["nextRunAtMs"]
                    next_run = datetime.fromtimestamp(next_run_ms / 1000)
                    job["next_run"] = next_run.isoformat()
            
            return jobs
        except Exception:
            return []
    
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
