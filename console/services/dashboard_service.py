"""Dashboard service for aggregating system data."""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List

from console.adapters.cron_adapter import CronAdapter
from console.adapters.data_adapter import DataAdapter
from console.adapters.system_adapter import SystemAdapter
from console.utils.time_utils import now_iso

# P&L tracker
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
try:
    from stock_swing.tracking.pnl_tracker import PnLTracker
    _HAS_TRACKER = True
except Exception:
    _HAS_TRACKER = False


class DashboardService:
    """Aggregates data from multiple adapters for dashboard display."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.cron_adapter = CronAdapter(project_root)
        self.data_adapter = DataAdapter(project_root)
        self.system_adapter = SystemAdapter(project_root)
        self._tracker = PnLTracker(project_root) if _HAS_TRACKER else None

    def get_dashboard(self) -> Dict[str, Any]:
        return {
            "time": now_iso(),
            "overview": self.get_overview(),
            "cron_jobs": self.get_cron_jobs(),
            "data_status": self.get_data_status(),
            "system": self.get_system_status(),
            "trading": self.get_trading(),
            "positions": self.get_positions(),
            "logs": self.get_logs(),
        }

    def get_overview(self) -> Dict[str, Any]:
        cron_jobs = self.cron_adapter.get_jobs()
        data_counts = self.data_adapter.get_counts()
        system_health = self.system_adapter.get_health()
        trading = self.get_trading()
        return {
            "time": now_iso(),
            "health_score": system_health.get("score", 0),
            "health_status": system_health.get("status", "unknown"),
            "cron_jobs_active": len([j for j in cron_jobs if j.get("enabled")]),
            "cron_jobs_total": len(cron_jobs),
            "data_counts": data_counts,
            "runtime_mode": system_health.get("runtime_mode", "unknown"),
            "trading_summary": trading.get("summary", {}),
        }

    def get_cron_jobs(self) -> Dict[str, Any]:
        jobs = self.cron_adapter.get_jobs()
        return {
            "time": now_iso(),
            "jobs": jobs,
            "total": len(jobs),
            "active": len([j for j in jobs if j.get("enabled")]),
        }

    def get_data_status(self) -> Dict[str, Any]:
        return {
            "time": now_iso(),
            "counts": self.data_adapter.get_counts(),
            "freshness": self.data_adapter.get_freshness(),
        }

    def get_system_status(self) -> Dict[str, Any]:
        return {
            "time": now_iso(),
            **self.system_adapter.get_health(),
        }

    def get_trading(self) -> Dict[str, Any]:
        """Get trading performance data from PnL tracker."""
        if not self._tracker:
            return {"available": False, "error": "PnLTracker not available"}

        try:
            # Reload state fresh
            self._tracker.state = self._tracker._load_state()
            summary = self._tracker.get_summary()
            recent = self._tracker.get_recent_trades(10)
            daily_snapshots = list(self._tracker.state.daily_snapshots)

            return {
                "available": True,
                "time": now_iso(),
                "summary": summary,
                "recent_trades": recent,
                "daily_snapshots": daily_snapshots[-30:],  # last 30 days
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    def get_positions(self) -> Dict[str, Any]:
        """Get open positions from PnL tracker."""
        if not self._tracker:
            return {"available": False, "positions": []}

        try:
            self._tracker.state = self._tracker._load_state()
            positions = self._tracker.get_open_positions()
            return {
                "available": True,
                "time": now_iso(),
                "positions": positions,
                "count": len(positions),
            }
        except Exception as e:
            return {"available": False, "positions": [], "error": str(e)}

    def get_logs(self, max_lines: int = 200) -> Dict[str, Any]:
        """Get recent audit log lines."""
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        log_path = self.project_root / "data" / "audits" / f"paper_demo_{today}.log"

        lines = []
        if log_path.exists():
            try:
                raw = log_path.read_text(encoding="utf-8").splitlines()
                lines = raw[-max_lines:]
            except Exception:
                pass

        # Also check daily report
        report_path = self.project_root / "data" / "audits" / f"daily_report_{datetime.now().strftime('%Y-%m-%d')}.txt"
        report_text = ""
        if report_path.exists():
            try:
                report_text = report_path.read_text(encoding="utf-8")
            except Exception:
                pass

        return {
            "time": now_iso(),
            "log_file": str(log_path),
            "lines": lines,
            "line_count": len(lines),
            "daily_report": report_text,
        }
