"""
Hybrid data fetcher: Uses Massive for ETFs, Broker for stocks.

This solves the Alpaca stale ETF data problem (stopped at 2026-04-22)
by using Massive API as a fallback for ETF symbols.
"""

from __future__ import annotations

import os
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

from stock_swing.core.types import CanonicalRecord
from stock_swing.sources.broker_client_protocol import BrokerClientProtocol

logger = logging.getLogger(__name__)


class HybridDataFetcher:
    """
    Hybrid data fetcher that prefers Massive for all symbols.
    
    UPDATE 2026-05-15: Alpaca fetch_bars() stopped updating ALL symbols
    (stocks + ETFs) on 2026-04-22. All symbols have 23-day-old stale data.
    
    Strategy:
    - Try Massive first for ALL symbols
    - Fallback to Yahoo daily bars for 1Day requests if Massive fails
    - Fallback to Broker only as a last resort
    - Broker positions API still works (used for entry prices and exit strategy)
    """
    
    def __init__(
        self,
        broker_client: BrokerClientProtocol,
        etf_symbols: set[str],
        massive_api_key: Optional[str] = None
    ):
        """
        Initialize hybrid fetcher.
        
        Args:
            broker_client: Broker client (any BrokerClientProtocol implementation;
                Alpaca today, future IBKR possible — see docs/broker_migration_ibkr_plan.md)
            etf_symbols: Set of ETF ticker symbols
            massive_api_key: Massive API key (optional, defaults to env var)
        """
        self.broker = broker_client
        self.etf_symbols = etf_symbols
        
        # Initialize Massive client if API key available
        self.massive_client = None
        api_key = massive_api_key or os.environ.get("MASSIVE_API_KEY")
        
        if api_key:
            try:
                from stock_swing.sources.massive_client import MassiveClient
                self.massive_client = MassiveClient(api_key=api_key)
                logger.info("Massive client initialized for ETF data")
            except Exception as exc:
                logger.warning(f"Failed to initialize Massive client: {exc}")
                logger.warning("Will use broker for all symbols (may have stale ETF data)")
        else:
            logger.warning("MASSIVE_API_KEY not found - using broker only")
    
    def fetch_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        limit: int = 20
    ) -> tuple[list[CanonicalRecord], str]:
        """
        Fetch bars for a symbol using appropriate source.
        
        2026-05-15: Alpaca fetch_bars() stopped updating ALL symbols on 2026-04-22.
        Strategy: Try Massive first for ALL symbols, fallback to Broker only if Massive fails.
        
        Args:
            symbol: Ticker symbol
            timeframe: Bar timeframe (e.g., "1Day")
            limit: Number of bars to fetch
        
        Returns:
            Tuple of (records, source_name)
            source_name is "massive", "broker", or "failed"
        """
        # Try Massive first for ALL symbols (if available)
        if self.massive_client:
            try:
                records = self._fetch_from_massive(symbol, limit)
                if records:
                    return (records, "massive")
            except Exception as exc:
                logger.warning(f"Massive fetch failed for {symbol}: {exc}, falling back to broker")
        
        # Yahoo is a safer fallback for daily bars than broker bars, which have
        # occasionally shown split/scale anomalies in paper mode.
        if timeframe.lower() in {"1day", "day", "daily"}:
            try:
                records = self._fetch_from_yahoo(symbol, limit)
                if records:
                    logger.warning(f"Using Yahoo fallback for {symbol} after Massive failure")
                    return (records, "yahoo")
            except Exception as exc:
                logger.warning(f"Yahoo fallback failed for {symbol}: {exc}, falling back to broker")

        # Fallback to broker (may be stale or malformed, use sparingly)
        try:
            records = self._fetch_from_broker(symbol, timeframe, limit)
            logger.warning(f"Using broker data for {symbol} - may be stale (Alpaca stopped 2026-04-22)")
            return (records, "broker")
        except Exception as exc:
            logger.error(f"Broker fetch failed for {symbol}: {exc}")
            return ([], "failed")
    
    def _fetch_from_massive(self, symbol: str, limit: int) -> list[CanonicalRecord]:
        """Fetch bars from Massive API and convert to CanonicalRecord."""
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=limit)
        from_str = start_date.strftime("%Y-%m-%d")
        to_str = end_date.strftime("%Y-%m-%d")
        
        bars = self.massive_client.fetch_daily_bars(
            symbol,
            from_date=from_str,
            to_date=to_str,
            limit=limit
        )
        
        if not bars:
            return []
        
        # Convert to CanonicalRecord
        records = []
        for bar in bars:
            # Ensure timezone-aware timestamp
            if bar.timestamp.tzinfo is None:
                bar_timestamp = bar.timestamp.replace(tzinfo=timezone.utc)
            else:
                bar_timestamp = bar.timestamp
            
            record = CanonicalRecord(
                record_id=f"massive_{symbol}_{bar_timestamp.isoformat()}",
                schema_version="v1",
                source="massive",
                source_type="price",
                symbol=symbol,
                event_type="bar_daily",
                event_time=bar_timestamp,
                as_of=bar_timestamp.isoformat(),
                ingested_at=datetime.now(timezone.utc),
                timezone="UTC",
                payload_version="v1",
                payload={
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "vwap": bar.vwap,
                    "transactions": bar.transactions
                },
                quality_flags=[]
            )
            records.append(record)
        
        logger.info(f"Fetched {len(records)} bars for {symbol} from Massive")
        return records

    def _fetch_from_yahoo(self, symbol: str, limit: int) -> list[CanonicalRecord]:
        """Fetch recent daily bars from Yahoo Finance."""
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        result = data.get("chart", {}).get("result", [{}])[0]
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]

        records: list[CanonicalRecord] = []
        for ts, open_, high, low, close, volume in zip(
            timestamps,
            quote.get("open", []),
            quote.get("high", []),
            quote.get("low", []),
            quote.get("close", []),
            quote.get("volume", []),
        ):
            if open_ is None or high is None or low is None or close is None:
                continue
            event_time = datetime.fromtimestamp(ts, tz=timezone.utc)
            records.append(
                CanonicalRecord(
                    record_id=f"yahoo_{symbol}_{event_time.isoformat()}",
                    schema_version="v1",
                    source="yahoo",
                    source_type="price",
                    symbol=symbol,
                    event_type="bar_daily",
                    event_time=event_time,
                    as_of=event_time.isoformat(),
                    ingested_at=datetime.now(timezone.utc),
                    timezone="UTC",
                    payload_version="v1",
                    payload={
                        "open": float(open_),
                        "high": float(high),
                        "low": float(low),
                        "close": float(close),
                        "volume": int(volume or 0),
                        "vwap": None,
                        "transactions": None,
                    },
                    quality_flags=[],
                )
            )

        if limit > 0:
            records = records[-limit:]
        logger.info(f"Fetched {len(records)} bars for {symbol} from Yahoo")
        return records
    
    def _fetch_from_broker(
        self,
        symbol: str,
        timeframe: str,
        limit: int
    ) -> list[CanonicalRecord]:
        """Fetch bars from Broker API and normalize."""
        from stock_swing.normalization.broker_normalizer import BrokerNormalizer
        
        raw = self.broker.fetch_bars(symbol, timeframe=timeframe, limit=limit)
        normalizer = BrokerNormalizer()
        records = normalizer.normalize(raw)
        
        logger.info(f"Fetched {len(records)} bars for {symbol} from Broker")
        return records
