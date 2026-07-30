"""Tests for safe parameter ranges."""

import pytest

from stock_swing.parameter_engine import (
    APPROVED_REDACTED_ACCOUNT_RANGES,
    SafeRangeValidator,
)


def test_safe_range_validator_approved_parameters() -> None:
    """Test checking approved parameters."""
    validator = SafeRangeValidator()
    
    assert validator.is_parameter_approved("min_signal_strength") is True
    assert validator.is_parameter_approved("min_confidence") is True
    assert validator.is_parameter_approved("max_position_size") is True
    assert validator.is_parameter_approved("unknown_param") is False


def test_safe_range_validator_validate_value_valid() -> None:
    """Test validating value within range."""
    validator = SafeRangeValidator()
    
    is_valid, error = validator.validate_value("min_signal_strength", 0.7)
    
    assert is_valid is True
    assert error is None


def test_safe_range_validator_validate_value_below_min() -> None:
    """Test validating value below minimum."""
    validator = SafeRangeValidator()
    
    # R4-B 2026-07-02: min lowered from 0.4 to 0.3; use 0.25 to test below-min
    is_valid, error = validator.validate_value("min_signal_strength", 0.25)
    
    assert is_valid is False
    assert "outside safe range" in error


def test_safe_range_validator_validate_value_above_max() -> None:
    """Test validating value above maximum."""
    validator = SafeRangeValidator()
    
    is_valid, error = validator.validate_value("min_signal_strength", 0.95)
    
    assert is_valid is False
    assert "outside safe range" in error


def test_safe_range_validator_validate_unapproved() -> None:
    """Test validating unapproved parameter."""
    validator = SafeRangeValidator()
    
    is_valid, error = validator.validate_value("unapproved_param", 0.5)
    
    assert is_valid is False
    assert "not in approved family" in error


def test_safe_range_validator_type_mismatch() -> None:
    """Test validating wrong type."""
    validator = SafeRangeValidator()
    
    # min_signal_strength expects float, not int
    is_valid, error = validator.validate_value("max_position_size", 75.5)
    
    assert is_valid is False
    assert "type mismatch" in error.lower()


def test_safe_range_validator_clamp_to_range() -> None:
    """Test clamping value to range."""
    validator = SafeRangeValidator()
    
    # Below min: R4-B new min is 0.3
    clamped = validator.clamp_to_range("min_signal_strength", 0.2)
    assert clamped == 0.3
    
    # Above max
    clamped = validator.clamp_to_range("min_signal_strength", 0.95)
    assert clamped == 0.9
    
    # Within range
    clamped = validator.clamp_to_range("min_signal_strength", 0.7)
    assert clamped == 0.7


def test_safe_range_validator_clamp_unapproved() -> None:
    """Test clamping unapproved parameter fails."""
    validator = SafeRangeValidator()
    
    with pytest.raises(ValueError, match="not in approved family"):
        validator.clamp_to_range("unapproved_param", 0.5)


def test_safe_range_validator_get_safe_increment() -> None:
    """Test getting safe incremented value."""
    validator = SafeRangeValidator()
    
    # Increase
    new_value = validator.get_safe_increment("min_signal_strength", 0.6, direction=1)
    assert new_value == 0.65
    
    # Decrease
    new_value = validator.get_safe_increment("min_signal_strength", 0.6, direction=-1)
    assert abs(new_value - 0.55) < 0.001


def test_safe_range_validator_increment_clamped() -> None:
    """Test increment is clamped to range."""
    validator = SafeRangeValidator()
    
    # At max, increment should clamp
    new_value = validator.get_safe_increment("min_signal_strength", 0.9, direction=1)
    assert new_value == 0.9  # Clamped to max
    
    # At min, decrement should clamp: R4-B new min is 0.3
    new_value = validator.get_safe_increment("min_signal_strength", 0.3, direction=-1)
    assert new_value == 0.3  # Clamped to min


def test_approved_parameter_ranges_structure() -> None:
    """Test approved parameter ranges structure."""
    assert "min_signal_strength" in APPROVED_REDACTED_ACCOUNT_RANGES
    assert "min_confidence" in APPROVED_REDACTED_ACCOUNT_RANGES
    assert "max_position_size" in APPROVED_REDACTED_ACCOUNT_RANGES
    
    # Verify range structure
    range_obj = APPROVED_REDACTED_ACCOUNT_RANGES["min_signal_strength"]
    assert hasattr(range_obj, "min_value")
    assert hasattr(range_obj, "max_value")
    assert hasattr(range_obj, "default_value")
    assert hasattr(range_obj, "increment")
    assert hasattr(range_obj, "value_type")
    
    # Verify ranges are sensible
    assert range_obj.min_value < range_obj.default_value < range_obj.max_value


def test_no_auto_apply_in_ranges() -> None:
    """Test that ranges are informational only (no auto-apply)."""
    validator = SafeRangeValidator()
    
    # Validation should not modify state
    current_value = 0.6
    validator.validate_value("min_signal_strength", 0.7)
    
    # Original value unchanged (validation is read-only)
    assert current_value == 0.6
    
    # Clamping returns new value but doesn't modify state
    new_value = validator.clamp_to_range("min_signal_strength", 0.95)
    assert new_value == 0.9
    assert current_value == 0.6  # Original unchanged
