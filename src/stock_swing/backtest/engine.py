"""Main backtest engine."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import logging

from .data_loader import DataLoader
from .parameter_grid import ParameterGrid
from .trade_simulator import TradeSimulator
from .metrics import MetricsCalculator, BacktestResult


logger = logging.getLogger(__name__)


class BacktestEngine:
    """Main backtest engine for parameter optimization."""
    
    def __init__(self, project_root: Path, start_equity: float = 100000.0):
        """Initialize backtest engine.
        
        Args:
            project_root: Path to project root directory
            start_equity: Starting equity for simulations
        """
        self.project_root = Path(project_root)
        self.start_equity = start_equity
        
        # Initialize components
        self.data_loader = DataLoader(project_root)
        self.parameter_grid = ParameterGrid()
        self.simulator = TradeSimulator(start_equity)
        self.metrics_calculator = MetricsCalculator()
    
    def run_single_backtest(
        self,
        parameters: Dict[str, Any],
        start_date: datetime | None = None,
        end_date: datetime | None = None
    ) -> BacktestResult:
        """Run a single backtest with given parameters.
        
        Args:
            parameters: Parameter set to test
            start_date: Start date for backtest
            end_date: End date for backtest
            
        Returns:
            BacktestResult with performance metrics
        """
        # Reset simulator
        self.simulator.reset()
        
        # Load data
        decisions = self.data_loader.load_decisions(start_date, end_date)
        
        if not decisions:
            logger.warning("No decision data available for backtest")
            return self._empty_result(parameters)
        
        # TODO: For now, return placeholder result
        # Full implementation requires:
        # 1. Price data loading
        # 2. Decision filtering by parameters
        # 3. Daily simulation loop
        # 4. Position management
        
        # Calculate metrics
        result = self.metrics_calculator.calculate(
            trades=self.simulator.trades,
            equity_curve=self.simulator.equity_curve,
            start_equity=self.start_equity
        )
        
        result.parameters = parameters
        
        return result
    
    def run_grid_search(
        self,
        priority_only: bool = True,
        max_combinations: int | None = None
    ) -> List[BacktestResult]:
        """Run backtests for all parameter combinations.
        
        Args:
            priority_only: If True, only test priority parameters
            max_combinations: Maximum combinations to test (None for all)
            
        Returns:
            List of BacktestResult sorted by Sharpe ratio
        """
        # Generate parameter combinations
        combinations = self.parameter_grid.generate(priority_only=priority_only)
        
        # Apply domain constraints
        combinations = self.parameter_grid.apply_domain_constraints(combinations)
        
        # Limit if requested
        if max_combinations and len(combinations) > max_combinations:
            combinations = combinations[:max_combinations]
        
        logger.info(f"Running grid search with {len(combinations)} parameter combinations")
        
        # Run backtests
        results = []
        for i, params in enumerate(combinations):
            if (i + 1) % 10 == 0:
                logger.info(f"Progress: {i+1}/{len(combinations)}")
            
            result = self.run_single_backtest(params)
            results.append(result)
        
        # Sort by Sharpe ratio (descending)
        results.sort(key=lambda r: r.sharpe_ratio, reverse=True)
        
        return results
    
    def run_walk_forward(
        self,
        train_days: int = 10,
        test_days: int = 5,
        priority_only: bool = True
    ) -> Dict[str, Any]:
        """Run walk-forward validation.
        
        Args:
            train_days: Number of days for training window
            test_days: Number of days for testing window
            priority_only: Use priority parameters only
            
        Returns:
            Dictionary with walk-forward results
        """
        # Get available date range
        start_date, end_date = self.data_loader.get_date_range()
        
        if not start_date or not end_date:
            logger.warning("No data available for walk-forward validation")
            return {
                "train_results": [],
                "test_results": [],
                "best_parameters": {}
            }
        
        # TODO: Implement walk-forward logic
        # 1. Split data into train/test windows
        # 2. Optimize on training window
        # 3. Validate on test window
        # 4. Roll forward
        
        return {
            "train_results": [],
            "test_results": [],
            "best_parameters": {}
        }
    
    def get_best_parameters(
        self,
        results: List[BacktestResult],
        metric: str = "sharpe_ratio"
    ) -> Dict[str, Any]:
        """Get best parameters from backtest results.
        
        Args:
            results: List of backtest results
            metric: Metric to optimize (sharpe_ratio, total_return, win_rate, etc.)
            
        Returns:
            Best parameter set
        """
        if not results:
            return {}
        
        # Sort by selected metric
        if metric == "sharpe_ratio":
            best = max(results, key=lambda r: r.sharpe_ratio)
        elif metric == "total_return":
            best = max(results, key=lambda r: r.total_return)
        elif metric == "win_rate":
            best = max(results, key=lambda r: r.win_rate)
        else:
            best = results[0]
        
        return best.parameters
    
    def _empty_result(self, parameters: Dict[str, Any]) -> BacktestResult:
        """Create empty result for failed backtest.
        
        Args:
            parameters: Parameters used
            
        Returns:
            BacktestResult with zero values
        """
        return BacktestResult(
            parameters=parameters,
            total_return=0.0,
            sharpe_ratio=0.0,
            win_rate=0.0,
            max_drawdown=0.0,
            total_trades=0,
            avg_pnl=0.0,
            profit_factor=0.0,
            trades=[],
            equity_curve=[self.start_equity],
            final_equity=self.start_equity,
            start_equity=self.start_equity
        )
