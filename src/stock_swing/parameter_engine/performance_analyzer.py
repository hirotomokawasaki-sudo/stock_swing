"""Performance analyzer for evaluating strategy and parameter effectiveness.

This module analyzes historical performance to identify parameter tuning opportunities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PerformanceMetrics:
    """Performance metrics for a strategy or parameter set.
    
    Attributes:
        total_decisions: Total decisions evaluated.
        actionable_decisions: Decisions that passed risk (actionable).
        denied_decisions: Decisions denied by risk.
        win_rate: Percentage of winning trades (if applicable).
        avg_signal_strength: Average signal strength.
        avg_confidence: Average confidence.
        parameter_values: Current parameter values.
        evaluation_period: Time period evaluated.
        sample_size: Number of samples.
    """
    
    total_decisions: int
    actionable_decisions: int
    denied_decisions: int
    win_rate: float | None = None
    avg_signal_strength: float = 0.0
    avg_confidence: float = 0.0
    parameter_values: dict[str, Any] = field(default_factory=dict)
    evaluation_period: str = ""
    sample_size: int = 0


class PerformanceAnalyzer:
    """Analyzer for strategy and parameter performance.
    
    Analyzes historical performance to identify:
    - Signal quality trends
    - Risk denial patterns
    - Parameter effectiveness
    """
    
    def analyze_signal_quality(
        self,
        signals: list[dict[str, Any]],
    ) -> PerformanceMetrics:
        """Analyze signal quality metrics.
        
        Args:
            signals: List of signal records (CandidateSignal-like dicts).
            
        Returns:
            PerformanceMetrics with signal quality analysis.
        """
        if not signals:
            return PerformanceMetrics(
                total_decisions=0,
                actionable_decisions=0,
                denied_decisions=0,
                sample_size=0,
            )
        
        total = len(signals)
        signal_strengths = [s.get("signal_strength", 0.0) for s in signals]
        confidences = [s.get("confidence", 0.0) for s in signals]
        
        avg_signal_strength = sum(signal_strengths) / total if total > 0 else 0.0
        avg_confidence = sum(confidences) / total if total > 0 else 0.0
        
        return PerformanceMetrics(
            total_decisions=total,
            actionable_decisions=total,  # Signals are pre-risk
            denied_decisions=0,
            avg_signal_strength=avg_signal_strength,
            avg_confidence=avg_confidence,
            sample_size=total,
        )
    
    def analyze_risk_denial_patterns(
        self,
        decisions: list[dict[str, Any]],
    ) -> PerformanceMetrics:
        """Analyze risk denial patterns.
        
        Args:
            decisions: List of decision records.
            
        Returns:
            PerformanceMetrics with risk denial analysis.
        """
        if not decisions:
            return PerformanceMetrics(
                total_decisions=0,
                actionable_decisions=0,
                denied_decisions=0,
                sample_size=0,
            )
        
        total = len(decisions)
        actionable = len([d for d in decisions if d.get("risk_state") == "pass"])
        denied = len([d for d in decisions if d.get("risk_state") == "deny"])
        
        signal_strengths = [d.get("signal_strength", 0.0) for d in decisions]
        confidences = [d.get("confidence", 0.0) for d in decisions]
        
        avg_signal_strength = sum(signal_strengths) / total if total > 0 else 0.0
        avg_confidence = sum(confidences) / total if total > 0 else 0.0
        
        return PerformanceMetrics(
            total_decisions=total,
            actionable_decisions=actionable,
            denied_decisions=denied,
            avg_signal_strength=avg_signal_strength,
            avg_confidence=avg_confidence,
            sample_size=total,
        )
    
    def compare_parameter_sets(
        self,
        baseline_metrics: PerformanceMetrics,
        candidate_metrics: PerformanceMetrics,
    ) -> dict[str, Any]:
        """Compare two parameter sets.
        
        Args:
            baseline_metrics: Current/baseline metrics.
            candidate_metrics: Candidate/proposed metrics.
            
        Returns:
            Comparison results with improvement indicators.
        """
        # Calculate improvements
        signal_improvement = (
            candidate_metrics.avg_signal_strength - baseline_metrics.avg_signal_strength
        )
        confidence_improvement = (
            candidate_metrics.avg_confidence - baseline_metrics.avg_confidence
        )
        
        # Calculate actionable rate improvement
        baseline_rate = (
            baseline_metrics.actionable_decisions / baseline_metrics.total_decisions
            if baseline_metrics.total_decisions > 0 else 0.0
        )
        candidate_rate = (
            candidate_metrics.actionable_decisions / candidate_metrics.total_decisions
            if candidate_metrics.total_decisions > 0 else 0.0
        )
        actionable_improvement = candidate_rate - baseline_rate
        
        return {
            "signal_strength_improvement": signal_improvement,
            "confidence_improvement": confidence_improvement,
            "actionable_rate_improvement": actionable_improvement,
            "baseline_signal_strength": baseline_metrics.avg_signal_strength,
            "candidate_signal_strength": candidate_metrics.avg_signal_strength,
            "baseline_actionable_rate": baseline_rate,
            "candidate_actionable_rate": candidate_rate,
            "is_improvement": (
                signal_improvement > 0 or 
                confidence_improvement > 0 or 
                actionable_improvement > 0
            ),
        }
