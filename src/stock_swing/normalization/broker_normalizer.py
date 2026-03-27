"""Broker normalizer for transforming broker payloads to canonical schema.

Supported event types:
- Market data bars
- Quotes
- Account snapshots
- Position snapshots
- Order updates

See SOURCE_MAPPING.md for field mappings.
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord, RawEnvelope
from stock_swing.normalization.normalizer import BaseNormalizer


class BrokerNormalizer(BaseNormalizer):
    """Normalizer for Broker source data."""

    def normalize(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize Broker raw envelope to canonical records.
        
        Args:
            raw: RawEnvelope from BrokerClient.
            
        Returns:
            List of CanonicalRecord instances.
        """
        if "bars" in raw.endpoint:
            return self._normalize_bars(raw)
        elif "quote" in raw.endpoint:
            return self._normalize_quote(raw)
        elif "account" in raw.endpoint:
            return self._normalize_account(raw)
        elif "positions" in raw.endpoint:
            return self._normalize_positions(raw)
        elif "orders" in raw.endpoint:
            return self._normalize_orders(raw)
        else:
            return self._normalize_generic(raw)

    def _normalize_bars(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize market data bars."""
        bars = raw.payload.get("bars", [])
        symbol = raw.request_params.get("symbol", "UNKNOWN")
        timeframe = raw.request_params.get("timeframe", "1Min")
        
        records = []
        for bar in bars:
            bar_time_str = bar.get("t")
            
            # Parse bar timestamp
            try:
                event_time = self._normalize_timestamp(bar_time_str)
            except Exception:
                event_time = raw.fetched_at
            
            record = CanonicalRecord(
                record_id=self._generate_record_id(
                    raw.source,
                    symbol,
                    timeframe,
                    bar_time_str,
                ),
                schema_version="v1",
                source=raw.source,
                source_type="price",
                symbol=symbol,
                event_type=f"bar_{timeframe.lower()}",
                event_time=event_time,
                as_of=self._extract_as_of_date(event_time),
                ingested_at=raw.fetched_at,
                timezone="UTC",
                payload_version=None,
                quality_flags=[],
                payload={
                    "timeframe": timeframe,
                    "open": bar.get("o"),
                    "high": bar.get("h"),
                    "low": bar.get("l"),
                    "close": bar.get("c"),
                    "volume": bar.get("v"),
                    "vwap": bar.get("vw"),
                    "trade_count": bar.get("n"),
                },
            )
            records.append(record)
        
        return records if records else []

    def _normalize_quote(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize latest quote."""
        quote_data = raw.payload.get("quote", raw.payload)
        symbol = raw.request_params.get("symbol", "UNKNOWN")
        
        quote_time_str = quote_data.get("t", raw.fetched_at.isoformat())
        
        try:
            event_time = self._normalize_timestamp(quote_time_str)
        except Exception:
            event_time = raw.fetched_at
        
        record = CanonicalRecord(
            record_id=self._generate_record_id(
                raw.source,
                symbol,
                "quote",
                event_time.isoformat(),
            ),
            schema_version="v1",
            source=raw.source,
            source_type="price",
            symbol=symbol,
            event_type="quote",
            event_time=event_time,
            as_of=self._extract_as_of_date(event_time),
            ingested_at=raw.fetched_at,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload={
                "bid_price": quote_data.get("bp"),
                "ask_price": quote_data.get("ap"),
                "bid_size": quote_data.get("bs"),
                "ask_size": quote_data.get("as"),
            },
        )
        
        return [record]

    def _normalize_account(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize account snapshot."""
        record = CanonicalRecord(
            record_id=self._generate_record_id(
                raw.source,
                "account",
                raw.fetched_at.isoformat(),
            ),
            schema_version="v1",
            source=raw.source,
            source_type="position",
            symbol=None,
            event_type="account_snapshot",
            event_time=raw.fetched_at,
            as_of=self._extract_as_of_date(raw.fetched_at),
            ingested_at=raw.fetched_at,
            timezone="UTC",
            payload_version=None,
            quality_flags=[],
            payload=raw.payload,
        )
        
        return [record]

    def _normalize_positions(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize positions."""
        positions = raw.payload if isinstance(raw.payload, list) else [raw.payload]
        
        records = []
        for pos in positions:
            symbol = pos.get("symbol", "UNKNOWN")
            
            record = CanonicalRecord(
                record_id=self._generate_record_id(
                    raw.source,
                    symbol,
                    "position",
                    raw.fetched_at.isoformat(),
                ),
                schema_version="v1",
                source=raw.source,
                source_type="position",
                symbol=symbol,
                event_type="position_snapshot",
                event_time=raw.fetched_at,
                as_of=self._extract_as_of_date(raw.fetched_at),
                ingested_at=raw.fetched_at,
                timezone="UTC",
                payload_version=None,
                quality_flags=[],
                payload=pos,
            )
            records.append(record)
        
        return records if records else []

    def _normalize_orders(self, raw: RawEnvelope) -> list[CanonicalRecord]:
        """Normalize orders."""
        orders = raw.payload if isinstance(raw.payload, list) else [raw.payload]
        
        records = []
        for order in orders:
            symbol = order.get("symbol", "UNKNOWN")
            order_id = order.get("id", "UNKNOWN")
            
            record = CanonicalRecord(
                record_id=self._generate_record_id(
                    raw.source,
                    order_id,
                ),
                schema_version="v1",
                source=raw.source,
                source_type="order",
                symbol=symbol,
                event_type="order_update",
                event_time=raw.fetched_at,
                as_of=self._extract_as_of_date(raw.fetched_at),
                ingested_at=raw.fetched_at,
                timezone="UTC",
                payload_version=None,
                quality_flags=[],
                payload=order,
            )
            records.append(record)
        
        return records if records else []

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
            source_type="price",
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
