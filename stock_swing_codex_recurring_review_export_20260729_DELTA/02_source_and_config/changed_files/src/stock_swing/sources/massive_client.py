"""
Massive API client for market data.

Provides access to:
- Historical OHLC bars (minute/day aggregates)
- Technical indicators (SMA, EMA, RSI, MACD)
- Real-time quotes and trades
- Options data and Greeks
"""

from typing import Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
import os

import logging

logger = logging.getLogger(__name__)

try:
    from massive import RESTClient as _MassiveRESTClient
except ImportError:  # pragma: no cover - exercised via constructor path
    _MassiveRESTClient = None


@dataclass
class MassiveBar:
    """Simplified bar structure from Massive API."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: Optional[float] = None
    transactions: Optional[int] = None


class MassiveClient:
    """
    Wrapper around Massive REST API.
    
    Usage:
        client = MassiveClient()
        bars = client.fetch_minute_bars("NVDA", from_date="2026-04-01", to_date="2026-05-12")
        sma = client.fetch_sma("NVDA", window=20)
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Massive client.
        
        Args:
            api_key: Massive API key (defaults to MASSIVE_API_KEY env var)
        """
        self.api_key = api_key or os.environ.get("MASSIVE_API_KEY")
        if not self.api_key:
            raise ValueError("MASSIVE_API_KEY not found in environment")

        if _MassiveRESTClient is None:
            raise ImportError(
                "massive SDK is required for MassiveClient. "
                "Install with: pip install massive"
            )

        self.client = _MassiveRESTClient(api_key=self.api_key)
        # R7-v2 / H8: increase urllib3 connection pool maxsize to silence
        # "Connection pool is full, discarding connection" warnings.
        # The Massive SDK creates a PoolManager with default maxsize=1;
        # patching connection_pool_kw before any requests are made raises
        # it to 10 so concurrent symbol fetches reuse persistent connections.
        try:
            pool_mgr = getattr(self.client, 'client', None)
            if pool_mgr is not None and hasattr(pool_mgr, 'connection_pool_kw'):
                pool_mgr.connection_pool_kw.setdefault('maxsize', 10)
                pool_mgr.connection_pool_kw['maxsize'] = max(
                    pool_mgr.connection_pool_kw.get('maxsize', 1), 10
                )
                logger.debug("Massive connection pool maxsize set to %d",
                             pool_mgr.connection_pool_kw['maxsize'])
        except Exception as _e:
            logger.debug("Could not patch Massive pool maxsize: %s", _e)
        logger.info("Massive client initialized")
    
    def fetch_minute_bars(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        multiplier: int = 1,
        limit: int = 50000
    ) -> List[MassiveBar]:
        """
        Fetch minute-level OHLC bars.
        
        Args:
            symbol: Stock ticker (e.g., "NVDA")
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            multiplier: Minute aggregation (1 = 1-minute bars, 5 = 5-minute bars)
            limit: Max bars to return (default 50000)
        
        Returns:
            List of MassiveBar objects
        """
        logger.info(f"Fetching {multiplier}-minute bars for {symbol} from {from_date} to {to_date}")
        
        bars = []
        try:
            for agg in self.client.list_aggs(
                ticker=symbol,
                multiplier=multiplier,
                timespan="minute",
                from_=from_date,
                to=to_date,
                limit=limit
            ):
                bars.append(MassiveBar(
                    timestamp=datetime.fromtimestamp(agg.timestamp / 1000),
                    open=agg.open,
                    high=agg.high,
                    low=agg.low,
                    close=agg.close,
                    volume=agg.volume,
                    vwap=getattr(agg, 'vwap', None),
                    transactions=getattr(agg, 'transactions', None)
                ))
            
            logger.info(f"Fetched {len(bars)} minute bars for {symbol}")
            return bars
        
        except Exception as e:
            logger.error(f"Failed to fetch minute bars for {symbol}: {e}")
            raise
    
    def fetch_daily_bars(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        limit: int = 5000
    ) -> List[MassiveBar]:
        """
        Fetch daily OHLC bars.
        
        Args:
            symbol: Stock ticker (e.g., "NVDA")
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            limit: Max bars to return (default 5000)
        
        Returns:
            List of MassiveBar objects
        """
        logger.info(f"Fetching daily bars for {symbol} from {from_date} to {to_date}")
        
        bars = []
        try:
            for agg in self.client.list_aggs(
                ticker=symbol,
                multiplier=1,
                timespan="day",
                from_=from_date,
                to=to_date,
                limit=limit
            ):
                bars.append(MassiveBar(
                    timestamp=datetime.fromtimestamp(agg.timestamp / 1000),
                    open=agg.open,
                    high=agg.high,
                    low=agg.low,
                    close=agg.close,
                    volume=agg.volume,
                    vwap=getattr(agg, 'vwap', None),
                    transactions=getattr(agg, 'transactions', None)
                ))
            
            logger.info(f"Fetched {len(bars)} daily bars for {symbol}")
            return bars
        
        except Exception as e:
            logger.error(f"Failed to fetch daily bars for {symbol}: {e}")
            raise
    
    def fetch_sma(
        self,
        symbol: str,
        window: int = 20,
        series_type: str = "close",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[dict]:
        """
        Fetch Simple Moving Average from Massive API.
        
        Args:
            symbol: Stock ticker
            window: SMA window size (default 20)
            series_type: Price series ("close", "open", "high", "low")
            from_date: Optional start date
            to_date: Optional end date
        
        Returns:
            List of {timestamp, value} dicts
        """
        logger.info(f"Fetching SMA({window}) for {symbol}")
        
        try:
            params = {
                "ticker": symbol,
                "timespan": "day",
                "window": window,
                "series_type": series_type
            }
            if from_date:
                params["timestamp_gte"] = from_date
            if to_date:
                params["timestamp_lte"] = to_date
            
            response = self.client.get_sma(**params)
            results = []
            
            # Handle the response - it may have a .values or .results attribute
            if hasattr(response, 'values'):
                items = response.values
            elif hasattr(response, 'results'):
                items = response.results
            else:
                items = [response]  # Single result
            
            for item in items:
                results.append({
                    "timestamp": datetime.fromtimestamp(item.timestamp / 1000),
                    "value": item.value
                })
            
            logger.info(f"Fetched {len(results)} SMA values for {symbol}")
            return results
        
        except Exception as e:
            logger.error(f"Failed to fetch SMA for {symbol}: {e}")
            raise
    
    def fetch_rsi(
        self,
        symbol: str,
        window: int = 14,
        series_type: str = "close",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[dict]:
        """
        Fetch Relative Strength Index from Massive API.
        
        Args:
            symbol: Stock ticker
            window: RSI window size (default 14)
            series_type: Price series ("close", "open", "high", "low")
            from_date: Optional start date
            to_date: Optional end date
        
        Returns:
            List of {timestamp, value} dicts
        """
        logger.info(f"Fetching RSI({window}) for {symbol}")
        
        try:
            params = {
                "ticker": symbol,
                "timespan": "day",
                "window": window,
                "series_type": series_type
            }
            if from_date:
                params["timestamp_gte"] = from_date
            if to_date:
                params["timestamp_lte"] = to_date
            
            response = self.client.get_rsi(**params)
            results = []
            
            # Handle the response - it may have a .values or .results attribute
            if hasattr(response, 'values'):
                items = response.values
            elif hasattr(response, 'results'):
                items = response.results
            else:
                items = [response]  # Single result
            
            for item in items:
                results.append({
                    "timestamp": datetime.fromtimestamp(item.timestamp / 1000),
                    "value": item.value
                })
            
            logger.info(f"Fetched {len(results)} RSI values for {symbol}")
            return results
        
        except Exception as e:
            logger.error(f"Failed to fetch RSI for {symbol}: {e}")
            raise
    
    def get_ticker_details(self, symbol: str) -> dict:
        """
        Get ticker metadata.
        
        Args:
            symbol: Stock ticker
        
        Returns:
            Dict with ticker details (name, market, currency, etc.)
        """
        try:
            details = self.client.get_ticker_details(symbol)
            return {
                "ticker": details.ticker,
                "name": details.name,
                "market": details.market,
                "currency": details.currency_name,
                "type": getattr(details, 'type', None),
                "primary_exchange": getattr(details, 'primary_exchange', None)
            }
        except Exception as e:
            logger.error(f"Failed to get ticker details for {symbol}: {e}")
            raise
