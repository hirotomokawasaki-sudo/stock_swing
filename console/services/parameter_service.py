"""Parameter tuning service with safety validation."""
from pathlib import Path
from typing import Dict, Any
import json
from datetime import datetime


class ParameterService:
    """Manage trading parameters with safety checks."""
    
    # Safe ranges for each parameter
    PARAMETERS = {
        "max_position_size": {
            "current": 400,
            "min": 100,
            "max": 1000,
            "recommended": 400,
            "unit": "USD",
            "description": "Maximum position size per symbol",
            "risk_level": "high",
        },
        "min_signal_strength": {
            "current": 0.50,
            "min": 0.30,
            "max": 0.80,
            "recommended": 0.50,
            "unit": "ratio",
            "description": "Minimum signal strength to act on",
            "risk_level": "medium",
        },
        "min_confidence": {
            "current": 0.40,
            "min": 0.30,
            "max": 0.80,
            "recommended": 0.40,
            "unit": "ratio",
            "description": "Minimum confidence threshold",
            "risk_level": "medium",
        },
        "symbol_position_limit_pct": {
            "current": 0.10,
            "min": 0.05,
            "max": 0.20,
            "recommended": 0.10,
            "unit": "percentage",
            "description": "Maximum position per symbol (% of equity)",
            "risk_level": "high",
        },
    }
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.changes_log = project_root / "data" / "config" / "parameter_changes.log"
        self.changes_log.parent.mkdir(parents=True, exist_ok=True)
    
    def get_all_parameters(self) -> Dict[str, Any]:
        """Get all parameters and their safe ranges."""
        return {
            "parameters": self.PARAMETERS,
            "timestamp": datetime.now().isoformat(),
        }
    
    def get_parameter(self, name: str) -> Dict[str, Any]:
        """Get a specific parameter."""
        if name not in self.PARAMETERS:
            raise ValueError(f"Unknown parameter: {name}")
        return self.PARAMETERS[name]
    
    def validate_value(self, name: str, value: float) -> Dict[str, Any]:
        """Validate a parameter value without applying it."""
        if name not in self.PARAMETERS:
            return {"valid": False, "error": f"Unknown parameter: {name}"}
        
        param = self.PARAMETERS[name]
        warnings = []
        
        # Type check
        if not isinstance(value, (int, float)):
            return {"valid": False, "error": "Value must be numeric"}
        
        # Range check
        if value < param["min"]:
            return {
                "valid": False,
                "error": f"Too low (min: {param['min']} {param['unit']})",
            }
        
        if value > param["max"]:
            return {
                "valid": False,
                "error": f"Too high (max: {param['max']} {param['unit']})",
            }
        
        # Warning checks
        if value < param["recommended"] * 0.5:
            warnings.append("⚠️  Much lower than recommended")
        
        if value > param["recommended"] * 2:
            warnings.append("⚠️  Much higher than recommended")
        
        # Estimate impact
        impact = self._estimate_impact(name, value, param["current"])
        
        return {
            "valid": True,
            "warnings": warnings,
            "impact": impact,
            "requires_confirmation": len(warnings) > 0 or param["risk_level"] == "high",
        }
    
    def _estimate_impact(self, name: str, new_value: float, old_value: float) -> str:
        """Estimate the impact of a parameter change."""
        if name == "max_position_size":
            if new_value > old_value:
                return f"Larger positions allowed (${old_value} → ${new_value}). More capital at risk per symbol."
            else:
                return f"Smaller positions only (${old_value} → ${new_value}). Reduced risk but fewer opportunities."
        
        elif name == "symbol_position_limit_pct":
            old_pct = old_value * 100
            new_pct = new_value * 100
            if new_value > old_value:
                return f"Higher concentration allowed ({old_pct:.0f}% → {new_pct:.0f}%). More risk per symbol."
            else:
                return f"Lower concentration ({old_pct:.0f}% → {new_pct:.0f}%). Better diversification."
        
        elif name in ["min_signal_strength", "min_confidence"]:
            if new_value > old_value:
                return f"Higher threshold ({old_value} → {new_value}). Fewer signals, higher quality."
            else:
                return f"Lower threshold ({old_value} → {new_value}). More signals, lower quality."
        
        return "Impact analysis not available"
    
    def apply_parameter(self, name: str, value: float, confirmed: bool = False, user: str = "admin") -> Dict[str, Any]:
        """Apply a parameter change with safety checks."""
        # Validate first
        validation = self.validate_value(name, value)
        
        if not validation["valid"]:
            raise ValueError(f"Invalid value: {validation['error']}")
        
        # Check confirmation requirement
        if validation["requires_confirmation"] and not confirmed:
            return {
                "success": False,
                "error": "Confirmation required",
                "validation": validation,
            }
        
        # Get old value
        param = self.PARAMETERS[name]
        old_value = param["current"]
        
        # Apply change (in-memory for now, will write to config file)
        self.PARAMETERS[name]["current"] = value
        
        # Log the change
        self.log_change(name, old_value, value, user)
        
        # Write to config file
        self._write_config(name, value)
        
        return {
            "success": True,
            "parameter": name,
            "old_value": old_value,
            "new_value": value,
            "impact": validation["impact"],
            "timestamp": datetime.now().isoformat(),
        }
    
    def _write_config(self, name: str, value: float):
        """Write parameter to config file."""
        config_file = self.project_root / "data" / "config" / "parameters.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing config
        if config_file.exists():
            config = json.loads(config_file.read_text())
        else:
            config = {}
        
        # Update parameter
        config[name] = value
        
        # Write back
        config_file.write_text(json.dumps(config, indent=2))
    
    def rollback_last_change(self, name: str) -> Dict[str, Any]:
        """Rollback the last change to a parameter."""
        if not self.changes_log.exists():
            raise ValueError("No change history found")
        
        # Read change log
        lines = self.changes_log.read_text().splitlines()
        if not lines:
            raise ValueError("No changes to rollback")
        
        # Find last change for this parameter
        last_change = None
        for line in reversed(lines):
            if f"| {name} |" in line:
                last_change = line
                break
        
        if not last_change:
            raise ValueError(f"No changes found for parameter: {name}")
        
        # Parse the old value
        parts = last_change.split("|")
        change_part = parts[2].strip()  # "old → new"
        old_value = float(change_part.split("→")[0].strip().replace("$", ""))
        
        # Apply rollback
        return self.apply_parameter(name, old_value, confirmed=True, user="system_rollback")
    
    def log_change(self, name: str, old_value: float, new_value: float, user: str = "admin"):
        """Log a parameter change."""
        timestamp = datetime.now().isoformat()
        log_entry = f"{timestamp} | {name} | {old_value} → {new_value} | user: {user}\n"
        
        with open(self.changes_log, 'a') as f:
            f.write(log_entry)
