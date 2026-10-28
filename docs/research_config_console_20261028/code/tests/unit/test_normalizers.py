"""Tests for source normalizers."""

from datetime import datetime, timezone

from stock_swing.core.types import RawEnvelope
from stock_swing.normalization import (
    BrokerNormalizer,
    FinnhubNormalizer,
    FredNormalizer,
    SecNormalizer,
)


def test_finnhub_basic_financials() -> None:
    """Test Finnhub basic financials normalization."""
    raw = RawEnvelope(
        source="finnhub",
        endpoint="stock/metric",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={"symbol": "AAPL"},
        payload={"metric": {"eps": 6.15, "pe": 28.5}},
    )
    
    normalizer = FinnhubNormalizer()
    records = normalizer.normalize(raw)
    
    assert len(records) == 1
    record = records[0]
    assert record.source == "finnhub"
    assert record.source_type == "fundamentals"
    assert record.symbol == "AAPL"
    assert record.event_type == "basic_financials"
    assert record.schema_version == "v1"


def test_finnhub_earnings_calendar() -> None:
    """Test Finnhub earnings calendar normalization."""
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
    
    assert len(records) == 1
    record = records[0]
    assert record.symbol == "AAPL"
    assert record.event_type == "earnings_calendar"
    assert record.payload["estimate_eps"] == 1.52


def test_fred_series_observations() -> None:
    """Test FRED series observations normalization."""
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
    
    assert len(records) == 2
    record = records[0]
    assert record.source == "fred"
    assert record.source_type == "macro"
    assert record.symbol is None
    assert record.event_type == "macro_release"
    assert record.payload["series_id"] == "CPIAUCSL"
    assert record.payload["value"] == 319.082


def test_sec_company_submissions() -> None:
    """Test SEC company submissions normalization."""
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
                    "accessionNumber": ["0000320193-26-000012"],
                    "filingDate": ["2026-03-05"],
                    "form": ["8-K"],
                }
            },
        },
    )
    
    normalizer = SecNormalizer()
    records = normalizer.normalize(raw)
    
    assert len(records) >= 1
    record = records[0]
    assert record.source == "sec"
    assert record.source_type == "filing"
    assert record.symbol == "AAPL"
    assert record.event_type == "filing"
    assert record.payload["form_type"] == "8-K"


def test_broker_bars() -> None:
    """Test Broker bars normalization."""
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
    
    assert len(records) == 1
    record = records[0]
    assert record.source == "broker"
    assert record.source_type == "price"
    assert record.symbol == "AAPL"
    assert record.event_type == "bar_1min"
    assert record.payload["open"] == 183.12
    assert record.payload["close"] == 183.31


def test_record_id_deterministic() -> None:
    """Test that record IDs are deterministic."""
    raw = RawEnvelope(
        source="finnhub",
        endpoint="stock/metric",
        fetched_at=datetime(2026, 3, 6, 14, 30, 0, tzinfo=timezone.utc),
        request_params={"symbol": "AAPL"},
        payload={"metric": {"eps": 6.15}},
    )
    
    normalizer = FinnhubNormalizer()
    records1 = normalizer.normalize(raw)
    records2 = normalizer.normalize(raw)
    
    assert records1[0].record_id == records2[0].record_id
