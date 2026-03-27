"""Project-root-relative path resolution with stage validation.

This module ensures that all data paths follow the approved directory structure
and that only valid stage names are used. See MUSTREAD_NAVIGATION.md for details.
"""

from __future__ import annotations

from pathlib import Path


class PathManager:
    """Manages project-root-relative path resolution for data and config files.
    
    Attributes:
        project_root: Resolved absolute path to the project root.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize PathManager with a project root.
        
        Args:
            project_root: Path to the project root directory.
                Will be resolved to an absolute path.
        """
        self.project_root = project_root.resolve()

    def data_stage(self, stage: str) -> Path:
        """Return the path to a data stage directory, creating it if needed.
        
        Args:
            stage: Name of the data stage. Must be one of:
                {"raw", "normalized", "features", "signals", "decisions", "audits", "archive"}.
                
        Returns:
            Absolute path to the stage directory.
            
        Raises:
            ValueError: If the stage name is not in the allowed set (fail closed).
            
        Side effects:
            Creates the stage directory if it does not exist.
        """
        allowed = {"raw", "normalized", "features", "signals", "decisions", "audits", "archive"}
        if stage not in allowed:
            raise ValueError(f"unsupported data stage: {stage}")
        path = self.project_root / "data" / stage
        path.mkdir(parents=True, exist_ok=True)
        return path

    def source_raw(self, source: str) -> Path:
        """Return the path to a source-specific raw data directory, creating it if needed.
        
        Args:
            source: Source name (e.g., "finnhub", "fred", "sec", "broker").
            
        Returns:
            Absolute path to data/raw/{source}/.
            
        Side effects:
            Creates the directory if it does not exist.
        """
        path = self.data_stage("raw") / source
        path.mkdir(parents=True, exist_ok=True)
        return path

    def config_file(self, *parts: str) -> Path:
        """Resolve a path under the config/ directory.
        
        Args:
            *parts: Path components relative to config/ (e.g., "runtime", "current_mode.yaml").
            
        Returns:
            Absolute path to the config file.
            
        Note:
            This method does not create the file or validate its existence.
        """
        return self.project_root.joinpath("config", *parts)
