"""Base normalizer for transforming raw provider payloads to canonical schema.

All source normalizers must inherit from BaseNormalizer and implement normalize().
See CANONICAL_SCHEMA.md for canonical record structure.
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from stock_swing.core.types import CanonicalRecord, RawEnvelope


class BaseNormalizer(ABC):
    """Abstract base class for source normalizers.
    
    All normalizers must implement normalize() to transform raw provider
    payloads into CanonicalRecord instances.
    """

    @abstractmethod
    def normalize(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize raw envelope to canonical records.
        
        Args:
            raw: RawEnvelope from source client.
            
        Returns:
            List of CanonicalRecord instances.
            May return multiple records if raw payload contains multiple events.
            
        Raises:
            ValueError: If raw data is malformed or required fields missing.
        """
        raise NotImplementedError

    def _generate_record_id(self, source: str, *components: Any) -> str:
        """Generate deterministic record ID from source and components.
        
        Args:
            source: Source name.
            *components: Components to hash (symbol, timestamp, etc.).
            
        Returns:
            Deterministic UUID based on content hash.
        """
        content = f"{source}:{':'.join(str(c) for c in components)}"
        hash_hex = hashlib.sha256(content.encode()).hexdigest()
        # Create UUID from first 32 hex chars
        return str(uuid.UUID(hash_hex[:32]))

    def _normalize_timestamp(self, timestamp: Any) -> datetime:
        """Normalize timestamp to UTC datetime.
        
        Args:
            timestamp: Timestamp as string, int (unix), or datetime.
            
        Returns:
            UTC datetime object.
        """
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                return timestamp.replace(tzinfo=timezone.utc)
            return timestamp.astimezone(timezone.utc)
        
        if isinstance(timestamp, str):
            # Try parsing ISO8601
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                return dt.astimezone(timezone.utc)
            except ValueError:
                pass
        
        if isinstance(timestamp, (int, float)):
            # Unix timestamp
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        
        # Fallback: use current time and add quality flag
        return datetime.now(timezone.utc)

    def _extract_as_of_date(self, event_time: datetime) -> str:
        """Extract business date from event timestamp.
        
        Args:
            event_time: Event timestamp.
            
        Returns:
            Date string in YYYY-MM-DD format.
        """
        return event_time.date().isoformat()
