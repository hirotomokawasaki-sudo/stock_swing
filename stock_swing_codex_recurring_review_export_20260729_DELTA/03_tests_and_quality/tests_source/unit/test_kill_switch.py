"""Tests for kill switch."""

import tempfile
from pathlib import Path

import pytest

from stock_swing.safety import KillSwitch, KillSwitchState


def test_kill_switch_init_active() -> None:
    """Test kill switch initializes as active."""
    ks = KillSwitch()
    
    assert ks.is_active() is True
    assert ks.get_state() == KillSwitchState.ACTIVE


def test_kill_switch_trigger() -> None:
    """Test triggering kill switch."""
    ks = KillSwitch()
    
    ks.trigger(reason="Emergency stop", triggered_by="operator")
    
    assert ks.is_active() is False
    assert ks.get_state() == KillSwitchState.TRIGGERED


def test_kill_switch_check_active() -> None:
    """Test check passes when active."""
    ks = KillSwitch()
    
    # Should not raise
    ks.check()


def test_kill_switch_check_triggered() -> None:
    """Test check raises when triggered."""
    ks = KillSwitch()
    ks.trigger(reason="Test", triggered_by="test")
    
    with pytest.raises(RuntimeError, match="Kill switch is TRIGGERED"):
        ks.check()


def test_kill_switch_reset() -> None:
    """Test resetting kill switch."""
    ks = KillSwitch()
    
    # Trigger
    ks.trigger(reason="Test", triggered_by="test")
    assert ks.is_active() is False
    
    # Reset
    ks.reset(operator_id="admin")
    assert ks.is_active() is True


def test_kill_switch_trigger_history() -> None:
    """Test trigger history tracking."""
    ks = KillSwitch()
    
    ks.trigger(reason="First trigger", triggered_by="operator1")
    ks.reset()
    ks.trigger(reason="Second trigger", triggered_by="operator2")
    
    history = ks.get_trigger_history()
    
    assert len(history) == 2
    assert history[0].reason == "First trigger"
    assert history[1].reason == "Second trigger"


def test_kill_switch_persistence() -> None:
    """Test kill switch state persistence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "kill_switch.state"
        
        # Create kill switch and trigger
        ks1 = KillSwitch(state_file=state_file)
        ks1.trigger(reason="Test", triggered_by="test")
        
        # Create new instance (should load triggered state)
        ks2 = KillSwitch(state_file=state_file)
        assert ks2.get_state() == KillSwitchState.TRIGGERED
        
        # Reset and verify persistence
        ks2.reset()
        ks3 = KillSwitch(state_file=state_file)
        assert ks3.get_state() == KillSwitchState.ACTIVE


def test_kill_switch_invalid_state_file() -> None:
    """Test kill switch handles invalid state file (fail-safe)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "kill_switch.state"
        
        # Write invalid content
        state_file.write_text("invalid_content")
        
        # Should fail-safe to triggered
        ks = KillSwitch(state_file=state_file)
        assert ks.get_state() == KillSwitchState.TRIGGERED
