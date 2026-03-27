"""Stage-aware storage layer for controlled data persistence.

This module provides stage-specific storage operations that enforce:
- Stage separation (raw, normalized, features, signals, decisions, audits)
- Path safety (all writes go through approved stage paths)
- Raw immutability (raw writes fail if destination exists, unless explicitly configured)

See MUSTREAD_NAVIGATION.md for stage definitions.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from stock_swing.core.path_manager import PathManager


class RawOverwriteError(RuntimeError):
    """Raised when attempting to overwrite existing raw data without explicit permission.
    
    Raw data must be immutable by default. See MUSTREAD_NAVIGATION.md.
    """

    pass


class StageStore:
    """Stage-aware storage for structured data persistence.
    
    This class enforces stage separation and path discipline for all data writes.
    
    Attributes:
        path_manager: PathManager instance for project-root-relative paths.
        allow_raw_overwrite: If False (default), raw writes fail if destination exists.
    """

    def __init__(self, path_manager: PathManager, allow_raw_overwrite: bool = False) -> None:
        """Initialize StageStore.
        
        Args:
            path_manager: PathManager for resolving stage paths.
            allow_raw_overwrite: If True, allow overwriting existing raw files.
                Default False enforces raw immutability.
        """
        self.path_manager = path_manager
        self.allow_raw_overwrite = allow_raw_overwrite

    def write_raw(
        self,
        source: str,
        filename: str,
        data: dict[str, Any] | Any,
    ) -> Path:
        """Write raw source data to data/raw/{source}/{filename}.
        
        Args:
            source: Source name (e.g., "finnhub", "fred", "sec", "broker").
            filename: Target filename (e.g., "aapl_2026-03-06_fundamentals.json").
            data: Data to write (will be serialized to JSON).
                If data is a dataclass, it will be converted via asdict().
                
        Returns:
            Path to the written file.
            
        Raises:
            RawOverwriteError: If destination exists and allow_raw_overwrite is False.
            
        Note:
            Raw data is immutable by default. Overwriting requires explicit configuration.
        """
        destination = self.path_manager.source_raw(source) / filename

        if destination.exists() and not self.allow_raw_overwrite:
            raise RawOverwriteError(
                f"raw file already exists: {destination.relative_to(self.path_manager.project_root)}"
            )

        return self._write_json(destination, data)

    def write_normalized(self, filename: str, data: dict[str, Any] | Any) -> Path:
        """Write normalized canonical data to data/normalized/{filename}.
        
        Args:
            filename: Target filename (e.g., "aapl_2026-03-06_canonical.json").
            data: Canonical data to write.
                
        Returns:
            Path to the written file.
        """
        destination = self.path_manager.data_stage("normalized") / filename
        return self._write_json(destination, data)

    def write_features(self, filename: str, data: dict[str, Any] | Any) -> Path:
        """Write feature data to data/features/{filename}.
        
        Args:
            filename: Target filename (e.g., "aapl_2026-03-06_features.json").
            data: Feature data to write.
                
        Returns:
            Path to the written file.
        """
        destination = self.path_manager.data_stage("features") / filename
        return self._write_json(destination, data)

    def write_signals(self, filename: str, data: dict[str, Any] | Any) -> Path:
        """Write strategy signal data to data/signals/{filename}.
        
        Args:
            filename: Target filename (e.g., "aapl_2026-03-06_swing_signal.json").
            data: Signal data to write.
                
        Returns:
            Path to the written file.
        """
        destination = self.path_manager.data_stage("signals") / filename
        return self._write_json(destination, data)

    def write_decisions(self, filename: str, data: dict[str, Any] | Any) -> Path:
        """Write decision data to data/decisions/{filename}.
        
        Args:
            filename: Target filename (e.g., "aapl_2026-03-06_decision.json").
            data: Decision data to write.
                
        Returns:
            Path to the written file.
        """
        destination = self.path_manager.data_stage("decisions") / filename
        return self._write_json(destination, data)

    def write_audit(self, filename: str, data: dict[str, Any] | Any) -> Path:
        """Write audit/event data to data/audits/{filename}.
        
        Args:
            filename: Target filename (e.g., "2026-03-06_execution_audit.json").
            data: Audit data to write.
                
        Returns:
            Path to the written file.
        """
        destination = self.path_manager.data_stage("audits") / filename
        return self._write_json(destination, data)

    def _write_json(self, destination: Path, data: dict[str, Any] | Any) -> Path:
        """Internal helper to write JSON with parent directory creation.
        
        Args:
            destination: Target file path.
            data: Data to serialize. Dataclasses are converted via asdict().
            
        Returns:
            Path to the written file.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)

        # Convert dataclasses to dict
        if hasattr(data, "__dataclass_fields__"):
            payload = asdict(data)
        elif isinstance(data, dict):
            payload = data
        else:
            # Fallback: try to serialize directly
            payload = data

        # Write with datetime serialization support
        content = json.dumps(payload, default=self._json_serializer, indent=2)
        destination.write_text(content, encoding="utf-8")
        return destination

    @staticmethod
    def _json_serializer(obj: Any) -> str:
        """Custom JSON serializer for datetime and other non-JSON types.
        
        Args:
            obj: Object to serialize.
            
        Returns:
            String representation of the object.
        """
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)
