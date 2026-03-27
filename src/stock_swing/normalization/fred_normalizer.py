"""FRED normalizer for transforming FRED payloads to canonical schema.

Supported event types:
- Macro series observations

See SOURCE_MAPPING.md for field mappings.
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord, RawEnvelope
from stock_swing.normalization.normalizer import BaseNormalizer


class FredNormalizer(BaseNormalizer):
    """Normalizer for FRED source data."""

    def normalize(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize FRED raw envelope to canonical records.
        
        Args:
            raw: RawEnvelope from FredClient.
            
        Returns:
            List of CanonicalRecord instances (one per observation).
        """
        if "observations" in raw.endpoint or "observations" in raw.payload:
            return self._normalize_series_observations(raw)
        else:
            # Series info or other metadata
            return self._normalize_series_info(raw)

    def _normalize_series_observations(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize FRED series observations."""
        observations = raw.payload.get("observations", [])
        series_id = raw.request_params.get("series_id", "UNKNOWN")
        
        records = []
        for obs in observations:
            date = obs.get("date")
            value = obs.get("value")
            
            # Parse event time from observation date
            try:
                event_time = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                event_time = raw.fetched_at
                date = raw.fetched_at.date().isoformat()
            
            record = CanonicalRecord(
                record_id=self._generate_record_id(
                    raw.source,
                    series_id,
                    date,
                ),
                schema_version="v1",
                source=raw.source,
                source_type="macro",
                symbol=None,  # Macro data has no symbol
                event_type="macro_release",
                event_time=event_time,
                as_of=date,
                ingested_at=raw.fetched_at,
                timezone="UTC",
                payload_version=None,
                quality_flags=[],
                payload={
                    "series_id": series_id,
                    "value": float(value) if value and value != "." else None,
                    "release_name": None,  # Not in observations
                    "period": date,
                    "units": None,  # Not in observations
                    "realtime_start": obs.get("realtime_start"),
                    "realtime_end": obs.get("realtime_end"),
                },
            )
            records.append(record)
        
        return records if records else []

    def _normalize_series_info(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize FRED series metadata."""
        seriess = raw.payload.get("seriess", [])
        
        if not seriess:
            return []
        
        records = []
        for series in seriess:
            series_id = series.get("id", raw.request_params.get("series_id", "UNKNOWN"))
            
            record = CanonicalRecord(
                record_id=self._generate_record_id(
                    raw.source,
                    series_id,
                    "metadata",
                    raw.fetched_at.isoformat(),
                ),
                schema_version="v1",
                source=raw.source,
                source_type="macro",
                symbol=None,
                event_type="series_metadata",
                event_time=raw.fetched_at,
                as_of=self._extract_as_of_date(raw.fetched_at),
                ingested_at=raw.fetched_at,
                timezone="UTC",
                payload_version=None,
                quality_flags=[],
                payload={
                    "series_id": series_id,
                    "title": series.get("title"),
                    "units": series.get("units"),
                    "frequency": series.get("frequency"),
                    "observation_start": series.get("observation_start"),
                    "observation_end": series.get("observation_end"),
                },
            )
            records.append(record)
        
        return records
