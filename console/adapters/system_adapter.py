"""Adapter for system health status."""

import yaml
from pathlib import Path
from typing import Dict, Any


class SystemAdapter:
    """Read system health and configuration."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.runtime_config = project_root / "config" / "runtime" / "current_mode.yaml"
        self.env_file = project_root / ".env"
    
    def get_health(self) -> Dict[str, Any]:
        """Get system health status."""
        health = {
            "runtime_mode": self._get_runtime_mode(),
            "api_keys_configured": self._check_api_keys(),
            "venv_exists": (self.project_root / "venv").exists(),
            "score": 0,
            "status": "unknown",
        }
        
        # Calculate health score
        score = 0
        if health["runtime_mode"] in ["research", "paper"]:
            score += 40
        if health["api_keys_configured"]:
            score += 30
        if health["venv_exists"]:
            score += 30
        
        health["score"] = score
        
        if score >= 80:
            health["status"] = "healthy"
        elif score >= 50:
            health["status"] = "degraded"
        else:
            health["status"] = "unhealthy"
        
        return health
    
    def _get_runtime_mode(self) -> str:
        """Get current runtime mode."""
        if not self.runtime_config.exists():
            return "unknown"
        
        try:
            data = yaml.safe_load(self.runtime_config.read_text())
            return data.get("mode", "unknown")
        except Exception:
            return "error"
    
    def _check_api_keys(self) -> bool:
        """Check if API keys are configured."""
        if not self.env_file.exists():
            return False
        
        content = self.env_file.read_text()
        required_keys = ["FINNHUB_API_KEY", "FRED_API_KEY"]
        
        for key in required_keys:
            if f"{key}=your_key_here" in content or f"{key}=" not in content:
                return False
        
        return True
