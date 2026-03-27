"""Configuration loading from project-relative YAML files.

This module provides safe YAML loading with explicit validation.
All paths are resolved relative to the project root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigLoader:
    """Loads configuration files relative to the project root.
    
    Attributes:
        project_root: Resolved absolute path to the project root.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize ConfigLoader with a project root.
        
        Args:
            project_root: Path to the project root directory.
                Will be resolved to an absolute path.
        """
        self.project_root = project_root.resolve()

    def load_yaml(self, relative_path: str) -> dict[str, Any]:
        """Load a YAML file and return it as a dictionary.
        
        Args:
            relative_path: Path relative to project_root (e.g., "config/runtime/current_mode.yaml").
            
        Returns:
            Dictionary parsed from YAML. Empty dict if file is empty.
            
        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the YAML content is not a mapping (dict).
            yaml.YAMLError: If YAML parsing fails.
        """
        path = self.project_root / relative_path
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"expected mapping in {relative_path}")
        return data
