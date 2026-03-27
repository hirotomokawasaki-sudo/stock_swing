"""SEC normalizer for transforming SEC payloads to canonical schema.

Supported event types:
- Company submissions (filings)

See SOURCE_MAPPING.md for field mappings.
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord, RawEnvelope
from stock_swing.normalization.normalizer import BaseNormalizer


class SecNormalizer(BaseNormalizer):
    """Normalizer for SEC source data."""

    def normalize(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize SEC raw envelope to canonical records.
        
        Args:
            raw: RawEnvelope from SecClient.
            
        Returns:
            List of CanonicalRecord instances.
        """
        if "submissions" in raw.endpoint:
            return self._normalize_company_submissions(raw)
        elif "companyconcept" in raw.endpoint:
            return self._normalize_company_concept(raw)
        else:
            return self._normalize_generic(raw)

    def _normalize_company_submissions(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize company submissions (filings)."""
        cik = raw.payload.get("cik", raw.request_params.get("cik", "UNKNOWN"))
        tickers = raw.payload.get("tickers", [])
        symbol = tickers[0] if tickers else None
        
        filings = raw.payload.get("filings", {}).get("recent", {})
        accession_numbers = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        forms = filings.get("form", [])
        
        records = []
        for i, accession_no in enumerate(accession_numbers[:10]):  # Limit to 10 most recent
            filing_date = filing_dates[i] if i < len(filing_dates) else None
            form_type = forms[i] if i < len(forms) else None
            
            if not filing_date:
                continue
            
            # Parse event time
            try:
                event_time = datetime.fromisoformat(filing_date).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                event_time = raw.fetched_at
                filing_date = raw.fetched_at.date().isoformat()
            
            record = CanonicalRecord(
                record_id=self._generate_record_id(
                    raw.source,
                    accession_no,
                ),
                schema_version="v1",
                source=raw.source,
                source_type="filing",
                symbol=symbol,
                event_type="filing",
                event_time=event_time,
                as_of=filing_date,
                ingested_at=raw.fetched_at,
                timezone="UTC",
                payload_version=None,
                quality_flags=[],
                payload={
                    "form_type": form_type,
                    "accession_no": accession_no,
                    "filed_at": filing_date,
                    "cik": cik,
                },
            )
            records.append(record)
        
        return records if records else []

    def _normalize_company_concept(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize company concept (XBRL data)."""
        cik = raw.payload.get("cik", raw.request_params.get("cik", "UNKNOWN"))
        tag = raw.payload.get("tag", raw.request_params.get("tag", "UNKNOWN"))
        
        record = CanonicalRecord(
            record_id=self._generate_record_id(
                raw.source,
                cik,
                tag,
                raw.fetched_at.isoformat(),
            ),
            schema_version="v1",
            source=raw.source,
            source_type="filing",
            symbol=None,
            event_type="xbrl_concept",
            event_time=raw.fetched_at,
            as_of=self._extract_as_of_date(raw.fetched_at),
            ingested_at=raw.fetched_at,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload=raw.payload,
        )
        
        return [record]

    def _normalize_generic(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Generic fallback normalization."""
        record = CanonicalRecord(
            record_id=self._generate_record_id(
                raw.source,
                raw.endpoint,
                raw.fetched_at.isoformat(),
            ),
            schema_version="v1",
            source=raw.source,
            source_type="filing",
            symbol=None,
            event_type="generic",
            event_time=raw.fetched_at,
            as_of=self._extract_as_of_date(raw.fetched_at),
            ingested_at=raw.fetched_at,
            timezone="UTC",
            payload_version=None,
            quality_flags=["generic_normalization"],
            payload=raw.payload,
        )
        
        return [record]
