"""Enhanced backtest engine with full simulation loop."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any
import logging

from .data_loader import DataLoader
from .parameter_grid import ParameterGrid
from .trade_simulator import TradeSimulator
from .metrics import MetricsCalculator, BacktestResult
from .price_cache import PriceCache

logger = logging.getLogger(__name__)


class BacktestEngineV2:
    """Enhanced backtest engine with full daily simulation."""
    
    def __init__(
        self,
        project_root: Path,
        start_equity: float = 100000.0,
        broker_client=None
    ):
        """Initialize enhanced backtest engine.
        
        Args:
            project_root: Path to project root directory
            start_equity: Starting equity for simulations
            broker_client: Optional broker client for price data
        """
        self.project_root = Path(project_root)
        self.start_equity = start_equity
        
        # Initialize components
        self.data_loader = DataLoader(project_root)
        self.parameter_grid = ParameterGrid()
        self.simulator = TradeSimulator(start_equity)
        self.metrics_calculator = MetricsCalculator()
        
        # Initialize price cache
        cache_dir = project_root / "data" / "price_cache"
        self.price_cache = PriceCache(cache_dir, broker_client)
    
    def run_backtest_full(
        self,
        parameters: Dict[str, Any],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        use_real_prices: bool = False
    ) -> BacktestResult:
        """Run full backtest with daily simulation loop.
        
        Args:
            parameters: Parameter set to test
            start_date: Start date for backtest
            end_date: End date for backtest
            use_real_prices: If True, use real prices from broker/cache
            
        Returns:
            BacktestResult with performance metrics
        """
        # Reset simulator
        self.simulator.reset()
        
        # Load decisions
        decisions = self.data_loader.load_decisions(start_date, end_date)
        
        if not decisions:
            logger.warning("No decision data available")
            return self._empty_result(parameters)
        
        # Group decisions by date
        decisions_by_date = self._group_decisions_by_date(decisions)
        
        # Determine date range
        if not start_date or not end_date:
            dates = sorted(decisions_by_date.keys())
            if not dates:
                return self._empty_result(parameters)
            start_date = start_date or dates[0]
            end_date = end_date or dates[-1]
        
        # Run daily simulation
        current_date = start_date
        
        while current_date <= end_date:
            # Get decisions for this date
            daily_decisions = decisions_by_date.get(current_date, [])
            
            # Process entries
            for decision in daily_decisions:
                self._process_entry(decision, current_date, parameters, use_real_prices, debug=False)
            
            # Get current prices
            current_prices = self._get_prices_for_date(current_date, use_real_prices)
            
            # Check exits
            self.simulator.check_exits(current_date, current_prices)
            
            # Update equity curve
            self.simulator.update_equity_curve(current_prices)
            
            # Move to next day
            current_date += timedelta(days=1)
        
        # Close remaining positions
        final_prices = self._get_prices_for_date(end_date, use_real_prices)
        self.simulator.close_all_positions(end_date, final_prices)
        
        # Calculate metrics
        result = self.metrics_calculator.calculate(
            trades=self.simulator.trades,
            equity_curve=self.simulator.equity_curve,
            start_equity=self.start_equity
        )
        
        result.parameters = parameters
        
        return result
    
    def _group_decisions_by_date(
        self,
        decisions: List[Dict[str, Any]]
    ) -> Dict[datetime, List[Dict[str, Any]]]:
        """Group decisions by date."""
        grouped = {}
        
        for decision in decisions:
            # Parse timestamp (try both 'timestamp' and 'generated_at')
            ts_str = decision.get('timestamp') or decision.get('generated_at', '')
            if not ts_str:
                continue
            
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                date = ts.replace(hour=0, minute=0, second=0, microsecond=0)
                
                if date not in grouped:
                    grouped[date] = []
                
                grouped[date].append(decision)
            
            except Exception:
                continue
        
        return grouped
    
    def _process_entry(
        self,
        decision: Dict[str, Any],
        date: datetime,
        parameters: Dict[str, Any],
        use_real_prices: bool,
        debug: bool = False
    ):
        """Process potential entry from decision.
        
        Args:
            decision: Decision record
            date: Current date
            parameters: Backtest parameters
            use_real_prices: Use real prices if available
            debug: Print debug information
        """
        # Extract decision details
        symbol = decision.get('symbol', '')
        action = decision.get('action', '')
        confidence = decision.get('confidence', 0.0)
        
        if debug:
            print(f"  Processing: {symbol} action={action} conf={confidence:.2f}")
        
        if not symbol or action.lower() != 'buy':
            if debug:
                print(f"    Skip: not a BUY action")
            return
        
        # Check if decision was skipped in reality
        sizing = decision.get('sizing') or {}
        if sizing.get('skip_reason'):
            # Skip if it was skipped in real trading
            # (We want to simulate what actually could have happened)
            pass  # For now, still consider it
        
        # Filter by confidence threshold
        min_confidence = parameters.get('confidence_threshold', 0.65)
        if confidence < min_confidence:
            if debug:
                print(f"    Skip: confidence {confidence:.2f} < {min_confidence:.2f}")
            return
        
        # Get entry price
        if use_real_prices:
            entry_price = self.price_cache.get_price(symbol, date, 'open')
        else:
            # Use price from decision evidence/sizing
            evidence = decision.get('evidence') or {}
            sizing_info = (evidence.get('sizing') or decision.get('sizing') or {})
            entry_price = sizing_info.get('current_price')
            
            # Fallback to latest_close
            if not entry_price or entry_price <= 0:
                entry_price = evidence.get('latest_close')
        
        if not entry_price or entry_price <= 0:
            if debug:
                print(f"    Skip: no valid entry price")
            return
        
        if debug:
            print(f"    Entry price: ${entry_price:.2f}")
        
        # Check if can enter
        can_enter, qty = self.simulator.can_enter_position(
            symbol,
            entry_price,
            parameters
        )
        
        if debug:
            print(f"    Can enter: {can_enter}, Qty: {qty}")
        
        if not can_enter or qty < 1:
            if debug:
                print(f"    Skip: cannot enter or qty < 1")
            return
        
        # Enter position
        success = self.simulator.enter_position(
            symbol,
            date,
            entry_price,
            qty,
            parameters
        )
        
        if debug:
            print(f"    ✓ Entered: {success}, Total positions: {len(self.simulator.positions)}")
    
    def _get_prices_for_date(
        self,
        date: datetime,
        use_real_prices: bool
    ) -> Dict[str, float]:
        """Get prices for all symbols on a date.
        
        Args:
            date: Date to get prices for
            use_real_prices: Use real prices from cache/broker
            
        Returns:
            Dictionary mapping symbols to prices
        """
        prices = {}
        
        # Get all symbols in positions
        symbols = list(self.simulator.positions.keys())
        
        for symbol in symbols:
            if use_real_prices:
                price = self.price_cache.get_price(symbol, date, 'close')
                if price:
                    prices[symbol] = price
            else:
                # TEMPORARY: Simulate price movement for testing
                # In real backtest, we need actual price data
                position = self.simulator.positions.get(symbol)
                if position:
                    # Simulate random walk: +/- 2% per day
                    import random
                    days_held = (date - position.entry_date).days
                    # Slightly bullish bias for testing
                    daily_return = random.uniform(-0.02, 0.03)
                    simulated_price = position.entry_price * (1 + daily_return * days_held)
                    prices[symbol] = max(simulated_price, position.entry_price * 0.90)  # Floor at -10%
        
        return prices
    
    def _empty_result(self, parameters: Dict[str, Any]) -> BacktestResult:
        """Create empty result for failed backtest."""
        from .metrics import BacktestResult
        
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
