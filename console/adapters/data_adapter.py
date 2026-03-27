"""Adapter for data storage status."""

from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timedelta


class DataAdapter:
    """Read data storage status."""
    
    def __init__(self, project_root: Path):
        self.data_dir = project_root / "data"
    
    def get_counts(self) -> Dict[str, int]:
        """Get file counts for each data stage."""
        counts = {}
        
        stages = ["raw", "normalized", "features", "signals", "decisions", "audits"]
        for stage in stages:
            stage_dir = self.data_dir / stage
            if stage_dir.exists():
                counts[stage] = len(list(stage_dir.glob("**/*.json")))
            else:
                counts[stage] = 0
        
        return counts
    
    def get_freshness(self) -> Dict[str, Any]:
        """Check data freshness."""
        freshness = {}
        now = datetime.now()
        
        stages = ["raw", "normalized", "features", "signals", "decisions"]
        for stage in stages:
            stage_dir = self.data_dir / stage
            if not stage_dir.exists():
                freshness[stage] = {"status": "missing", "age_hours": None}
                continue
            
            files = list(stage_dir.glob("**/*.json"))
            if not files:
                freshness[stage] = {"status": "empty", "age_hours": None}
                continue
            
            # Get newest file
            newest = max(files, key=lambda f: f.stat().st_mtime)
            mtime = datetime.fromtimestamp(newest.stat().st_mtime)
            age = now - mtime
            age_hours = age.total_seconds() / 3600
            
            if age_hours < 6:
                status = "fresh"
            elif age_hours < 24:
                status = "aging"
            else:
                status = "stale"
            
            freshness[stage] = {
                "status": status,
                "age_hours": round(age_hours, 1),
                "newest_file": newest.name,
            }
        
        return freshness
