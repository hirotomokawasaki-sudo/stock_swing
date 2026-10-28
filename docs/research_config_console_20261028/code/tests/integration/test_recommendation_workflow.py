"""Integration tests for recommendation workflow."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from stock_swing.parameter_engine import (
    ParameterRecommender,
    PerformanceAnalyzer,
    PerformanceMetrics,
    SafeRangeValidator,
)
from stock_swing.reporting import RecommendationReporter


def test_end_to_end_recommendation_workflow() -> None:
    """Test complete recommendation workflow from analysis to report."""
    
    # Step 1: Analyze performance
    analyzer = PerformanceAnalyzer()
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=75,
        denied_decisions=25,
        avg_signal_strength=0.78,
        avg_confidence=0.72,
    )
    
    # Step 2: Generate recommendations
    recommender = ParameterRecommender(min_confidence=0.6)
    recommendations = recommender.generate_recommendations(
        current_strategy_params={"min_signal_strength": 0.6},
        current_risk_params={"min_confidence": 0.5, "max_position_size": 100},
        performance_metrics=metrics,
    )
    
    # Step 3: Validate recommendations against safe ranges
    validator = SafeRangeValidator()
    for rec in recommendations:
        is_valid, error = validator.validate_value(
            rec.parameter_name,
            rec.recommended_value,
        )
        assert is_valid, f"Recommendation violates safe range: {error}"
    
    # Step 4: Generate report
    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = RecommendationReporter(audit_dir=Path(tmpdir))
        
        report = reporter.generate_report(
            recommendations=recommendations,
            evaluation_period="2026-03-01 to 2026-03-27",
            metadata={"workflow": "integration_test"},
        )
        
        # Step 5: Write report (JSON and Markdown)
        json_path = reporter.write_report(report, format="json")
        md_path = reporter.write_report(report, format="markdown")
        
        assert json_path.exists()
        assert md_path.exists()
        
        # Verify JSON report
        import json
        json_content = json.loads(json_path.read_text())
        assert "RECOMMENDATIONS ONLY" in json_content["disclaimer"]
        
        # Verify Markdown report
        md_content = md_path.read_text()
        assert "No automatic parameter changes" in md_content
        
        # Step 6: Verify no auto-apply
        # All recommendations should require approval
        for rec in recommendations:
            assert rec.requires_approval is True


def test_safe_range_enforcement_in_workflow() -> None:
    """Test safe range enforcement throughout workflow."""
    
    # Create metrics that would suggest extreme parameters
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=90,
        denied_decisions=10,
        avg_signal_strength=0.95,  # Very high
        avg_confidence=0.90,  # Very high
    )
    
    # Generate recommendations
    recommender = ParameterRecommender()
    recommendations = recommender.generate_recommendations(
        current_strategy_params={"min_signal_strength": 0.6},
        current_risk_params={"min_confidence": 0.5},
        performance_metrics=metrics,
    )
    
    # Validate all recommendations are within safe ranges
    validator = SafeRangeValidator()
    for rec in recommendations:
        is_valid, error = validator.validate_value(
            rec.parameter_name,
            rec.recommended_value,
        )
        
        # CRITICAL: Must pass safe range validation
        assert is_valid, (
            f"Recommendation {rec.parameter_name}={rec.recommended_value} "
            f"violates safe range: {error}"
        )
        
        # Verify within approved range
        param_range = validator.approved_ranges[rec.parameter_name]
        assert param_range.min_value <= rec.recommended_value <= param_range.max_value


def test_no_config_modification_in_workflow() -> None:
    """Test that workflow does not modify any configuration."""
    
    # Initial parameters
    initial_strategy_params = {"min_signal_strength": 0.6}
    initial_risk_params = {"min_confidence": 0.5, "max_position_size": 100}
    
    # Copy for comparison
    import copy
    strategy_params_copy = copy.deepcopy(initial_strategy_params)
    risk_params_copy = copy.deepcopy(initial_risk_params)
    
    # Run full workflow
    analyzer = PerformanceAnalyzer()
    metrics = PerformanceMetrics(
        total_decisions=100,
        actionable_decisions=75,
        denied_decisions=25,
        avg_signal_strength=0.75,
        avg_confidence=0.70,
    )
    
    recommender = ParameterRecommender()
    recommendations = recommender.generate_recommendations(
        current_strategy_params=initial_strategy_params,
        current_risk_params=initial_risk_params,
        performance_metrics=metrics,
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = RecommendationReporter(audit_dir=Path(tmpdir))
        report = reporter.generate_report(recommendations, "test period")
        reporter.write_report(report, format="json")
    
    # CRITICAL: Verify no parameters were modified
    assert initial_strategy_params == strategy_params_copy, \
        "Strategy parameters were modified!"
    assert initial_risk_params == risk_params_copy, \
        "Risk parameters were modified!"


def test_audit_trail_in_workflow() -> None:
    """Test audit trail creation in workflow."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_dir = Path(tmpdir)
        
        # Generate recommendations
        recommender = ParameterRecommender()
        metrics = PerformanceMetrics(
            total_decisions=100,
            actionable_decisions=75,
            denied_decisions=25,
            avg_signal_strength=0.75,
            avg_confidence=0.70,
        )
        
        recommendations = recommender.generate_recommendations(
            current_strategy_params={"min_signal_strength": 0.6},
            current_risk_params={"min_confidence": 0.5},
            performance_metrics=metrics,
        )
        
        # Write report to audit
        reporter = RecommendationReporter(audit_dir=audit_dir)
        report = reporter.generate_report(recommendations, "test period")
        filepath = reporter.write_report(report, format="json")
        
        # Verify audit file exists
        assert filepath.exists()
        assert filepath.parent == audit_dir
        
        # Verify audit content
        import json
        audit_content = json.loads(filepath.read_text())
        
        # Verify auditability
        assert "report_id" in audit_content
        assert "generated_at" in audit_content
        assert "recommendations" in audit_content
        assert "disclaimer" in audit_content
        
        # Verify each recommendation is auditable
        for rec in audit_content["recommendations"]:
            assert "recommendation_id" in rec
            assert "rationale" in rec
            assert "supporting_metrics" in rec
            assert "requires_approval" in rec
            assert rec["requires_approval"] is True
