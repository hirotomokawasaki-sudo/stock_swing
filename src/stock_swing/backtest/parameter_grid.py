"""Parameter grid generator for backtesting."""

from __future__ import annotations

from itertools import product
from typing import Dict, List, Any


class ParameterGrid:
    """Generate parameter combinations for grid search."""
    
    # Default parameter ranges
    DEFAULT_RANGES = {
        # Entry parameters
        'confidence_threshold': [0.60, 0.65, 0.70, 0.75],
        'min_momentum': [0.02, 0.03, 0.04, 0.05],
        
        # Exit parameters
        'stop_loss_pct': [0.05, 0.07, 0.10],
        'take_profit_pct': [0.10, 0.15, 0.20],
        'max_hold_days': [3, 5, 7],
        
        # Position sizing
        'max_position_pct': [0.06, 0.08, 0.10],
        'max_risk_per_trade': [0.003, 0.005, 0.007],
    }
    
    # Priority parameter sets (high-impact, quick to test)
    PRIORITY_RANGES = {
        'confidence_threshold': [0.65, 0.70],
        'min_momentum': [0.03, 0.04],
        'stop_loss_pct': [0.05, 0.07],
        'take_profit_pct': [0.10, 0.15],
        'max_hold_days': [5, 7],
        'max_position_pct': [0.08],
        'max_risk_per_trade': [0.005],
    }
    
    def __init__(self, custom_ranges: Dict[str, List[Any]] | None = None):
        """Initialize parameter grid.
        
        Args:
            custom_ranges: Custom parameter ranges to override defaults
        """
        self.ranges = self.DEFAULT_RANGES.copy()
        if custom_ranges:
            self.ranges.update(custom_ranges)
    
    def generate(self, priority_only: bool = False) -> List[Dict[str, Any]]:
        """Generate all parameter combinations.
        
        Args:
            priority_only: If True, only generate priority combinations
            
        Returns:
            List of parameter dictionaries
        """
        ranges = self.PRIORITY_RANGES if priority_only else self.ranges
        
        # Get all parameter names and their values
        param_names = sorted(ranges.keys())
        param_values = [ranges[name] for name in param_names]
        
        # Generate all combinations
        combinations = []
        for values in product(*param_values):
            param_dict = dict(zip(param_names, values))
            combinations.append(param_dict)
        
        return combinations
    
    def count(self, priority_only: bool = False) -> int:
        """Count total number of combinations.
        
        Args:
            priority_only: If True, count only priority combinations
            
        Returns:
            Number of parameter combinations
        """
        ranges = self.PRIORITY_RANGES if priority_only else self.ranges
        
        count = 1
        for values in ranges.values():
            count *= len(values)
        
        return count
    
    def filter_by_criteria(
        self, 
        combinations: List[Dict[str, Any]],
        criteria: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Filter combinations by criteria.
        
        Useful for applying domain knowledge or constraints.
        
        Args:
            combinations: List of parameter combinations
            criteria: Filtering criteria (e.g., {"max_hold_days": lambda x: x >= 5})
            
        Returns:
            Filtered list of combinations
        """
        filtered = []
        
        for combo in combinations:
            include = True
            
            for param_name, criterion in criteria.items():
                value = combo.get(param_name)
                
                # If criterion is callable, use it as filter function
                if callable(criterion):
                    if not criterion(value):
                        include = False
                        break
                # Otherwise, check equality
                else:
                    if value != criterion:
                        include = False
                        break
            
            if include:
                filtered.append(combo)
        
        return filtered
    
    def apply_domain_constraints(self, combinations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply domain-specific constraints to filter unrealistic combinations.
        
        Examples:
        - take_profit should be >= stop_loss (generally)
        - max_position_pct should align with max_risk_per_trade
        
        Args:
            combinations: List of parameter combinations
            
        Returns:
            Filtered list respecting domain constraints
        """
        filtered = []
        
        for combo in combinations:
            # Constraint 1: Take profit should be >= stop loss
            tp = combo.get('take_profit_pct', 0.15)
            sl = combo.get('stop_loss_pct', 0.07)
            if tp < sl:
                continue
            
            # Constraint 2: Reasonable risk/position alignment
            # Higher max_position allows higher risk per trade
            risk = combo.get('max_risk_per_trade', 0.005)
            pos_pct = combo.get('max_position_pct', 0.08)
            
            # Risk per trade should not exceed ~10% of max position
            if risk > pos_pct * 0.10:
                continue
            
            filtered.append(combo)
        
        return filtered
