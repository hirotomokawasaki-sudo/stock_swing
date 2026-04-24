"""Price data cache for backtesting."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)


class PriceCache:
    """Cache historical price data for backtesting."""
    
    def __init__(self, cache_dir: Path, broker_client=None):
        """Initialize price cache.
        
        Args:
            cache_dir: Directory to store cached price data
            broker_client: BrokerClient instance for fetching data
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.broker_client = broker_client
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
    
    def get_price(
        self,
        symbol: str,
        date: datetime,
        price_type: str = "close"
    ) -> float | None:
        """Get price for a symbol on a specific date.
        
        Args:
            symbol: Stock symbol
            date: Date to get price for
            price_type: Type of price (open, high, low, close)
            
        Returns:
            Price or None if not available
        """
        # Check memory cache first
        cache_key = f"{symbol}_{date.date()}"
        if cache_key in self._memory_cache:
            bar = self._memory_cache[cache_key]
            return bar.get(price_type)
        
        # Load from file cache
        data = self._load_from_file(symbol, date)
        if data:
            self._memory_cache[cache_key] = data
            return data.get(price_type)
        
        # Fetch from broker if available
        if self.broker_client:
            fetched = self._fetch_and_cache(symbol, date)
            if fetched:
                return fetched.get(price_type)
        
        return None
    
    def get_price_range(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[datetime, Dict[str, float]]:
        """Get price data for a date range.
        
        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            
        Returns:
            Dictionary mapping dates to OHLC data
        """
        result = {}
        
        # Try to load all from file cache first
        cached_data = self._load_range_from_file(symbol, start_date, end_date)
        
        # Fill in any missing dates from broker
        current = start_date
        while current <= end_date:
            date_key = current.date()
            
            if date_key in cached_data:
                result[current] = cached_data[date_key]
            elif self.broker_client:
                bar = self._fetch_and_cache(symbol, current)
                if bar:
                    result[current] = bar
            
            current += timedelta(days=1)
        
        return result
    
    def _load_from_file(self, symbol: str, date: datetime) -> Dict[str, float] | None:
        """Load price data from file cache."""
        cache_file = self.cache_dir / f"{symbol}_{date.year}_{date.month:02d}.json"
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            
            date_str = date.date().isoformat()
            return data.get(date_str)
        
        except Exception as e:
            logger.warning(f"Failed to load cache for {symbol} on {date}: {e}")
            return None
    
    def _load_range_from_file(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[Any, Dict[str, float]]:
        """Load price range from file cache."""
        result = {}
        
        # Determine which cache files to load
        current = start_date
        cache_files = set()
        
        while current <= end_date:
            cache_file = self.cache_dir / f"{symbol}_{current.year}_{current.month:02d}.json"
            cache_files.add(cache_file)
            
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        # Load each cache file
        for cache_file in cache_files:
            if not cache_file.exists():
                continue
            
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                
                # Filter to date range
                for date_str, bar in data.items():
                    try:
                        date = datetime.fromisoformat(date_str).date()
                        if start_date.date() <= date <= end_date.date():
                            result[date] = bar
                    except Exception:
                        continue
            
            except Exception as e:
                logger.warning(f"Failed to load cache file {cache_file}: {e}")
                continue
        
        return result
    
    def _fetch_and_cache(self, symbol: str, date: datetime) -> Dict[str, float] | None:
        """Fetch price from broker and cache it."""
        if not self.broker_client:
            return None
        
        try:
            # Fetch 1 day bar
            response = self.broker_client.fetch_bars(
                symbol=symbol,
                timeframe="1Day",
                start=date.isoformat(),
                end=(date + timedelta(days=1)).isoformat(),
                limit=1
            )
            
            payload = response.payload if hasattr(response, 'payload') else response
            bars = payload.get('bars', []) if isinstance(payload, dict) else payload
            
            if not bars:
                return None
            
            bar = bars[0]
            
            # Extract OHLC
            price_data = {
                'open': float(bar.get('o', 0)),
                'high': float(bar.get('h', 0)),
                'low': float(bar.get('l', 0)),
                'close': float(bar.get('c', 0)),
                'volume': float(bar.get('v', 0)),
            }
            
            # Cache to file
            self._save_to_file(symbol, date, price_data)
            
            # Cache to memory
            cache_key = f"{symbol}_{date.date()}"
            self._memory_cache[cache_key] = price_data
            
            return price_data
        
        except Exception as e:
            logger.warning(f"Failed to fetch price for {symbol} on {date}: {e}")
            return None
    
    def _save_to_file(self, symbol: str, date: datetime, price_data: Dict[str, float]):
        """Save price data to file cache."""
        cache_file = self.cache_dir / f"{symbol}_{date.year}_{date.month:02d}.json"
        
        # Load existing data
        existing = {}
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    existing = json.load(f)
            except Exception:
                pass
        
        # Add new data
        date_str = date.date().isoformat()
        existing[date_str] = price_data
        
        # Save
        try:
            with open(cache_file, 'w') as f:
                json.dump(existing, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache for {symbol}: {e}")
