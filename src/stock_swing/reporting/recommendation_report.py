"""Recommendation reporting for structured output and audit trail.

This module generates structured reports for parameter recommendations.
Reports are written to audit storage and do not modify system configuration.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from stock_swing.parameter_engine.parameter_recommender import ParameterRecommendation


@dataclass
class RecommendationReport:
    """Structured report for parameter recommendations.
    
    Attributes:
        report_id: Unique report identifier.
        generated_at: UTC timestamp when report was generated.
        evaluation_period: Time period evaluated (e.g., "2026-03-01 to 2026-03-27").
        recommendations: List of recommendations.
        summary: Summary statistics.
        metadata: Additional metadata.
    """
    
    report_id: str
    generated_at: datetime
    evaluation_period: str
    recommendations: list[ParameterRecommendation]
    summary: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class RecommendationReporter:
    """Reporter for parameter recommendations.
    
    Generates structured reports and writes to audit storage.
    
    CRITICAL: Reports are informational only. No auto-apply.
    """
    
    def __init__(self, audit_dir: Path | None = None):
        """Initialize recommendation reporter.
        
        Args:
            audit_dir: Directory for audit reports (default: data/audits/).
        """
        self.audit_dir = audit_dir or Path("data/audits")
    
    def generate_report(
        self,
        recommendations: list[ParameterRecommendation],
        evaluation_period: str,
        metadata: dict[str, Any] | None = None,
    ) -> RecommendationReport:
        """Generate recommendation report.
        
        Args:
            recommendations: List of recommendations.
            evaluation_period: Time period evaluated.
            metadata: Additional metadata.
            
        Returns:
            RecommendationReport.
        """
        # Generate report ID
        report_id = f"rec-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        # Calculate summary statistics
        summary = self._calculate_summary(recommendations)
        
        # Create report
        report = RecommendationReport(
            report_id=report_id,
            generated_at=datetime.now(),
            evaluation_period=evaluation_period,
            recommendations=recommendations,
            summary=summary,
            metadata=metadata or {},
        )
        
        return report
    
    def write_report(
        self,
        report: RecommendationReport,
        format: str = "json",
    ) -> Path:
        """Write report to audit storage.
        
        Args:
            report: Report to write.
            format: Output format (json/markdown).
            
        Returns:
            Path to written report file.
            
        Note:
            Reports are written to audit directory and do not modify
            active system configuration.
        """
        # Ensure audit directory exists
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename
        filename = f"{report.report_id}.{format}"
        filepath = self.audit_dir / filename
        
        if format == "json":
            self._write_json_report(report, filepath)
        elif format == "markdown":
            self._write_markdown_report(report, filepath)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        return filepath
    
    def generate_summary(
        self,
        recommendations: list[ParameterRecommendation],
    ) -> str:
        """Generate human-readable summary of recommendations.
        
        Args:
            recommendations: List of recommendations.
            
        Returns:
            Human-readable summary.
        """
        if not recommendations:
            return "No recommendations generated."
        
        lines = [
            "# Parameter Recommendations Summary",
            "",
            f"**Total Recommendations:** {len(recommendations)}",
            "",
        ]
        
        # Group by type
        by_type: dict[str, list[ParameterRecommendation]] = {}
        for rec in recommendations:
            rec_type = rec.recommendation_type.value
            if rec_type not in by_type:
                by_type[rec_type] = []
            by_type[rec_type].append(rec)
        
        lines.append("## By Type:")
        for rec_type, recs in by_type.items():
            lines.append(f"- **{rec_type}**: {len(recs)} recommendations")
        
        lines.append("")
        lines.append("## Recommendations:")
        lines.append("")
        
        for rec in recommendations:
            lines.append(f"### {rec.parameter_name}")
            lines.append(f"- **Current Value:** {rec.current_value}")
            lines.append(f"- **Recommended Value:** {rec.recommended_value}")
            lines.append(f"- **Confidence:** {rec.confidence:.1%}")
            lines.append(f"- **Rationale:** {rec.rationale}")
            lines.append(f"- **Impact Estimate:** {rec.impact_estimate}")
            lines.append(f"- **Requires Approval:** {rec.requires_approval}")
            lines.append("")
        
        lines.append("---")
        lines.append("**IMPORTANT:** These are recommendations only.")
        lines.append("No automatic parameter changes have been applied.")
        lines.append("Operator approval required for all changes.")
        
        return "\n".join(lines)
    
    def _calculate_summary(
        self,
        recommendations: list[ParameterRecommendation],
    ) -> dict[str, Any]:
        """Calculate summary statistics.
        
        Args:
            recommendations: List of recommendations.
            
        Returns:
            Summary statistics.
        """
        if not recommendations:
            return {
                "total": 0,
                "by_type": {},
                "avg_confidence": 0.0,
            }
        
        # Count by type
        by_type: dict[str, int] = {}
        for rec in recommendations:
            rec_type = rec.recommendation_type.value
            by_type[rec_type] = by_type.get(rec_type, 0) + 1
        
        # Average confidence
        avg_confidence = sum(r.confidence for r in recommendations) / len(recommendations)
        
        return {
            "total": len(recommendations),
            "by_type": by_type,
            "avg_confidence": avg_confidence,
        }
    
    def _write_json_report(
        self,
        report: RecommendationReport,
        filepath: Path,
    ) -> None:
        """Write report in JSON format.
        
        Args:
            report: Report to write.
            filepath: Output file path.
        """
        # Convert to dict
        report_dict = {
            "report_id": report.report_id,
            "generated_at": report.generated_at.isoformat(),
            "evaluation_period": report.evaluation_period,
            "summary": report.summary,
            "metadata": report.metadata,
            "recommendations": [
                {
                    "recommendation_id": rec.recommendation_id,
                    "recommendation_type": rec.recommendation_type.value,
                    "generated_at": rec.generated_at.isoformat(),
                    "parameter_name": rec.parameter_name,
                    "current_value": rec.current_value,
                    "recommended_value": rec.recommended_value,
                    "rationale": rec.rationale,
                    "confidence": rec.confidence,
                    "impact_estimate": rec.impact_estimate,
                    "supporting_metrics": rec.supporting_metrics,
                    "requires_approval": rec.requires_approval,
                }
                for rec in report.recommendations
            ],
            "disclaimer": "RECOMMENDATIONS ONLY - NO AUTO-APPLY",
        }
        
        # Write JSON
        with filepath.open("w") as f:
            json.dump(report_dict, f, indent=2)
    
    def _write_markdown_report(
        self,
        report: RecommendationReport,
        filepath: Path,
    ) -> None:
        """Write report in Markdown format.
        
        Args:
            report: Report to write.
            filepath: Output file path.
        """
        lines = [
            f"# Parameter Recommendation Report",
            "",
            f"**Report ID:** {report.report_id}",
            f"**Generated:** {report.generated_at.isoformat()}",
            f"**Evaluation Period:** {report.evaluation_period}",
            "",
            "## Summary",
            "",
            f"- **Total Recommendations:** {report.summary.get('total', 0)}",
            f"- **Average Confidence:** {report.summary.get('avg_confidence', 0.0):.1%}",
            "",
        ]
        
        # By type
        if report.summary.get("by_type"):
            lines.append("### By Type:")
            for rec_type, count in report.summary["by_type"].items():
                lines.append(f"- **{rec_type}**: {count}")
            lines.append("")
        
        # Recommendations
        lines.append("## Recommendations")
        lines.append("")
        
        for rec in report.recommendations:
            lines.append(f"### {rec.parameter_name}")
            lines.append(f"- **Type:** {rec.recommendation_type.value}")
            lines.append(f"- **Current Value:** `{rec.current_value}`")
            lines.append(f"- **Recommended Value:** `{rec.recommended_value}`")
            lines.append(f"- **Confidence:** {rec.confidence:.1%}")
            lines.append(f"- **Rationale:** {rec.rationale}")
            lines.append(f"- **Impact Estimate:** {rec.impact_estimate}")
            lines.append(f"- **Requires Approval:** {rec.requires_approval}")
            lines.append("")
        
        # Disclaimer
        lines.append("---")
        lines.append("")
        lines.append("## DISCLAIMER")
        lines.append("")
        lines.append("**THESE ARE RECOMMENDATIONS ONLY.**")
        lines.append("")
        lines.append("No automatic parameter changes have been applied.")
        lines.append("All recommendations require explicit operator approval.")
        lines.append("Do not treat this report as applied configuration.")
        
        # Write markdown
        filepath.write_text("\n".join(lines))
