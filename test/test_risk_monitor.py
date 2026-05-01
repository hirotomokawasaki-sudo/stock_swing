"""
Unit tests for RiskMonitor class.

Tests:
- Drawdown calculation
- Kill switch trigger
- Warning alerts
- Daily loss limit
- State persistence

Run: pytest test/test_risk_monitor.py -v
"""

import pytest
from pathlib import Path
from datetime import date
import tempfile
import shutil

from stock_swing.risk.risk_monitor import RiskMonitor


@pytest.fixture
def temp_state_file():
    """Create temporary state file."""
    temp_dir = Path(tempfile.mkdtemp())
    state_file = temp_dir / 'risk_state.json'
    yield state_file
    shutil.rmtree(temp_dir)


def test_risk_monitor_init():
    """Test RiskMonitor initialization."""
    rm = RiskMonitor(equity_start=1_000_000)
    
    assert rm.equity_start == 1_000_000
    assert rm.equity_peak == 1_000_000
    assert rm.kill_switch_threshold == -0.12
    assert rm.warning_threshold == -0.08
    assert rm.daily_loss_limit == -0.03
    assert rm.kill_switch_activated == False


def test_drawdown_ok():
    """Test normal operation (no drawdown)."""
    rm = RiskMonitor(equity_start=1_000_000)
    
    # Small drawdown: -2%
    status = rm.check_drawdown(980_000)
    assert status == 'OK'
    assert rm.kill_switch_activated == False


def test_drawdown_warning():
    """Test warning alert at -8%."""
    rm = RiskMonitor(equity_start=1_000_000)
    
    # Drawdown: -10% (below -8% warning threshold)
    status = rm.check_drawdown(900_000)
    assert status == 'WARNING'
    assert rm.kill_switch_activated == False
    assert 'warning_alert' in rm.warnings_sent


def test_kill_switch_trigger():
    """Test kill switch activation at -12%."""
    rm = RiskMonitor(equity_start=1_000_000)
    
    # Drawdown: -15% (below -12% kill switch)
    status = rm.check_drawdown(850_000)
    assert status == 'KILL_SWITCH_ACTIVATED'
    assert rm.kill_switch_activated == True


def test_peak_update():
    """Test equity peak tracking."""
    rm = RiskMonitor(equity_start=1_000_000)
    
    # Equity increases
    rm.check_drawdown(1_050_000)
    assert rm.equity_peak == 1_050_000
    
    # Drawdown from new peak: -5%
    status = rm.check_drawdown(997_500)
    assert status == 'OK'
    
    # Further increase
    rm.check_drawdown(1_100_000)
    assert rm.equity_peak == 1_100_000


def test_daily_loss_limit():
    """Test daily loss limit enforcement."""
    rm = RiskMonitor(equity_start=1_000_000)
    rm.equity_day_start = 1_000_000
    
    # Daily loss: -3.5% (exceeds -3% limit)
    status = rm.check_drawdown(965_000)
    assert status == 'DAILY_LOSS_LIMIT_EXCEEDED'


def test_state_persistence(temp_state_file):
    """Test state save and load."""
    # Create monitor and trigger warning
    rm1 = RiskMonitor(equity_start=1_000_000, state_file=temp_state_file)
    rm1.check_drawdown(900_000)  # -10% warning
    
    assert rm1.equity_peak == 1_000_000
    assert 'warning_alert' in rm1.warnings_sent
    
    # Load state in new instance
    rm2 = RiskMonitor(equity_start=1_000_000, state_file=temp_state_file)
    
    assert rm2.equity_peak == 1_000_000
    assert 'warning_alert' in rm2.warnings_sent


def test_warning_only_once():
    """Test warning is sent only once until recovery."""
    rm = RiskMonitor(equity_start=1_000_000)
    
    # First warning
    status1 = rm.check_drawdown(900_000)
    assert status1 == 'WARNING'
    assert len(rm.warnings_sent) == 1
    
    # Second check (still in warning zone)
    status2 = rm.check_drawdown(905_000)
    assert status2 == 'WARNING'
    assert len(rm.warnings_sent) == 1  # Still only 1
    
    # Recovery above warning threshold
    rm.check_drawdown(950_000)  # -5% DD, above -8%
    assert len(rm.warnings_sent) == 1  # Still set
    
    # New peak clears warnings
    rm.check_drawdown(1_010_000)
    assert len(rm.warnings_sent) == 0  # Cleared


def test_get_status():
    """Test status reporting."""
    rm = RiskMonitor(equity_start=1_000_000)
    rm.check_drawdown(950_000)
    
    status = rm.get_status()
    
    assert status['equity_start'] == 1_000_000
    assert status['equity_peak'] == 1_000_000
    assert status['kill_switch_activated'] == False
    assert status['kill_switch_threshold'] == -0.12


def test_reset_kill_switch(temp_state_file):
    """Test manual kill switch reset."""
    rm = RiskMonitor(equity_start=1_000_000, state_file=temp_state_file)
    
    # Trigger kill switch
    rm.check_drawdown(850_000)
    assert rm.kill_switch_activated == True
    
    # Manual reset
    rm.reset_kill_switch()
    assert rm.kill_switch_activated == False
    assert len(rm.warnings_sent) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
