"""Backtest engine for parameter optimization.

This module provides backtesting capabilities for optimizing trading
parameters using historical decision and trade data.
"""

from .engine import BacktestEngine
from .data_loader import DataLoader
from .parameter_grid import ParameterGrid
from .trade_simulator import TradeSimulator
from .metrics import MetricsCalculator, BacktestResult, BacktestTrade

__all__ = [
    "BacktestEngine",
    "DataLoader",
    "ParameterGrid",
    "TradeSimulator",
    "MetricsCalculator",
    "BacktestResult",
    "BacktestTrade",
]
from .price_cache import PriceCache

__all__.append("PriceCache")
