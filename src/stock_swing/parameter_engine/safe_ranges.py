"""Safe parameter ranges for recommendation validation.

This module defines approved parameter families and safe ranges
for parameter recommendations.

CRITICAL: Recommendations must stay within these ranges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ParameterRange:
    """Safe range for a parameter.
    
    Attributes:
        parameter_name: Parameter name.
        min_value: Minimum allowed value.
        max_value: Maximum allowed value.
        default_value: Default/baseline value.
        increment: Recommended increment size.
        value_type: Value type (float/int/str).
    """
    
    parameter_name: str
    min_value: Any
    max_value: Any
    default_value: Any
    increment: Any
    value_type: type


# Approved parameter families and safe ranges
APPROVED_PARAMETER_RANGES = {
    # Strategy thresholds
    "min_signal_strength": ParameterRange(
        parameter_name="min_signal_strength",
        min_value=0.4,
        max_value=0.9,
        default_value=0.6,
        increment=0.05,
        value_type=float,
    ),
    "min_momentum": ParameterRange(
        parameter_name="min_momentum",
        min_value=0.01,
        max_value=0.15,
        default_value=0.05,
        increment=0.01,
        value_type=float,
    ),
    
    # Risk thresholds
    "min_confidence": ParameterRange(
        parameter_name="min_confidence",
        min_value=0.4,
        max_value=0.85,
        default_value=0.5,
        increment=0.05,
        value_type=float,
    ),
    
    # Position sizing
    "max_position_size": ParameterRange(
        parameter_name="max_position_size",
        min_value=10,
        max_value=200,
        default_value=100,
        increment=10,
        value_type=int,
    ),
    
    # Time horizons (days)
    "time_horizon_days": ParameterRange(
        parameter_name="time_horizon_days",
        min_value=1,
        max_value=10,
        default_value=3,
        increment=1,
        value_type=int,
    ),
}


class SafeRangeValidator:
    """Validator for parameter recommendation safe ranges.
    
    Ensures recommendations stay within approved parameter families and ranges.
    """
    
    def __init__(
        self,
        approved_ranges: dict[str, ParameterRange] | None = None,
    ):
        """Initialize safe range validator.
        
        Args:
            approved_ranges: Approved parameter ranges (uses defaults if None).
        """
        self.approved_ranges = approved_ranges or APPROVED_PARAMETER_RANGES
    
    def is_parameter_approved(self, parameter_name: str) -> bool:
        """Check if parameter is in approved family.
        
        Args:
            parameter_name: Parameter to check.
            
        Returns:
            True if parameter is approved.
        """
        return parameter_name in self.approved_ranges
    
    def validate_value(
        self,
        parameter_name: str,
        value: Any,
    ) -> tuple[bool, str | None]:
        """Validate parameter value is within safe range.
        
        Args:
            parameter_name: Parameter name.
            value: Value to validate.
            
        Returns:
            Tuple of (is_valid, error_message).
        """
        if not self.is_parameter_approved(parameter_name):
            return False, f"Parameter '{parameter_name}' not in approved family"
        
        param_range = self.approved_ranges[parameter_name]
        
        # Type check
        if not isinstance(value, param_range.value_type):
            return False, (
                f"Value type mismatch: expected {param_range.value_type.__name__}, "
                f"got {type(value).__name__}"
            )
        
        # Range check
        if value < param_range.min_value or value > param_range.max_value:
            return False, (
                f"Value {value} outside safe range "
                f"[{param_range.min_value}, {param_range.max_value}]"
            )
        
        return True, None
    
    def clamp_to_range(
        self,
        parameter_name: str,
        value: Any,
    ) -> Any:
        """Clamp value to safe range.
        
        Args:
            parameter_name: Parameter name.
            value: Value to clamp.
            
        Returns:
            Clamped value.
            
        Raises:
            ValueError: If parameter not approved.
        """
        if not self.is_parameter_approved(parameter_name):
            raise ValueError(f"Parameter '{parameter_name}' not in approved family")
        
        param_range = self.approved_ranges[parameter_name]
        
        return max(
            param_range.min_value,
            min(value, param_range.max_value)
        )
    
    def get_safe_increment(
        self,
        parameter_name: str,
        current_value: Any,
        direction: int,
    ) -> Any:
        """Get safe incremented value.
        
        Args:
            parameter_name: Parameter name.
            current_value: Current value.
            direction: Direction (+1 for increase, -1 for decrease).
            
        Returns:
            Safe incremented value.
            
        Raises:
            ValueError: If parameter not approved.
        """
        if not self.is_parameter_approved(parameter_name):
            raise ValueError(f"Parameter '{parameter_name}' not in approved family")
        
        param_range = self.approved_ranges[parameter_name]
        
        # Calculate new value
        if direction > 0:
            new_value = current_value + param_range.increment
        else:
            new_value = current_value - param_range.increment
        
        # Clamp to range
        return self.clamp_to_range(parameter_name, new_value)
