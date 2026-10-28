"""Contract tests for canonical schema validation.

These tests verify that normalized records comply with CANONICAL_SCHEMA.md
and that source-to-canonical mappings are stable and correct.
"""

from datetime import datetime, timezone

import pytest

from stock_swing.core.types import CanonicalRecord, RawEnvelope
from stock_swing.normalization import (
    BrokerNormalizer,
    FinnhubNormalizer,
    FredNormalizer,
    SecNormalizer,
)


def validate_canonical_record(record: CanonicalRecord) -> None:
    """Validate that a record conforms to canonical schema requirements.
    
    Args:
        record: CanonicalRecord to validate.
        
    Raises:
        AssertionError: If record does not conform to schema.
    """
    # Required fields must be present
    assert record.record_id is not None, "record_id is required"
    assert record.schema_version is not None, "schema_version is required"
    assert record.source is not None, "source is required"
    assert record.source_type is not None, "source_type is required"
    # symbol can be None for macro data
    assert record.event_type is not None, "event_type is required"
    assert record.event_time is not None, "event_time is required"
    assert record.as_of is not None, "as_of is required"
    assert record.ingested_at is not None, "ingested_at is required"
    assert record.timezone is not None, "timezone is required"
    assert record.quality_flags is not None, "quality_flags is required"
    assert record.payload is not None, "payload is required"
    
    # Type checks
    assert isinstance(record.record_id, str), "record_id must be string"
    assert isinstance(record.schema_version, str), "schema_version must be string"
    assert isinstance(record.source, str), "source must be string"
    assert isinstance(record.source_type, str), "source_type must be string"
    assert record.symbol is None or isinstance(record.symbol, str), "symbol must be string or None"
    assert isinstance(record.event_type, str), "event_type must be string"
    assert isinstance(record.event_time, datetime), "event_time must be datetime"
    assert isinstance(record.as_of, str), "as_of must be string"
    assert isinstance(record.ingested_at, datetime), "ingested_at must be datetime"
    assert isinstance(record.timezone, str), "timezone must be string"
    assert isinstance(record.quality_flags, list), "quality_flags must be list"
    assert isinstance(record.payload, dict), "payload must be dict"
    
    # Value constraints
    assert record.schema_version == "v1", "schema_version must be v1"
    assert record.source in {"finnhub", "fred", "sec", "broker"}, "source must be valid"
    assert record.source_type in {
        "fundamentals",
        "macro",
        "filing",
        "price",
        "order",
        "position",
    }, "source_type must be valid"
    assert record.timezone == "UTC", "timezone must be UTC"
    
    # Timestamp checks
    assert record.event_time.tzinfo is not None, "event_time must have timezone"
    assert record.ingested_at.tzinfo is not None, "ingested_at must have timezone"
    
    # as_of format check (YYYY-MM-DD)
    assert len(record.as_of) == 10, "as_of must be YYYY-MM-DD"
    assert record.as_of[4] == "-" and record.as_of[7] == "-", "as_of format invalid"


def test_finnhub_basic_financials_contract() -> None:
    """Contract test: Finnhub basic financials normalization."""
    raw = RawEnvelope(
        source="finnhub",
        endpoint="stock/metric",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={"symbol": "AAPL"},
        payload={"metric": {"eps": 6.15, "pe": 28.5}},
    )
    
    normalizer = FinnhubNormalizer()
    records = normalizer.normalize(raw)
    
    assert len(records) == 1, "Should produce exactly one record"
    record = records[0]
    
    # Validate canonical schema compliance
    validate_canonical_record(record)
    
    # Finnhub-specific assertions
    assert record.source == "finnhub"
    assert record.source_type == "fundamentals"
    assert record.symbol == "AAPL"
    assert record.event_type == "basic_financials"
    assert "metric" in record.payload


def test_finnhub_earnings_calendar_contract() -> None:
    """Contract test: Finnhub earnings calendar normalization."""
    raw = RawEnvelope(
        source="finnhub",
        endpoint="calendar/earnings",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={},
        payload={
            "earningsCalendar": [
                {
                    "symbol": "AAPL",
                    "date": "2026-04-01",
                    "epsEstimate": 1.52,
                    "revenueEstimate": 94500000000,
                    "quarter": 2,
                    "year": 2026,
                }
            ]
        },
    )
    
    normalizer = FinnhubNormalizer()
    records = normalizer.normalize(raw)
    
    assert len(records) >= 1, "Should produce at least one record"
    
    for record in records:
        validate_canonical_record(record)
        assert record.source == "finnhub"
        assert record.source_type == "fundamentals"
        assert record.event_type == "earnings_calendar"
        
        # Canonical payload structure for earnings
        assert "estimate_eps" in record.payload
        assert "estimate_revenue" in record.payload
        assert "fiscal_period" in record.payload


def test_finnhub_insider_transactions_contract() -> None:
    """Contract test: Finnhub insider transactions normalization."""
    raw = RawEnvelope(
        source="finnhub",
        endpoint="stock/insider-transactions",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={"symbol": "AAPL"},
        payload={
            "data": [
                {
                    "symbol": "AAPL",
                    "name": "Jane Doe",
                    "share": 2500,
                    "transactionCode": "P",
                    "transactionPrice": 187.4,
                    "filingDate": "2026-03-04",
                }
            ]
        },
    )
    
    normalizer = FinnhubNormalizer()
    records = normalizer.normalize(raw)
    
    assert len(records) >= 1, "Should produce at least one record"
    
    for record in records:
        validate_canonical_record(record)
        assert record.source == "finnhub"
        assert record.event_type == "insider_transaction"
        
        # Canonical payload structure for insider transactions
        assert "insider_name" in record.payload
        assert "transaction_type" in record.payload
        assert "shares" in record.payload
        assert "price" in record.payload
        assert "filing_date" in record.payload


def test_fred_series_observations_contract() -> None:
    """Contract test: FRED series observations normalization."""
    raw = RawEnvelope(
        source="fred",
        endpoint="series/observations",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={"series_id": "CPIAUCSL"},
        payload={
            "observations": [
                {"date": "2026-01-01", "value": "319.082"},
                {"date": "2026-02-01", "value": "319.456"},
            ]
        },
    )
    
    normalizer = FredNormalizer()
    records = normalizer.normalize(raw)
    
    assert len(records) == 2, "Should produce one record per observation"
    
    for record in records:
        validate_canonical_record(record)
        assert record.source == "fred"
        assert record.source_type == "macro"
        assert record.symbol is None, "Macro data should have no symbol"
        assert record.event_type == "macro_release"
        
        # Canonical payload structure for macro data
        assert "series_id" in record.payload
        assert "value" in record.payload
        assert "period" in record.payload


def test_sec_company_submissions_contract() -> None:
    """Contract test: SEC company submissions normalization."""
    raw = RawEnvelope(
        source="sec",
        endpoint="submissions/CIK0000320193.json",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={"cik": "0000320193"},
        payload={
            "cik": "320193",
            "tickers": ["AAPL"],
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-26-000012", "0000320193-26-000011"],
                    "filingDate": ["2026-03-05", "2026-02-15"],
                    "form": ["8-K", "10-Q"],
                }
            },
        },
    )
    
    normalizer = SecNormalizer()
    records = normalizer.normalize(raw)
    
    assert len(records) >= 1, "Should produce at least one record"
    
    for record in records:
        validate_canonical_record(record)
        assert record.source == "sec"
        assert record.source_type == "filing"
        assert record.event_type == "filing"
        
        # Canonical payload structure for filings
        assert "form_type" in record.payload
        assert "accession_no" in record.payload
        assert "filed_at" in record.payload


def test_broker_bars_contract() -> None:
    """Contract test: Broker bars normalization."""
    raw = RawEnvelope(
        source="broker",
        endpoint="v2/stocks/AAPL/bars",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={"symbol": "AAPL", "timeframe": "1Min"},
        payload={
            "bars": [
                {
                    "t": "2026-03-06T09:30:00Z",
                    "o": 183.12,
                    "h": 183.45,
                    "l": 182.91,
                    "c": 183.31,
                    "v": 1912200,
                }
            ]
        },
    )
    
    normalizer = BrokerNormalizer()
    records = normalizer.normalize(raw)
    
    assert len(records) == 1, "Should produce one record per bar"
    
    for record in records:
        validate_canonical_record(record)
        assert record.source == "broker"
        assert record.source_type == "price"
        assert record.symbol == "AAPL"
        assert "bar_" in record.event_type
        
        # Canonical payload structure for bars
        assert "timeframe" in record.payload
        assert "open" in record.payload
        assert "high" in record.payload
        assert "low" in record.payload
        assert "close" in record.payload
        assert "volume" in record.payload


def test_broker_positions_contract() -> None:
    """Contract test: Broker positions normalization."""
    raw = RawEnvelope(
        source="broker",
        endpoint="v2/positions",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={},
        payload=[
            {
                "symbol": "AAPL",
                "qty": "10",
                "market_value": "1833.10",
                "avg_entry_price": "180.00",
            }
        ],
    )
    
    normalizer = BrokerNormalizer()
    records = normalizer.normalize(raw)
    
    assert len(records) >= 1, "Should produce at least one record"
    
    for record in records:
        validate_canonical_record(record)
        assert record.source == "broker"
        assert record.source_type == "position"
        assert record.event_type == "position_snapshot"


def test_record_id_stability() -> None:
    """Contract test: Record IDs are deterministic and stable."""
    raw = RawEnvelope(
        source="finnhub",
        endpoint="stock/metric",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={"symbol": "AAPL"},
        payload={"metric": {"eps": 6.15}},
    )
    
    normalizer = FinnhubNormalizer()
    
    # Generate records multiple times
    records1 = normalizer.normalize(raw)
    records2 = normalizer.normalize(raw)
    records3 = normalizer.normalize(raw)
    
    # Record IDs should be identical
    assert records1[0].record_id == records2[0].record_id
    assert records2[0].record_id == records3[0].record_id


def test_timestamp_normalization_to_utc() -> None:
    """Contract test: All timestamps normalized to UTC."""
    raw = RawEnvelope(
        source="finnhub",
        endpoint="stock/metric",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={"symbol": "AAPL"},
        payload={"metric": {"eps": 6.15}},
    )
    
    normalizer = FinnhubNormalizer()
    records = normalizer.normalize(raw)
    
    for record in records:
        assert record.event_time.tzinfo == timezone.utc
        assert record.ingested_at.tzinfo == timezone.utc
        assert record.timezone == "UTC"


def test_quality_flags_present() -> None:
    """Contract test: Quality flags array always present."""
    raw = RawEnvelope(
        source="finnhub",
        endpoint="stock/metric",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={"symbol": "AAPL"},
        payload={"metric": {"eps": 6.15}},
    )
    
    normalizer = FinnhubNormalizer()
    records = normalizer.normalize(raw)
    
    for record in records:
        assert isinstance(record.quality_flags, list)
        # Can be empty or contain flags
        for flag in record.quality_flags:
            assert isinstance(flag, str)
