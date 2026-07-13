"""Tests for feature engine."""

from datetime import datetime, timezone, timedelta

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine import (
    EarningsEventFeature,
    MacroRegimeFeature,
    PriceMomentumFeature,
)


def test_macro_regime_feature_with_data() -> None:
    """Test macro regime feature with CPI data."""
    records = [
        CanonicalRecord(
            record_id="test1",
            schema_version="v1",
            source="fred",
            source_type="macro",
            symbol=None,
            event_type="macro_release",
            event_time=datetime(2026, 2, 1, tzinfo=timezone.utc),
            as_of="2026-02-01",
            ingested_at=datetime.now(timezone.utc),
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload={"series_id": "CPIAUCSL", "value": 319.456},
        )
    ]
    
    feature = MacroRegimeFeature()
    results = feature.compute(records)
    
    assert len(results) == 1
    result = results[0]
    assert result.feature_name == "macro_regime"
    assert result.symbol is None
    assert "regime" in result.values
    assert "confidence" in result.values


def test_macro_regime_feature_no_data() -> None:
    """Test macro regime feature with no data."""
    feature = MacroRegimeFeature()
    results = feature.compute([])
    
    assert len(results) == 1
    result = results[0]
    assert result.values["regime"] == "unknown"
    assert "no_macro_data" in result.quality_flags


def test_earnings_event_feature_upcoming() -> None:
    """Test earnings event feature with upcoming event."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=3)
    
    records = [
        CanonicalRecord(
            record_id="test1",
            schema_version="v1",
            source="finnhub",
            source_type="fundamentals",
            symbol="AAPL",
            event_type="earnings_calendar",
            event_time=future,
            as_of=future.date().isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload={},
        )
    ]
    
    feature = EarningsEventFeature(lookahead_days=7)
    results = feature.compute(records)
    
    assert len(results) == 1
    result = results[0]
    assert result.feature_name == "earnings_event"
    assert result.symbol == "AAPL"
    assert result.values["has_upcoming_event"] is True
    assert result.values["days_until_event"] >= 0


def test_earnings_event_feature_no_upcoming() -> None:
    """Test earnings event feature with past event."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=10)
    
    records = [
        CanonicalRecord(
            record_id="test1",
            schema_version="v1",
            source="finnhub",
            source_type="fundamentals",
            symbol="AAPL",
            event_type="earnings_calendar",
            event_time=past,
            as_of=past.date().isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload={},
        )
    ]
    
    feature = EarningsEventFeature(lookahead_days=7)
    results = feature.compute(records)
    
    assert len(results) == 1
    result = results[0]
    assert result.values["has_upcoming_event"] is False


def test_price_momentum_feature_bullish() -> None:
    """Test price momentum feature with bullish trend."""
    now = datetime.now(timezone.utc)
    
    records = [
        CanonicalRecord(
            record_id="test1",
            schema_version="v1",
            source="broker",
            source_type="price",
            symbol="AAPL",
            event_type="bar_1day",
            event_time=now - timedelta(days=5),
            as_of=(now - timedelta(days=5)).date().isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload={"open": 180.0, "high": 182.0, "low": 179.0, "close": 181.0},
        ),
        CanonicalRecord(
            record_id="test2",
            schema_version="v1",
            source="broker",
            source_type="price",
            symbol="AAPL",
            event_type="bar_1day",
            event_time=now,
            as_of=now.date().isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload={"open": 188.0, "high": 190.0, "low": 187.0, "close": 189.0},
        ),
    ]
    
    feature = PriceMomentumFeature(period_days=5)
    results = feature.compute(records)
    
    assert len(results) == 1
    result = results[0]
    assert result.feature_name == "price_momentum"
    assert result.symbol == "AAPL"
    assert result.values["momentum"] > 0
    assert result.values["trend"] == "bullish"


def test_price_momentum_feature_return_1d() -> None:
    """Test that return_1d (prev-bar to latest-bar return) is correctly computed."""
    now = datetime.now(timezone.utc)
    prev_close = 190.0
    latest_close = 187.0
    expected_return_1d = (latest_close - prev_close) / prev_close  # -0.015789...

    records = [
        CanonicalRecord(
            record_id="r1",
            schema_version="v1",
            source="broker",
            source_type="price",
            symbol="SMH",
            event_type="bar_1day",
            event_time=now - timedelta(days=5),
            as_of=(now - timedelta(days=5)).date().isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload={"open": 200.0, "high": 201.0, "low": 199.0, "close": 200.0},
        ),
        CanonicalRecord(
            record_id="r2",
            schema_version="v1",
            source="broker",
            source_type="price",
            symbol="SMH",
            event_type="bar_1day",
            event_time=now - timedelta(days=1),
            as_of=(now - timedelta(days=1)).date().isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload={"open": 191.0, "high": 192.0, "low": 189.0, "close": prev_close},
        ),
        CanonicalRecord(
            record_id="r3",
            schema_version="v1",
            source="broker",
            source_type="price",
            symbol="SMH",
            event_type="bar_1day",
            event_time=now,
            as_of=now.date().isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload={"open": 189.0, "high": 189.5, "low": 186.0, "close": latest_close},
        ),
    ]

    feature = PriceMomentumFeature(period_days=5)
    results = feature.compute(records)

    assert len(results) == 1
    result = results[0]
    assert result.symbol == "SMH"
    assert "return_1d" in result.values
    assert result.values["return_1d"] is not None
    assert abs(result.values["return_1d"] - expected_return_1d) < 1e-9


def test_price_momentum_feature_insufficient_data() -> None:
    """Test price momentum feature with insufficient data."""
    now = datetime.now(timezone.utc)
    
    records = [
        CanonicalRecord(
            record_id="test1",
            schema_version="v1",
            source="broker",
            source_type="price",
            symbol="AAPL",
            event_type="bar_1day",
            event_time=now,
            as_of=now.date().isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload={"close": 180.0},
        ),
    ]
    
    feature = PriceMomentumFeature()
    results = feature.compute(records)
    
    assert len(results) == 1
    result = results[0]
    assert "insufficient_bars" in result.quality_flags
