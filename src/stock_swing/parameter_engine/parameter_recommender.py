"""Parameter recommender for strategy and risk parameter tuning suggestions.

This module generates parameter recommendations based on performance analysis.
All recommendations are advisory only - no auto-apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from stock_swing.parameter_engine.performance_analyzer import (
    PerformanceAnalyzer,
    PerformanceMetrics,
)


class RecommendationType(Enum):
    """Type of parameter recommendation."""
    
    STRATEGY_THRESHOLD = "strategy_threshold"  # Strategy threshold adjustment
    RISK_THRESHOLD = "risk_threshold"  # Risk threshold adjustment
    FEATURE_WEIGHT = "feature_weight"  # Feature weighting adjustment
    POSITION_SIZE = "position_size"  # Position sizing adjustment
    TIME_HORIZON = "time_horizon"  # Time horizon adjustment


@dataclass
class ParameterRecommendation:
    """Parameter tuning recommendation.
    
    Attributes:
        recommendation_id: Unique identifier.
        recommendation_type: Type of recommendation.
        generated_at: UTC timestamp when generated.
        parameter_name: Parameter to adjust.
        current_value: Current parameter value.
        recommended_value: Recommended new value.
        rationale: Human-readable rationale.
        confidence: Recommendation confidence [0.0, 1.0].
        impact_estimate: Estimated impact (e.g., "+5% signal quality").
        supporting_metrics: Metrics supporting recommendation.
        requires_approval: Whether operator approval required (always True).
    """
    
    recommendation_id: str
    recommendation_type: RecommendationType
    generated_at: datetime
    parameter_name: str
    current_value: Any
    recommended_value: Any
    rationale: str
    confidence: float
    impact_estimate: str
    supporting_metrics: dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = True  # Always True - no auto-apply


class ParameterRecommender:
    """Parameter recommender for strategy and risk tuning.
    
    Generates recommendations based on performance analysis.
    CRITICAL: All recommendations are advisory only. No auto-apply.
    """
    
    def __init__(
        self,
        performance_analyzer: PerformanceAnalyzer | None = None,
        min_confidence: float = 0.6,
    ):
        """Initialize parameter recommender.
        
        Args:
            performance_analyzer: Performance analyzer instance.
            min_confidence: Minimum confidence for recommendations.
        """
        self.performance_analyzer = performance_analyzer or PerformanceAnalyzer()
        self.min_confidence = min_confidence
        self._recommendation_counter = 0
    
    def recommend_strategy_thresholds(
        self,
        current_params: dict[str, Any],
        performance_metrics: PerformanceMetrics,
    ) -> list[ParameterRecommendation]:
        """Recommend strategy threshold adjustments.
        
        Args:
            current_params: Current strategy parameters.
            performance_metrics: Performance metrics for current parameters.
            
        Returns:
            List of recommendations.
        """
        recommendations = []
        
        # Check signal strength threshold
        if "min_signal_strength" in current_params:
            current_threshold = current_params["min_signal_strength"]
            avg_signal = performance_metrics.avg_signal_strength
            
            # If average signal strength is significantly above threshold,
            # recommend raising threshold for higher quality
            if avg_signal > current_threshold + 0.15:
                new_threshold = min(current_threshold + 0.05, 0.9)
                
                rec = self._create_recommendation(
                    rec_type=RecommendationType.STRATEGY_THRESHOLD,
                    param_name="min_signal_strength",
                    current_value=current_threshold,
                    recommended_value=new_threshold,
                    rationale=(
                        f"Average signal strength ({avg_signal:.2%}) is significantly "
                        f"above threshold ({current_threshold:.2%}). Raising threshold "
                        f"may improve signal quality."
                    ),
                    confidence=0.75,
                    impact_estimate="Higher quality signals, potentially fewer trades",
                    metrics={"avg_signal_strength": avg_signal},
                )
                recommendations.append(rec)
            
            # If too many denials, recommend lowering threshold
            denial_rate = (
                performance_metrics.denied_decisions / performance_metrics.total_decisions
                if performance_metrics.total_decisions > 0 else 0.0
            )
            
            if denial_rate > 0.5 and current_threshold > 0.5:
                new_threshold = max(current_threshold - 0.05, 0.4)
                
                rec = self._create_recommendation(
                    rec_type=RecommendationType.STRATEGY_THRESHOLD,
                    param_name="min_signal_strength",
                    current_value=current_threshold,
                    recommended_value=new_threshold,
                    rationale=(
                        f"High denial rate ({denial_rate:.1%}). Lowering threshold "
                        f"may reduce denials."
                    ),
                    confidence=0.70,
                    impact_estimate="More signals, potentially lower quality",
                    metrics={"denial_rate": denial_rate},
                )
                recommendations.append(rec)
        
        return recommendations
    
    def recommend_risk_thresholds(
        self,
        current_params: dict[str, Any],
        performance_metrics: PerformanceMetrics,
    ) -> list[ParameterRecommendation]:
        """Recommend risk threshold adjustments.
        
        Args:
            current_params: Current risk parameters.
            performance_metrics: Performance metrics.
            
        Returns:
            List of recommendations.
        """
        recommendations = []
        
        # Check min_confidence threshold
        if "min_confidence" in current_params:
            current_threshold = current_params["min_confidence"]
            avg_confidence = performance_metrics.avg_confidence
            
            # If average confidence is well above threshold, recommend raising
            if avg_confidence > current_threshold + 0.2:
                new_threshold = min(current_threshold + 0.05, 0.85)
                
                rec = self._create_recommendation(
                    rec_type=RecommendationType.RISK_THRESHOLD,
                    param_name="min_confidence",
                    current_value=current_threshold,
                    recommended_value=new_threshold,
                    rationale=(
                        f"Average confidence ({avg_confidence:.2%}) is well above "
                        f"threshold ({current_threshold:.2%}). Raising threshold "
                        f"may improve risk filtering."
                    ),
                    confidence=0.70,
                    impact_estimate="Stricter risk filtering, fewer approvals",
                    metrics={"avg_confidence": avg_confidence},
                )
                recommendations.append(rec)
        
        return recommendations
    
    def recommend_position_sizing(
        self,
        current_params: dict[str, Any],
        performance_metrics: PerformanceMetrics,
    ) -> list[ParameterRecommendation]:
        """Recommend position sizing adjustments.
        
        Args:
            current_params: Current position sizing parameters.
            performance_metrics: Performance metrics.
            
        Returns:
            List of recommendations.
        """
        recommendations = []
        
        # Check max_position_size
        if "max_position_size" in current_params:
            current_max = current_params["max_position_size"]
            
            # Conservative recommendation: if high quality signals,
            # consider slightly larger positions
            if performance_metrics.avg_signal_strength > 0.8:
                new_max = min(current_max + 20, 150)
                
                rec = self._create_recommendation(
                    rec_type=RecommendationType.POSITION_SIZE,
                    param_name="max_position_size",
                    current_value=current_max,
                    recommended_value=new_max,
                    rationale=(
                        f"High average signal strength ({performance_metrics.avg_signal_strength:.2%}) "
                        f"suggests signal quality supports slightly larger positions."
                    ),
                    confidence=0.65,
                    impact_estimate="Larger positions for high-quality signals",
                    metrics={"avg_signal_strength": performance_metrics.avg_signal_strength},
                )
                recommendations.append(rec)
        
        return recommendations
    
    def generate_recommendations(
        self,
        current_strategy_params: dict[str, Any],
        current_risk_params: dict[str, Any],
        performance_metrics: PerformanceMetrics,
    ) -> list[ParameterRecommendation]:
        """Generate all applicable recommendations.
        
        Args:
            current_strategy_params: Current strategy parameters.
            current_risk_params: Current risk parameters.
            performance_metrics: Performance metrics.
            
        Returns:
            List of all recommendations.
        """
        recommendations = []
        
        # Strategy threshold recommendations
        recommendations.extend(
            self.recommend_strategy_thresholds(current_strategy_params, performance_metrics)
        )
        
        # Risk threshold recommendations
        recommendations.extend(
            self.recommend_risk_thresholds(current_risk_params, performance_metrics)
        )
        
        # Position sizing recommendations
        recommendations.extend(
            self.recommend_position_sizing(current_risk_params, performance_metrics)
        )
        
        # Filter by minimum confidence
        recommendations = [
            r for r in recommendations 
            if r.confidence >= self.min_confidence
        ]
        
        return recommendations
    
    def _create_recommendation(
        self,
        rec_type: RecommendationType,
        param_name: str,
        current_value: Any,
        recommended_value: Any,
        rationale: str,
        confidence: float,
        impact_estimate: str,
        metrics: dict[str, Any],
    ) -> ParameterRecommendation:
        """Create a parameter recommendation.
        
        Args:
            rec_type: Recommendation type.
            param_name: Parameter name.
            current_value: Current value.
            recommended_value: Recommended value.
            rationale: Rationale.
            confidence: Confidence.
            impact_estimate: Impact estimate.
            metrics: Supporting metrics.
            
        Returns:
            ParameterRecommendation.
        """
        self._recommendation_counter += 1
        rec_id = f"param-rec-{self._recommendation_counter:04d}"
        
        return ParameterRecommendation(
            recommendation_id=rec_id,
            recommendation_type=rec_type,
            generated_at=datetime.now(timezone.utc),
            parameter_name=param_name,
            current_value=current_value,
            recommended_value=recommended_value,
            rationale=rationale,
            confidence=confidence,
            impact_estimate=impact_estimate,
            supporting_metrics=metrics,
            requires_approval=True,  # Always True - no auto-apply
        )
