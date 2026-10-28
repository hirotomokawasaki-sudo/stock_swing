"""
Risk monitoring and kill switch implementation.

Critical safety system for portfolio protection.
- Drawdown monitoring (-8% warning, -12% kill switch)
- Daily loss limits (-3% per day)
- Automatic position liquidation
- Alert notifications

Author: OpenClaw Assistant
Created: 2026-05-02
"""

from __future__ import annotations

import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RiskMonitor:
    """
    Portfolio-level risk monitoring with automatic kill switch.
    
    Features:
    - Real-time drawdown tracking
    - Kill switch at -12% drawdown
    - Warning alerts at -8% drawdown
    - Daily loss limit enforcement (-3% per day)
    - Automatic position liquidation
    - Detailed event logging
    
    Usage:
        risk_monitor = RiskMonitor(equity_start=1_000_000)
        
        # Every execution
        status = risk_monitor.check_drawdown(current_equity)
        
        if status == 'KILL_SWITCH_ACTIVATED':
            # Stop trading, liquidate all positions
            sys.exit(1)
    """
    
    def __init__(self,
                 equity_start: float,
                 kill_switch_threshold: float = -0.12,
                 warning_threshold: float = -0.08,
                 daily_loss_limit: float = -0.03,
                 state_file: Optional[Path] = None):
        """
        Initialize risk monitor.
        
        Args:
            equity_start: Starting equity for drawdown calculation
            kill_switch_threshold: DD threshold for kill switch (default -12%)
            warning_threshold: DD threshold for warning alert (default -8%)
            daily_loss_limit: Max daily loss (default -3%)
            state_file: Path to state persistence file
        """
        self.equity_start = float(equity_start)
        self.equity_peak = float(equity_start)
        self.kill_switch_threshold = float(kill_switch_threshold)
        self.warning_threshold = float(warning_threshold)
        self.daily_loss_limit = float(daily_loss_limit)
        
        # Daily tracking
        self.current_date = date.today()
        self.equity_day_start = float(equity_start)
        
        # State
        self.kill_switch_activated = False
        self.warnings_sent = set()
        self.state_file = state_file or Path('data/risk_monitor_state.json')
        
        # Load state if exists
        self._load_state()
        
        logger.info(
            f"RiskMonitor initialized: "
            f"start=${self.equity_start:,.0f}, "
            f"peak=${self.equity_peak:,.0f}, "
            f"kill_switch={self.kill_switch_threshold:.1%}, "
            f"warning={self.warning_threshold:.1%}, "
            f"daily_limit={self.daily_loss_limit:.1%}"
        )
    
    def check_drawdown(self, current_equity: float) -> str:
        """
        Check current drawdown and trigger alerts/kill switch if needed.
        
        Args:
            current_equity: Current account equity
            
        Returns:
            'KILL_SWITCH_ACTIVATED' | 'WARNING' | 'OK'
        """
        current_equity = float(current_equity)
        
        # Check if new day (reset daily tracking)
        today = date.today()
        if today != self.current_date:
            self.current_date = today
            self.equity_day_start = current_equity
            logger.info(f"New day: Day start equity = ${current_equity:,.0f}")
        
        # Update peak
        if current_equity > self.equity_peak:
            old_peak = self.equity_peak
            self.equity_peak = current_equity
            logger.info(f"New equity peak: ${old_peak:,.0f} → ${self.equity_peak:,.0f}")
            # Clear warnings on recovery
            self.warnings_sent.clear()
        
        # Calculate drawdown from peak
        drawdown = (current_equity - self.equity_peak) / self.equity_peak
        
        # Calculate daily loss
        daily_loss = (current_equity - self.equity_day_start) / self.equity_day_start
        
        # Save state
        self._save_state()
        
        # Critical: Kill switch
        if drawdown <= self.kill_switch_threshold:
            logger.critical(
                f"🚨 KILL SWITCH ACTIVATED: "
                f"Drawdown {drawdown:.2%} <= threshold {self.kill_switch_threshold:.2%}"
            )
            self.trigger_kill_switch(current_equity, drawdown)
            return 'KILL_SWITCH_ACTIVATED'
        
        # Daily loss limit
        if daily_loss <= self.daily_loss_limit:
            logger.error(
                f"❌ DAILY LOSS LIMIT EXCEEDED: "
                f"Daily loss {daily_loss:.2%} <= limit {self.daily_loss_limit:.2%}"
            )
            self.trigger_daily_loss_limit(current_equity, daily_loss)
            return 'DAILY_LOSS_LIMIT_EXCEEDED'
        
        # Warning
        if drawdown <= self.warning_threshold:
            if 'warning_alert' not in self.warnings_sent:
                logger.warning(
                    f"⚠️ DRAWDOWN WARNING: "
                    f"Drawdown {drawdown:.2%} <= threshold {self.warning_threshold:.2%}"
                )
                self.send_warning_alert(current_equity, drawdown)
                self.warnings_sent.add('warning_alert')
            return 'WARNING'
        
        # All OK
        logger.info(
            f"Risk check OK: "
            f"DD={drawdown:+.2%}, Daily={daily_loss:+.2%}, "
            f"Equity=${current_equity:,.0f}"
        )
        return 'OK'
    
    def trigger_kill_switch(self, current_equity: float, drawdown: float):
        """
        Activate kill switch: mark for position liquidation.
        
        Actual liquidation happens in paper_demo.py
        
        Args:
            current_equity: Current equity
            drawdown: Current drawdown percentage
        """
        if self.kill_switch_activated:
            logger.warning("Kill switch already activated")
            return
        
        self.kill_switch_activated = True
        self._save_state()
        
        # Log critical event
        logger.critical("=" * 60)
        logger.critical("🚨 KILL SWITCH ACTIVATED")
        logger.critical("=" * 60)
        logger.critical(f"Current equity: ${current_equity:,.2f}")
        logger.critical(f"Peak equity: ${self.equity_peak:,.2f}")
        logger.critical(f"Drawdown: {drawdown:.2%}")
        logger.critical(f"Threshold: {self.kill_switch_threshold:.2%}")
        logger.critical("Action: Liquidate all positions, disable trading")
        logger.critical("=" * 60)
        
        # Send critical alert
        self.send_critical_alert(current_equity, drawdown)
    
    def trigger_daily_loss_limit(self, current_equity: float, daily_loss: float):
        """
        Daily loss limit exceeded: stop trading for today.
        
        Args:
            current_equity: Current equity
            daily_loss: Daily loss percentage
        """
        logger.error("=" * 60)
        logger.error("❌ DAILY LOSS LIMIT EXCEEDED")
        logger.error("=" * 60)
        logger.error(f"Day start equity: ${self.equity_day_start:,.2f}")
        logger.error(f"Current equity: ${current_equity:,.2f}")
        logger.error(f"Daily loss: {daily_loss:.2%}")
        logger.error(f"Limit: {self.daily_loss_limit:.2%}")
        logger.error("Action: Stop trading for today")
        logger.error("=" * 60)
        
        # Send alert
        self.send_daily_loss_alert(current_equity, daily_loss)
    
    def send_warning_alert(self, equity: float, drawdown: float):
        """Send warning alert (to be implemented with AlertManager)."""
        message = (
            f"⚠️ Drawdown Warning\n\n"
            f"Current equity: ${equity:,.2f}\n"
            f"Peak equity: ${self.equity_peak:,.2f}\n"
            f"Drawdown: {drawdown:.2%}\n"
            f"Warning threshold: {self.warning_threshold:.2%}\n\n"
            f"Kill switch activates at: {self.kill_switch_threshold:.2%}\n"
            f"Action: Monitor closely"
        )
        logger.warning(message)
        # TODO: Send via AlertManager when implemented
    
    def send_critical_alert(self, equity: float, drawdown: float):
        """Send critical kill switch alert (to be implemented with AlertManager)."""
        message = (
            f"🚨 KILL SWITCH ACTIVATED\n\n"
            f"Current equity: ${equity:,.2f}\n"
            f"Peak equity: ${self.equity_peak:,.2f}\n"
            f"Drawdown: {drawdown:.2%}\n"
            f"Threshold: {self.kill_switch_threshold:.2%}\n\n"
            f"All positions will be liquidated.\n"
            f"Trading is DISABLED.\n"
            f"Manual intervention required to resume."
        )
        logger.critical(message)
        # TODO: Send via AlertManager when implemented
    
    def send_daily_loss_alert(self, equity: float, daily_loss: float):
        """Send daily loss limit alert (to be implemented with AlertManager)."""
        message = (
            f"❌ Daily Loss Limit Exceeded\n\n"
            f"Day start equity: ${self.equity_day_start:,.2f}\n"
            f"Current equity: ${equity:,.2f}\n"
            f"Daily loss: {daily_loss:.2%}\n"
            f"Limit: {self.daily_loss_limit:.2%}\n\n"
            f"Trading stopped for today.\n"
            f"Will resume tomorrow."
        )
        logger.error(message)
        # TODO: Send via AlertManager when implemented
    
    def _save_state(self):
        """Save state to file for persistence."""
        import json
        
        state = {
            'equity_start': self.equity_start,
            'equity_peak': self.equity_peak,
            'equity_day_start': self.equity_day_start,
            'current_date': self.current_date.isoformat(),
            'kill_switch_activated': self.kill_switch_activated,
            'warnings_sent': list(self.warnings_sent),
        }
        
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def _load_state(self):
        """Load state from file if exists."""
        import json
        
        if not self.state_file.exists():
            return
        
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            
            self.equity_peak = float(state.get('equity_peak', self.equity_start))
            self.equity_day_start = float(state.get('equity_day_start', self.equity_start))
            
            date_str = state.get('current_date')
            if date_str:
                self.current_date = date.fromisoformat(date_str)
            
            self.kill_switch_activated = bool(state.get('kill_switch_activated', False))
            self.warnings_sent = set(state.get('warnings_sent', []))
            
            logger.info(f"State loaded from {self.state_file}")
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
    
    def get_status(self) -> dict:
        """Get current risk monitor status."""
        current_dd = (self.equity_peak - self.equity_start) / self.equity_start if self.equity_start > 0 else 0
        
        return {
            'equity_start': self.equity_start,
            'equity_peak': self.equity_peak,
            'equity_day_start': self.equity_day_start,
            'current_date': self.current_date.isoformat(),
            'current_drawdown_from_start': current_dd,
            'kill_switch_activated': self.kill_switch_activated,
            'kill_switch_threshold': self.kill_switch_threshold,
            'warning_threshold': self.warning_threshold,
            'daily_loss_limit': self.daily_loss_limit,
            'warnings_sent': list(self.warnings_sent),
        }
    
    def reset_kill_switch(self):
        """
        Reset kill switch (manual intervention only).
        
        WARNING: Only use this after investigating the cause and
        confirming it's safe to resume trading.
        """
        logger.warning("Kill switch manually reset")
        self.kill_switch_activated = False
        self.warnings_sent.clear()
        self._save_state()
