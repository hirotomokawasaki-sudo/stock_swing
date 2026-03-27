"""Tests for parameter recommendation engine."""

from stock_swing.parameter_engine import (
    ParameterRecommender,
    PerformanceAnalyzer,
    PerformanceMetrics,
    RecommendationType,
)


def test_performance_analyzer_signal_quality() -> None:
    """Test performance analyzer signal quality analysis."""
    analyzer = PerformanceAnalyzer()
    
    signals = [
        {"signal_strength": 0.8, "confidence": 0.75},
        {"signal_strength": 0.85, "confidence": 0.80},
        {"signal_strength": 0.75, "confidence": 0.70},
    ]
    
    metrics = analyzer.analyze_signal_quality(signals)
    
    assert metrics.total_decisions == 3
    assert abs(metrics.avg_signal_strength - 0.8) < 0.001
    assert abs(metrics.avg_confidence - 0.75) < 0.001


def test_performance_analyzer_risk_denial() -> None:
    """Test performance analyzer risk denial analysis."""
    analyzer = PerformanceAnalyzer()
    
    decisions = [
        {"risk_state": "pass", "signal_strength": 0.8, "confidence": 0.75},
        {"risk_state": "deny", "signal_strength": 0.5, "confidence": 0.45},
        {"risk_state": "pass", "signal_strength": 0.85, "confidence": 0.80},
    ]
    
    metrics = analyzer.analyze_risk_denial_patterns(decisions)
    
    assert metrics.total_decisions == 3
    assert metrics.actionable_decisions == 2
    assert metrics.denied_decisions == 1


def test_performance_analyzer_compare_params() -> None:
    """Test performance analyzer parameter comparison."""
    analyzer = PerformanceAnalyzer()
    
    baseline = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=70,
        denied_decisions=30,
        avg_signal_strength=0.7,
        avg_confidence=0.65,
    )
    
    candidate = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=80,
        denied_decisions=20,
        avg_signal_strength=0.75,
        avg_confidence=0.70,
    )
    
    comparison = analyzer.compare_parameter_sets(baseline, candidate)
    
    assert abs(comparison["signal_strength_improvement"] - 0.05) < 0.001
    assert abs(comparison["confidence_improvement"] - 0.05) < 0.001
    assert comparison["is_improvement"] is True


def test_parameter_recommender_strategy_threshold_raise() -> None:
    """Test recommender suggests raising strategy threshold."""
    recommender = ParameterRecommender()
    
    current_params = {"min_signal_strength": 0.6}
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=80,
        denied_decisions=20,
        avg_signal_strength=0.80,  # Well above threshold
        avg_confidence=0.75,
    )
    
    recommendations = recommender.recommend_strategy_thresholds(current_params, metrics)
    
    assert len(recommendations) >= 1
    rec = recommendations[0]
    assert rec.parameter_name == "min_signal_strength"
    assert rec.recommended_value > rec.current_value
    assert rec.requires_approval is True


def test_parameter_recommender_strategy_threshold_lower() -> None:
    """Test recommender suggests lowering threshold with high denials."""
    recommender = ParameterRecommender()
    
    current_params = {"min_signal_strength": 0.7}
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=40,
        denied_decisions=60,  # High denial rate
        avg_signal_strength=0.65,
        avg_confidence=0.60,
    )
    
    recommendations = recommender.recommend_strategy_thresholds(current_params, metrics)
    
    assert len(recommendations) >= 1
    rec = recommendations[0]
    assert rec.parameter_name == "min_signal_strength"
    assert rec.recommended_value < rec.current_value


def test_parameter_recommender_risk_threshold() -> None:
    """Test recommender suggests risk threshold adjustment."""
    recommender = ParameterRecommender()
    
    current_params = {"min_confidence": 0.5}
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=80,
        denied_decisions=20,
        avg_signal_strength=0.75,
        avg_confidence=0.75,  # Well above threshold
    )
    
    recommendations = recommender.recommend_risk_thresholds(current_params, metrics)
    
    assert len(recommendations) >= 1
    rec = recommendations[0]
    assert rec.parameter_name == "min_confidence"
    assert rec.recommended_value > rec.current_value
    assert rec.requires_approval is True


def test_parameter_recommender_position_sizing() -> None:
    """Test recommender suggests position sizing adjustment."""
    recommender = ParameterRecommender()
    
    current_params = {"max_position_size": 100}
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=80,
        denied_decisions=20,
        avg_signal_strength=0.85,  # High signal quality
        avg_confidence=0.80,
    )
    
    recommendations = recommender.recommend_position_sizing(current_params, metrics)
    
    assert len(recommendations) >= 1
    rec = recommendations[0]
    assert rec.parameter_name == "max_position_size"
    assert rec.recommended_value > rec.current_value


def test_parameter_recommender_generate_all() -> None:
    """Test recommender generates all applicable recommendations."""
    recommender = ParameterRecommender(min_confidence=0.6)
    
    strategy_params = {"min_signal_strength": 0.6}
    risk_params = {"min_confidence": 0.5, "max_position_size": 100}
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=80,
        denied_decisions=20,
        avg_signal_strength=0.80,
        avg_confidence=0.75,
    )
    
    recommendations = recommender.generate_recommendations(
        current_strategy_params=strategy_params,
        current_risk_params=risk_params,
        performance_metrics=metrics,
    )
    
    # Should have multiple recommendations
    assert len(recommendations) >= 2
    
    # All should require approval
    assert all(r.requires_approval for r in recommendations)
    
    # All should meet minimum confidence
    assert all(r.confidence >= 0.6 for r in recommendations)


def test_parameter_recommender_min_confidence_filter() -> None:
    """Test recommender filters by minimum confidence."""
    recommender = ParameterRecommender(min_confidence=0.8)
    
    strategy_params = {"min_signal_strength": 0.6}
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=80,
        denied_decisions=20,
        avg_signal_strength=0.75,
        avg_confidence=0.70,
    )
    
    recommendations = recommender.recommend_strategy_thresholds(strategy_params, metrics)
    
    # Should filter out low confidence recommendations
    assert all(r.confidence >= 0.8 for r in recommendations)


def test_parameter_recommender_no_auto_apply() -> None:
    """Test that all recommendations require approval."""
    recommender = ParameterRecommender()
    
    strategy_params = {"min_signal_strength": 0.6}
    risk_params = {"min_confidence": 0.5}
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=80,
        denied_decisions=20,
        avg_signal_strength=0.80,
        avg_confidence=0.75,
    )
    
    recommendations = recommender.generate_recommendations(
        current_strategy_params=strategy_params,
        current_risk_params=risk_params,
        performance_metrics=metrics,
    )
    
    # CRITICAL: All recommendations must require approval (no auto-apply)
    for rec in recommendations:
        assert rec.requires_approval is True


def test_parameter_recommendation_structure() -> None:
    """Test parameter recommendation structure."""
    recommender = ParameterRecommender()
    
    current_params = {"min_signal_strength": 0.6}
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=80,
        denied_decisions=20,
        avg_signal_strength=0.80,
        avg_confidence=0.75,
    )
    
    recommendations = recommender.recommend_strategy_thresholds(current_params, metrics)
    
    assert len(recommendations) >= 1
    rec = recommendations[0]
    
    # Verify structure
    assert rec.recommendation_id is not None
    assert rec.recommendation_type == RecommendationType.STRATEGY_THRESHOLD
    assert rec.generated_at is not None
    assert rec.parameter_name == "min_signal_strength"
    assert rec.current_value == 0.6
    assert rec.recommended_value != rec.current_value
    assert rec.rationale != ""
    assert 0.0 <= rec.confidence <= 1.0
    assert rec.impact_estimate != ""
    assert rec.requires_approval is True
