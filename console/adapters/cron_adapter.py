"""Adapter for cron jobs data."""

import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime


class CronAdapter:
    """Read cron jobs from backup file."""
    
    def __init__(self, project_root: Path):
        self.cron_backup = project_root / "cron_backup" / "jobs.json"
    
    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get all cron jobs."""
        if not self.cron_backup.exists():
            return []
        
        try:
            data = json.loads(self.cron_backup.read_text())
            jobs = data.get("jobs", [])
            
            # Enrich with readable info
            for job in jobs:
                if "schedule" in job:
                    schedule = job["schedule"]
                    job["schedule_display"] = self._format_schedule(schedule)
                
                if "state" in job and "nextRunAtMs" in job["state"]:
                    next_run_ms = job["state"]["nextRunAtMs"]
                    next_run = datetime.fromtimestamp(next_run_ms / 1000)
                    job["next_run"] = next_run.isoformat()
            
            return jobs
        except Exception as e:
            return [{"error": str(e)}]
    
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
