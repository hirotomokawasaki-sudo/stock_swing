"""Dashboard service for aggregating system data."""

import json
from pathlib import Path
from typing import Dict, Any

from console.adapters.cron_adapter import CronAdapter
from console.adapters.data_adapter import DataAdapter
from console.adapters.system_adapter import SystemAdapter
from console.utils.time_utils import now_iso


class DashboardService:
    """Aggregates data from multiple adapters for dashboard display."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.cron_adapter = CronAdapter(project_root)
        self.data_adapter = DataAdapter(project_root)
        self.system_adapter = SystemAdapter(project_root)
    
    def get_dashboard(self) -> Dict[str, Any]:
        """Get complete dashboard data."""
        return {
            "time": now_iso(),
            "overview": self.get_overview(),
            "cron_jobs": self.get_cron_jobs(),
            "data_status": self.get_data_status(),
            "system": self.get_system_status(),
        }
    
    def get_overview(self) -> Dict[str, Any]:
        """Get overview summary."""
        cron_jobs = self.cron_adapter.get_jobs()
        data_counts = self.data_adapter.get_counts()
        system_health = self.system_adapter.get_health()
        
        return {
            "time": now_iso(),
            "health_score": system_health.get("score", 0),
            "health_status": system_health.get("status", "unknown"),
            "cron_jobs_active": len([j for j in cron_jobs if j.get("enabled")]),
            "cron_jobs_total": len(cron_jobs),
            "data_counts": data_counts,
            "runtime_mode": system_health.get("runtime_mode", "unknown"),
        }
    
    def get_cron_jobs(self) -> Dict[str, Any]:
        """Get cron jobs information."""
        jobs = self.cron_adapter.get_jobs()
        return {
            "time": now_iso(),
            "jobs": jobs,
            "total": len(jobs),
            "active": len([j for j in jobs if j.get("enabled")]),
        }
    
    def get_data_status(self) -> Dict[str, Any]:
        """Get data status."""
        return {
            "time": now_iso(),
            "counts": self.data_adapter.get_counts(),
            "freshness": self.data_adapter.get_freshness(),
        }
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get system status."""
        return {
            "time": now_iso(),
            **self.system_adapter.get_health(),
        }
