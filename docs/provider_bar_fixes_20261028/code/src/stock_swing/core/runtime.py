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


def read_ledger_quality_gate(project_root: Path | None = None) -> dict:
    """Read the ledger_quality_gate block from config/runtime/current_mode.yaml.

    Returns the ``ledger_quality_gate`` dict as written in the YAML.  Never raises;
    on any error returns a safe fallback with ``current_status="UNKNOWN"`` and
    ``enforce_invalid_ledger_blocks_live_ready=True`` (fail-closed).
    """
    if project_root is None:
        project_root = Path(__file__).parents[3]

    fallback: dict = {
        "current_status": "UNKNOWN",
        "enforce_invalid_ledger_blocks_live_ready": True,
    }
    try:
        config = ConfigLoader(project_root).load_yaml("config/runtime/current_mode.yaml")
        gate = config.get("ledger_quality_gate")
        if not isinstance(gate, dict):
            return fallback
        return gate
    except Exception:
        return fallback


def read_circuit_breaker_config(project_root: Path | None = None) -> dict:
    """Read the circuit_breaker block from config/runtime/current_mode.yaml.

    Returns the ``circuit_breaker`` config dict.  Never raises; returns safe
    defaults (``require_clean_run_after_manual_clear=True``) on any error.
    """
    if project_root is None:
        project_root = Path(__file__).parents[3]

    fallback: dict = {"require_clean_run_after_manual_clear": True}
    try:
        config = ConfigLoader(project_root).load_yaml("config/runtime/current_mode.yaml")
        cb_cfg = config.get("circuit_breaker")
        if not isinstance(cb_cfg, dict):
            return fallback
        return cb_cfg
    except Exception:
        return fallback


def read_runtime_mode(project_root: Path | None = None) -> str:
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
    if project_root is None:
        project_root = Path(__file__).parents[3]

    config = ConfigLoader(project_root).load_yaml("config/runtime/current_mode.yaml")
    mode = config.get("mode")
    if mode not in ALLOWED_RUNTIME_MODES:
        raise RuntimeModeError(f"invalid or missing runtime mode: {mode!r}")
    return mode
