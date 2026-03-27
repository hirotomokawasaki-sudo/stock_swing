"""Runtime mode reading and validation with fail-closed behavior.

This module enforces that runtime mode is always valid and explicit.
If the mode is missing, invalid, or inconsistent, execution must be denied.

See RUNTIME_MODES.md for detailed mode definitions and constraints.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from .config_loader import ConfigLoader


ALLOWED_RUNTIME_MODES = {"research", "paper", "live_guarded", "live"}
"""Set of allowed runtime modes. Must match RUNTIME_MODES.md."""


class RuntimeMode(Enum):
    """Runtime mode enumeration.
    
    Defines the available runtime modes for the system.
    """
    
    RESEARCH = "research"
    PAPER = "paper"
    LIVE_GUARDED = "live_guarded"
    LIVE = "live"


class RuntimeModeError(RuntimeError):
    """Raised when runtime mode is invalid, missing, or inconsistent.
    
    This error indicates a fail-closed condition: execution should be denied.
    """

    pass


def read_runtime_mode(project_root: Path) -> str:
    """Read and validate runtime mode from config/runtime/current_mode.yaml.
    
    Args:
        project_root: Absolute path to the project root directory.
        
    Returns:
        The validated runtime mode string.
        
    Raises:
        RuntimeModeError: If the mode is invalid or missing (fail closed).
        FileNotFoundError: If the config file does not exist (fail closed).
        
    Behavior:
        - Missing mode key → fail closed with RuntimeModeError
        - Invalid mode value → fail closed with RuntimeModeError
        - Missing config file → fail closed with FileNotFoundError
    """
    config = ConfigLoader(project_root).load_yaml("config/runtime/current_mode.yaml")
    mode = config.get("mode")
    if mode not in ALLOWED_RUNTIME_MODES:
        raise RuntimeModeError(f"invalid or missing runtime mode: {mode!r}")
    return mode
