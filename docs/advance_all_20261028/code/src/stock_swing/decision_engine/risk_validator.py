"""Risk validator for evaluating candidate signals.

This module implements risk checks that determine whether a candidate signal
can proceed to actionable decision or must be denied/reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from stock_swing.strategy_engine.base_strategy import CandidateSignal


class RiskState(Enum):
    """Risk validation state."""
    
    PASS = "pass"  # Risk checks passed
    DENY = "deny"  # Risk checks failed, must deny
    REVIEW = "review"  # Manual review required


@dataclass
class RiskValidationResult:
    """Result of risk validation.
    
    Attributes:
        risk_state: Overall risk state (pass/deny/review).
        deny_reasons: List of reasons if denied.
        review_notes: Notes for manual review.
        checks_performed: List of checks that were performed.
    """
    
    risk_state: RiskState
    deny_reasons: list[str] = field(default_factory=list)
    review_notes: list[str] = field(default_factory=list)
    checks_performed: list[str] = field(default_factory=list)


class RiskValidator:
    """Risk validator for candidate signals.
    
    Implements risk checks to determine if a candidate signal should:
    - Pass to actionable decision
    - Be denied
    - Require manual review
    """
    
    def __init__(
        self,
        min_signal_strength: float = 0.6,
        min_confidence: float = 0.5,
        max_position_size: int = 100,
    ):
        """Initialize risk validator.
        
        Args:
            min_signal_strength: Minimum signal strength to pass.
            min_confidence: Minimum confidence to pass.
            max_position_size: Maximum position size (shares).
        """
        self.min_signal_strength = min_signal_strength
        self.min_confidence = min_confidence
        self.max_position_size = max_position_size
    
    def validate(
        self,
        candidate: CandidateSignal,
        current_positions: dict[str, int] | None = None,
    ) -> RiskValidationResult:
        """Validate a candidate signal.
        
        Args:
            candidate: Candidate signal to validate.
            current_positions: Current positions (symbol → quantity).
            
        Returns:
            RiskValidationResult indicating pass/deny/review.
        """
        current_positions = current_positions or {}
        checks_performed = []
        deny_reasons = []
        review_notes = []
        
        # Check 1: Signal strength
        checks_performed.append("signal_strength")
        if candidate.signal_strength < self.min_signal_strength:
            deny_reasons.append(
                f"signal_strength {candidate.signal_strength:.2f} below minimum {self.min_signal_strength:.2f}"
            )
        
        # Check 2: Confidence
        checks_performed.append("confidence")
        if candidate.confidence < self.min_confidence:
            deny_reasons.append(
                f"confidence {candidate.confidence:.2f} below minimum {self.min_confidence:.2f}"
            )
        
        # Check 3: Action validity
        checks_performed.append("action_validity")
        if candidate.action not in {"buy", "sell", "hold"}:
            deny_reasons.append(f"invalid action: {candidate.action}")
        
        # Check 4: Data quality — block signals from stale or insufficient price data
        checks_performed.append("data_quality")
        BLOCKING_QUALITY_FLAGS = {"stale_data", "insufficient_bars", "insufficient_price_data"}
        if isinstance(candidate.metadata, dict):
            signal_flags = set(candidate.metadata.get("quality_flags") or [])
            blocking = signal_flags & BLOCKING_QUALITY_FLAGS
            if blocking:
                deny_reasons.append(
                    f"data_quality: blocking quality flags present: {sorted(blocking)}"
                )

        # Check 5: Symbol validity
        # NOTE: max_position_size is a deprecated argument; actual sizing is handled
        # by PositionSizingPolicy in PaperExecutor, not here.
        checks_performed.append("symbol_validity")
        if not candidate.symbol or len(candidate.symbol) < 1 or len(candidate.symbol) > 10:
            deny_reasons.append(f"invalid symbol: {candidate.symbol}")
        
        # Determine risk state
        if deny_reasons:
            risk_state = RiskState.DENY
        else:
            risk_state = RiskState.PASS
        
        return RiskValidationResult(
            risk_state=risk_state,
            deny_reasons=deny_reasons,
            review_notes=review_notes,
            checks_performed=checks_performed,
        )
