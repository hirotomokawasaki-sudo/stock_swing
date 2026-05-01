"""Portfolio allocation enforcement for ETF vs Stock targets."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml

logger = logging.getLogger(__name__)


class PortfolioAllocator:
    """Enforce portfolio allocation rules (ETF vs Stocks).
    
    Ensures portfolio maintains target allocation between asset classes
    (e.g., 35% ETFs, 65% Stocks) by prioritizing buy decisions based on
    current allocation deviation from targets.
    """
    
    def __init__(self, config_path: Path):
        """Initialize portfolio allocator with config file.
        
        Args:
            config_path: Path to portfolio_allocation.yaml config file.
        """
        self.config = self._load_config(config_path)
        allocation = self.config.get('portfolio', {}).get('allocation', {})
        self.target_etf_pct = allocation.get('ETFs', 0.35)
        self.target_stock_pct = allocation.get('stocks', 0.65)
        
        # Tolerance before rebalancing (5% deviation triggers prioritization)
        self.rebalance_threshold_pct = 0.05
        
        logger.info(
            f"PortfolioAllocator initialized: ETF target={self.target_etf_pct:.1%}, "
            f"Stock target={self.target_stock_pct:.1%}"
        )
    
    def _load_config(self, path: Path) -> Dict[str, Any]:
        """Load YAML config file.
        
        Args:
            path: Path to YAML config file.
            
        Returns:
            Parsed config dict.
        """
        if not path.exists():
            logger.warning(f"Config file not found: {path}, using defaults")
            return {'portfolio': {'allocation': {'ETFs': 0.35, 'stocks': 0.65}}}
        
        with open(path) as f:
            return yaml.safe_load(f) or {}
    
    def _calculate_current_allocation(
        self,
        current_positions: Dict[str, Any],
        etf_symbols: Set[str]
    ) -> tuple[float, float, float]:
        """Calculate current ETF and Stock allocation.
        
        Args:
            current_positions: Dict of current positions {symbol: {market_value, ...}}.
            etf_symbols: Set of symbols that are ETFs.
            
        Returns:
            Tuple of (etf_value, stock_value, total_value).
        """
        etf_value = 0.0
        stock_value = 0.0
        
        for symbol, position in current_positions.items():
            market_value = float(position.get('market_value', 0))
            if symbol in etf_symbols:
                etf_value += market_value
            else:
                stock_value += market_value
        
        total_value = etf_value + stock_value
        return etf_value, stock_value, total_value
    
    def should_prioritize_etf(
        self, 
        current_positions: Dict[str, Any],
        etf_symbols: Set[str]
    ) -> bool:
        """Determine if ETF purchases should be prioritized.
        
        Args:
            current_positions: Dict of current positions.
            etf_symbols: Set of ETF symbols.
            
        Returns:
            True if ETF allocation is below target - threshold.
        """
        etf_value, stock_value, total_value = self._calculate_current_allocation(
            current_positions, etf_symbols
        )
        
        if total_value == 0:
            # Start with ETF purchases when portfolio is empty
            return True
        
        current_etf_pct = etf_value / total_value
        etf_deficit = self.target_etf_pct - current_etf_pct
        
        logger.info(
            f"ETF allocation: current={current_etf_pct:.1%} "
            f"(${etf_value:,.0f}), target={self.target_etf_pct:.1%}, "
            f"deficit={etf_deficit:.1%}"
        )
        
        # Prioritize ETF if below target by more than threshold
        return etf_deficit > self.rebalance_threshold_pct
    
    def should_prioritize_stock(
        self,
        current_positions: Dict[str, Any],
        etf_symbols: Set[str]
    ) -> bool:
        """Determine if Stock purchases should be prioritized.
        
        Args:
            current_positions: Dict of current positions.
            etf_symbols: Set of ETF symbols.
            
        Returns:
            True if Stock allocation is below target - threshold.
        """
        etf_value, stock_value, total_value = self._calculate_current_allocation(
            current_positions, etf_symbols
        )
        
        if total_value == 0:
            return False  # Start with ETF when empty
        
        current_stock_pct = stock_value / total_value
        stock_deficit = self.target_stock_pct - current_stock_pct
        
        logger.info(
            f"Stock allocation: current={current_stock_pct:.1%} "
            f"(${stock_value:,.0f}), target={self.target_stock_pct:.1%}, "
            f"deficit={stock_deficit:.1%}"
        )
        
        # Prioritize Stock if below target by more than threshold
        return stock_deficit > self.rebalance_threshold_pct
    
    def filter_decisions_by_allocation(
        self, 
        decisions: List[Any],
        current_positions: Dict[str, Any],
        etf_symbols: Set[str]
    ) -> List[Any]:
        """Filter and prioritize buy decisions based on portfolio allocation.
        
        Args:
            decisions: List of decision objects with .proposed_order.symbol.
            current_positions: Dict of current positions.
            etf_symbols: Set of ETF symbols.
            
        Returns:
            Reordered list of decisions with prioritized asset class first.
        """
        if not decisions:
            return []
        
        # Separate buy and sell decisions
        buy_decisions = [d for d in decisions if d.proposed_order.side == 'buy']
        sell_decisions = [d for d in decisions if d.proposed_order.side == 'sell']
        
        if not buy_decisions:
            return decisions  # No buys to prioritize
        
        # Separate ETF and Stock buy decisions
        etf_buys = [d for d in buy_decisions if d.proposed_order.symbol in etf_symbols]
        stock_buys = [d for d in buy_decisions if d.proposed_order.symbol not in etf_symbols]
        
        # Determine prioritization
        prioritize_etf = self.should_prioritize_etf(current_positions, etf_symbols)
        prioritize_stock = self.should_prioritize_stock(current_positions, etf_symbols)
        
        if prioritize_etf:
            logger.info(f"Prioritizing {len(etf_buys)} ETF buy decisions")
            reordered_buys = etf_buys + stock_buys
        elif prioritize_stock:
            logger.info(f"Prioritizing {len(stock_buys)} Stock buy decisions")
            reordered_buys = stock_buys + etf_buys
        else:
            logger.info("Portfolio allocation balanced, no prioritization needed")
            reordered_buys = buy_decisions
        
        # Return: sell decisions first (exits), then prioritized buys
        return sell_decisions + reordered_buys
    
    def get_allocation_status(
        self,
        current_positions: Dict[str, Any],
        etf_symbols: Set[str]
    ) -> Dict[str, Any]:
        """Get current allocation status for monitoring.
        
        Args:
            current_positions: Dict of current positions.
            etf_symbols: Set of ETF symbols.
            
        Returns:
            Dict with allocation status details.
        """
        etf_value, stock_value, total_value = self._calculate_current_allocation(
            current_positions, etf_symbols
        )
        
        if total_value > 0:
            current_etf_pct = etf_value / total_value
            current_stock_pct = stock_value / total_value
        else:
            current_etf_pct = 0.0
            current_stock_pct = 0.0
        
        return {
            'total_value': total_value,
            'etf_value': etf_value,
            'stock_value': stock_value,
            'current_etf_pct': current_etf_pct,
            'current_stock_pct': current_stock_pct,
            'target_etf_pct': self.target_etf_pct,
            'target_stock_pct': self.target_stock_pct,
            'etf_deficit': self.target_etf_pct - current_etf_pct,
            'stock_deficit': self.target_stock_pct - current_stock_pct,
            'needs_rebalance': abs(self.target_etf_pct - current_etf_pct) > self.rebalance_threshold_pct,
        }
