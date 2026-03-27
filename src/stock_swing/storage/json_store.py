"""Legacy JSON file store implementation.

This module provides a simple JSON file store that implements the abstract
storage interfaces. For stage-aware storage with path safety and raw immutability,
use StageStore instead.

Note: This implementation does not enforce stage separation or raw immutability.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from stock_swing.core.types import CanonicalRecord, DecisionRecord, RawEnvelope
from stock_swing.storage.interfaces import DecisionStore, NormalizedStore, RawStore


class JsonFileStore(RawStore, NormalizedStore, DecisionStore):
    """Simple JSON file store without stage enforcement.
    
    This class provides basic JSON serialization for raw, normalized, and decision data.
    It does not enforce stage separation or raw immutability.
    
    For production use, prefer StageStore which provides:
    - Stage-aware path resolution
    - Raw data immutability
    - Consistent path discipline
    """

    def write(self, obj, destination: Path) -> Path:
        """Write an object to a JSON file.
        
        Args:
            obj: Object to write (must be a dataclass).
            destination: Target file path.
            
        Returns:
            Path to the written file.
            
        Note:
            This method creates parent directories as needed and overwrites existing files.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(obj)
        destination.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
        return destination
