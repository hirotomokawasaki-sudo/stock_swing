"""Tests for recommendation reporting."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from stock_swing.parameter_engine import ParameterRecommendation, RecommendationType
from stock_swing.reporting import RecommendationReport, RecommendationReporter


def create_test_recommendation() -> ParameterRecommendation:
    """Create test recommendation."""
    return ParameterRecommendation(
        recommendation_id="test-rec-001",
        recommendation_type=RecommendationType.STRATEGY_THRESHOLD,
        generated_at=datetime.now(timezone.utc),
        parameter_name="min_signal_strength",
        current_value=0.6,
        recommended_value=0.65,
        rationale="Test rationale",
        confidence=0.75,
        impact_estimate="Test impact",
        supporting_metrics={"test": "metric"},
        requires_approval=True,
    )


def test_recommendation_reporter_generate_report() -> None:
    """Test generating recommendation report."""
    reporter = RecommendationReporter()
    
    recommendations = [create_test_recommendation()]
    
    report = reporter.generate_report(
        recommendations=recommendations,
        evaluation_period="2026-03-01 to 2026-03-27",
        metadata={"test": "metadata"},
    )
    
    assert report.report_id is not None
    assert len(report.recommendations) == 1
    assert report.summary["total"] == 1
    assert report.evaluation_period == "2026-03-01 to 2026-03-27"


def test_recommendation_reporter_write_json() -> None:
    """Test writing JSON report."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_dir = Path(tmpdir)
        reporter = RecommendationReporter(audit_dir=audit_dir)
        
        recommendations = [create_test_recommendation()]
        report = reporter.generate_report(recommendations, "test period")
        
        filepath = reporter.write_report(report, format="json")
        
        assert filepath.exists()
        assert filepath.suffix == ".json"
        
        # Verify content
        import json
        content = json.loads(filepath.read_text())
        assert content["report_id"] == report.report_id
        assert len(content["recommendations"]) == 1
        assert content["disclaimer"] == "RECOMMENDATIONS ONLY - NO AUTO-APPLY"


def test_recommendation_reporter_write_markdown() -> None:
    """Test writing Markdown report."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_dir = Path(tmpdir)
        reporter = RecommendationReporter(audit_dir=audit_dir)
        
        recommendations = [create_test_recommendation()]
        report = reporter.generate_report(recommendations, "test period")
        
        filepath = reporter.write_report(report, format="markdown")
        
        assert filepath.exists()
        assert filepath.suffix == ".markdown"
        
        # Verify content
        content = filepath.read_text()
        assert "Parameter Recommendation Report" in content
        assert "RECOMMENDATIONS ONLY" in content
        assert "No automatic parameter changes" in content


def test_recommendation_reporter_generate_summary() -> None:
    """Test generating human-readable summary."""
    reporter = RecommendationReporter()
    
    recommendations = [create_test_recommendation()]
    
    summary = reporter.generate_summary(recommendations)
    
    assert "Parameter Recommendations Summary" in summary
    assert "**Total Recommendations:** 1" in summary
    assert "min_signal_strength" in summary
    assert "IMPORTANT" in summary
    assert "No automatic parameter changes" in summary


def test_recommendation_report_structure() -> None:
    """Test recommendation report structure."""
    reporter = RecommendationReporter()
    
    recommendations = [create_test_recommendation()]
    report = reporter.generate_report(recommendations, "test period")
    
    # Verify structure
    assert hasattr(report, "report_id")
    assert hasattr(report, "generated_at")
    assert hasattr(report, "evaluation_period")
    assert hasattr(report, "recommendations")
    assert hasattr(report, "summary")
    assert hasattr(report, "metadata")
    
    # Verify summary
    assert "total" in report.summary
    assert "by_type" in report.summary
    assert "avg_confidence" in report.summary
