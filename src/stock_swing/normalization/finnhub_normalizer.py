"""Finnhub normalizer for transforming Finnhub payloads to canonical schema.

Supported event types:
- Basic financials (stock/metric)
- Earnings calendar
- Insider transactions
- Filing sentiment

See SOURCE_MAPPING.md for field mappings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stock_swing.core.types import CanonicalRecord, RawEnvelope
from stock_swing.normalization.normalizer import BaseNormalizer


class FinnhubNormalizer(BaseNormalizer):
    """Normalizer for Finnhub source data."""

    def normalize(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize Finnhub raw envelope to canonical records.
        
        Args:
            raw: RawEnvelope from FinnhubClient.
            
        Returns:
            List of CanonicalRecord instances.
        """
        endpoint = raw.endpoint
        
        if "stock/metric" in endpoint or "metric" in endpoint:
            return self._normalize_basic_financials(raw)
        elif "earnings" in endpoint or "calendar" in endpoint:
            return self._normalize_earnings_calendar(raw)
        elif "insider" in endpoint:
            return self._normalize_insider_transactions(raw)
        elif "sentiment" in endpoint or "filing" in endpoint:
            return self._normalize_filing_sentiment(raw)
        else:
            # Fallback: generic normalization
            return self._normalize_generic(raw)

    def _normalize_basic_financials(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize basic financials (stock/metric)."""
        symbol = raw.request_params.get("symbol", "UNKNOWN")
        
        record = CanonicalRecord(
            record_id=self._generate_record_id(
                raw.source,
                symbol,
                "basic_financials",
                raw.fetched_at.isoformat(),
            ),
            schema_version="v1",
            source=raw.source,
            source_type="fundamentals",
            symbol=symbol,
            event_type="basic_financials",
            event_time=raw.fetched_at,
            as_of=self._extract_as_of_date(raw.fetched_at),
            ingested_at=raw.fetched_at,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload=raw.payload,
        )
        
        return [record]

    def _normalize_earnings_calendar(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize earnings calendar."""
        calendar_data = raw.payload.get("earningsCalendar", [])
        
        records = []
        for item in calendar_data:
            symbol = item.get("symbol", raw.request_params.get("symbol", "UNKNOWN"))
            date = item.get("date", raw.fetched_at.date().isoformat())
            
            # Parse event time from date
            try:
                event_time = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                event_time = raw.fetched_at
            
            record = CanonicalRecord(
                record_id=self._generate_record_id(
                    raw.source,
                    symbol,
                    "earnings_calendar",
                    date,
                ),
                schema_version="v1",
                source=raw.source,
                source_type="fundamentals",
                symbol=symbol,
                event_type="earnings_calendar",
                event_time=event_time,
                as_of=date,
                ingested_at=raw.fetched_at,
                timezone="UTC",
                payload_version=None,
                quality_flags=[],
                payload={
                    "estimate_eps": item.get("epsEstimate"),
                    "estimate_revenue": item.get("revenueEstimate"),
                    "fiscal_period": f"Q{item.get('quarter')} {item.get('year')}",
                    "hour": item.get("hour"),
                },
            )
            records.append(record)
        
        return records if records else [self._normalize_generic(raw)[0]]

    def _normalize_insider_transactions(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize insider transactions."""
        transactions = raw.payload.get("data", [])
        
        records = []
        for txn in transactions:
            symbol = txn.get("symbol", raw.request_params.get("symbol", "UNKNOWN"))
            filing_date = txn.get("filingDate", raw.fetched_at.date().isoformat())
            
            # Parse event time from filing date
            try:
                event_time = datetime.fromisoformat(filing_date).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                event_time = raw.fetched_at
            
            record = CanonicalRecord(
                record_id=self._generate_record_id(
                    raw.source,
                    symbol,
                    "insider_transaction",
                    filing_date,
                    txn.get("name", ""),
                ),
                schema_version="v1",
                source=raw.source,
                source_type="fundamentals",
                symbol=symbol,
                event_type="insider_transaction",
                event_time=event_time,
                as_of=filing_date,
                ingested_at=raw.fetched_at,
                timezone="UTC",
                payload_version=None,
                quality_flags=[],
                payload={
                    "insider_name": txn.get("name"),
                    "insider_role": None,  # Not provided by Finnhub
                    "transaction_type": txn.get("transactionCode"),
                    "shares": txn.get("share"),
                    "price": txn.get("transactionPrice"),
                    "transaction_value": txn.get("share", 0) * txn.get("transactionPrice", 0),
                    "filing_date": filing_date,
                    "transaction_date": txn.get("transactionDate"),
                },
            )
            records.append(record)
        
        return records if records else [self._normalize_generic(raw)[0]]

    def _normalize_filing_sentiment(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize filing sentiment."""
        symbol = raw.payload.get("symbol", raw.request_params.get("accessNumber", "UNKNOWN"))
        accession_no = raw.payload.get("accessNumber", raw.request_params.get("accessNumber"))
        
        record = CanonicalRecord(
            record_id=self._generate_record_id(
                raw.source,
                "filing_sentiment",
                accession_no,
            ),
            schema_version="v1",
            source=raw.source,
            source_type="fundamentals",
            symbol=symbol,
            event_type="filing_sentiment",
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
        symbol = raw.request_params.get("symbol", "UNKNOWN")
        
        record = CanonicalRecord(
            record_id=self._generate_record_id(
                raw.source,
                symbol,
                raw.endpoint,
                raw.fetched_at.isoformat(),
            ),
            schema_version="v1",
            source=raw.source,
            source_type="fundamentals",
            symbol=symbol,
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
