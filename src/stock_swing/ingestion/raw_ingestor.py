"""Raw ingestion layer for fetching and persisting immutable source snapshots.

This module implements raw data ingestion for approved sources:
- Finnhub: Basic financials, earnings, insider, filing sentiment
- FRED: Macro series data
- SEC: Company filings
- Broker: Market data, account, positions, orders

See MUSTREAD_NAVIGATION.md for raw data immutability requirements.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from stock_swing.core.path_manager import PathManager
from stock_swing.core.types import RawEnvelope
from stock_swing.sources.base import SourceClient
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.finnhub_client import FinnhubClient
from stock_swing.sources.fred_client import FredClient
from stock_swing.sources.sec_client import SecClient
from stock_swing.storage.stage_store import StageStore


class RawIngestor:
    """Raw data ingestor for all approved sources.
    
    This class handles fetching data from source clients and persisting
    immutable raw snapshots to approved data/raw/{source}/ paths.
    
    Attributes:
        paths: PathManager for project-root-relative path resolution.
        store: StageStore for stage-aware persistence with raw immutability.
    """

    def __init__(self, project_root: Path, allow_raw_overwrite: bool = False) -> None:
        """Initialize RawIngestor.
        
        Args:
            project_root: Project root directory path.
            allow_raw_overwrite: If True, allow overwriting existing raw files.
                Default False enforces raw immutability.
        """
        self.paths = PathManager(project_root)
        self.store = StageStore(self.paths, allow_raw_overwrite=allow_raw_overwrite)

    def ingest(
        self,
        client: SourceClient,
        **kwargs: Any,
    ) -> Path:
        """Generic raw ingestion for any source client.
        
        Args:
            client: Source client instance.
            **kwargs: Source-specific fetch parameters.
            
        Returns:
            Path to the written raw file.
            
        Raises:
            SourceError: On fetch error.
            RawOverwriteError: If raw file exists and overwrite not allowed.
            
        Note:
            Filename format: {source}_{identifier}_{date}_{timestamp}.json
        """
        envelope = client.fetch(**kwargs)
        filename = self._build_filename(client.name, envelope, kwargs)
        
        return self.store.write_raw(client.name, filename, envelope)

    def ingest_finnhub(
        self,
        client: FinnhubClient,
        endpoint: str,
        symbol: str | None = None,
        **kwargs: Any,
    ) -> Path:
        """Ingest Finnhub data.
        
        Args:
            client: FinnhubClient instance.
            endpoint: Finnhub endpoint (e.g., "stock/metric").
            symbol: Stock symbol (if applicable).
            **kwargs: Additional endpoint-specific parameters.
            
        Returns:
            Path to the written raw file.
        """
        fetch_params = {"endpoint": endpoint, **kwargs}
        if symbol:
            fetch_params["symbol"] = symbol
        
        return self.ingest(client, **fetch_params)

    def ingest_fred(
        self,
        client: FredClient,
        series_id: str,
        observation_start: str | None = None,
        observation_end: str | None = None,
        **kwargs: Any,
    ) -> Path:
        """Ingest FRED series data.
        
        Args:
            client: FredClient instance.
            series_id: FRED series ID (e.g., "CPIAUCSL").
            observation_start: Start date (YYYY-MM-DD, optional).
            observation_end: End date (YYYY-MM-DD, optional).
            **kwargs: Additional parameters.
            
        Returns:
            Path to the written raw file.
        """
        fetch_params = {"series_id": series_id, **kwargs}
        if observation_start:
            fetch_params["observation_start"] = observation_start
        if observation_end:
            fetch_params["observation_end"] = observation_end
        
        return self.ingest(client, **fetch_params)

    def ingest_sec(
        self,
        client: SecClient,
        cik: str,
        endpoint_type: str = "submissions",
        **kwargs: Any,
    ) -> Path:
        """Ingest SEC filing data.
        
        Args:
            client: SecClient instance.
            cik: Central Index Key (10-digit with leading zeros).
            endpoint_type: Type of SEC endpoint ("submissions" or "concept").
            **kwargs: Additional endpoint-specific parameters.
            
        Returns:
            Path to the written raw file.
        """
        if endpoint_type == "submissions":
            envelope = client.fetch_company_submissions(cik)
        elif endpoint_type == "concept":
            taxonomy = kwargs.get("taxonomy", "us-gaap")
            tag = kwargs.get("tag", "Revenue")
            envelope = client.fetch_company_concept(cik, taxonomy, tag)
        else:
            raise ValueError(f"unsupported SEC endpoint_type: {endpoint_type}")
        
        filename = self._build_filename(client.name, envelope, {"cik": cik, **kwargs})
        return self.store.write_raw(client.name, filename, envelope)

    def ingest_broker_bars(
        self,
        client: BrokerClient,
        symbol: str,
        timeframe: str = "1Min",
        start: str | None = None,
        end: str | None = None,
        **kwargs: Any,
    ) -> Path:
        """Ingest broker market data bars.
        
        Args:
            client: BrokerClient instance.
            symbol: Stock symbol.
            timeframe: Bar timeframe (e.g., "1Min", "1Day").
            start: Start datetime (ISO8601, optional).
            end: End datetime (ISO8601, optional).
            **kwargs: Additional parameters.
            
        Returns:
            Path to the written raw file.
        """
        fetch_params = {
            "symbol": symbol,
            "timeframe": timeframe,
            **kwargs,
        }
        if start:
            fetch_params["start"] = start
        if end:
            fetch_params["end"] = end
        
        envelope = client.fetch_bars(**fetch_params)
        filename = self._build_filename(
            client.name,
            envelope,
            {"symbol": symbol, "timeframe": timeframe},
        )
        return self.store.write_raw(client.name, filename, envelope)

    def ingest_broker_account(self, client: BrokerClient) -> Path:
        """Ingest broker account information.
        
        Args:
            client: BrokerClient instance.
            
        Returns:
            Path to the written raw file.
        """
        envelope = client.fetch_account()
        filename = self._build_filename(client.name, envelope, {"type": "account"})
        return self.store.write_raw(client.name, filename, envelope)

    def ingest_broker_positions(self, client: BrokerClient) -> Path:
        """Ingest broker positions.
        
        Args:
            client: BrokerClient instance.
            
        Returns:
            Path to the written raw file.
        """
        envelope = client.fetch_positions()
        filename = self._build_filename(client.name, envelope, {"type": "positions"})
        return self.store.write_raw(client.name, filename, envelope)

    def ingest_broker_orders(
        self,
        client: BrokerClient,
        status: str = "all",
    ) -> Path:
        """Ingest broker orders.
        
        Args:
            client: BrokerClient instance.
            status: Order status filter ("open", "closed", "all").
            
        Returns:
            Path to the written raw file.
        """
        envelope = client.fetch_orders(status=status)
        filename = self._build_filename(
            client.name,
            envelope,
            {"type": "orders", "status": status},
        )
        return self.store.write_raw(client.name, filename, envelope)

    def _build_filename(
        self,
        source: str,
        envelope: RawEnvelope,
        params: dict[str, Any],
    ) -> str:
        """Build filename for raw data snapshot.
        
        Args:
            source: Source name.
            envelope: Raw envelope with fetched data.
            params: Original fetch parameters.
            
        Returns:
            Filename with format: {source}_{identifier}_{date}_{timestamp}.json
            
        Naming convention:
            - source: Source name (finnhub, fred, sec, broker)
            - identifier: Symbol, series_id, cik, or type
            - date: YYYY-MM-DD from fetched_at
            - timestamp: HHMMSSffffff from fetched_at
            
        Example:
            finnhub_AAPL_2026-03-06_093015123456.json
            fred_CPIAUCSL_2026-03-06_140530987654.json
        """
        # Extract identifier from params
        identifier = (
            params.get("symbol")
            or params.get("series_id")
            or params.get("cik")
            or params.get("type")
            or "data"
        )
        
        # Normalize identifier (remove special chars, lowercase)
        identifier_clean = str(identifier).replace("/", "_").replace(":", "_").lower()
        
        # Format timestamp
        date_str = envelope.fetched_at.date().isoformat()
        time_str = envelope.fetched_at.strftime("%H%M%S%f")
        
        return f"{source}_{identifier_clean}_{date_str}_{time_str}.json"
