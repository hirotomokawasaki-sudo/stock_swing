"""Execution summarizer for human-readable execution and reconciliation summaries.

This module generates operator-friendly summaries of order submissions,
fills, and reconciliation results.
"""

from __future__ import annotations

from stock_swing.execution.paper_executor import FillRecord, OrderSubmission
from stock_swing.execution.reconciler import ReconciliationResult


class ExecutionSummarizer:
    """Summarizer for execution and reconciliation.
    
    Generates human-readable summaries for operator review.
    """
    
    @staticmethod
    def summarize_submission(submission: OrderSubmission) -> str:
        """Generate human-readable summary of order submission.
        
        Args:
            submission: Order submission to summarize.
            
        Returns:
            Human-readable summary string.
        """
        # Status emoji
        status_emoji = {
            "pending": "⏳",
            "submitted": "📤",
            "filled": "✅",
            "partially_filled": "🔄",
            "cancelled": "❌",
            "rejected": "🚫",
        }
        emoji = status_emoji.get(submission.status, "❓")
        
        lines = [
            f"{emoji} **Order Submission: {submission.status.upper()}**",
            f"",
            f"**Symbol:** {submission.symbol}",
            f"**Side:** {submission.side.upper()}",
            f"**Type:** {submission.order_type}",
            f"**Quantity:** {submission.qty} shares",
            f"**Time in Force:** {submission.time_in_force}",
        ]
        
        if submission.limit_price:
            lines.append(f"**Limit Price:** ${submission.limit_price:.2f}")
        
        lines.append(f"")
        lines.append(f"**Submission ID:** `{submission.submission_id[:16]}...`")
        lines.append(f"**Decision ID:** `{submission.decision_id[:16]}...`")
        
        if submission.broker_order_id:
            lines.append(f"**Broker Order ID:** `{submission.broker_order_id}`")
        
        lines.append(f"**Submitted At:** {submission.submitted_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        if submission.reject_reason:
            lines.append(f"")
            lines.append(f"🚫 **Rejection Reason:** {submission.reject_reason}")
        
        if submission.broker_status:
            lines.append(f"")
            lines.append(f"**Broker Status:** {submission.broker_status}")
        
        return "\n".join(lines)
    
    @staticmethod
    def summarize_fill(fill: FillRecord) -> str:
        """Generate human-readable summary of order fill.
        
        Args:
            fill: Fill record to summarize.
            
        Returns:
            Human-readable summary string.
        """
        lines = [
            f"✅ **Order Fill**",
            f"",
            f"**Symbol:** {fill.symbol}",
            f"**Side:** {fill.side.upper()}",
            f"**Quantity:** {fill.qty} shares",
            f"**Price:** ${fill.price:.2f}",
            f"**Total:** ${fill.qty * fill.price:.2f}",
            f"",
            f"**Fill ID:** `{fill.fill_id[:16]}...`",
            f"**Broker Order ID:** `{fill.broker_order_id}`",
            f"**Filled At:** {fill.filled_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        ]
        
        if fill.broker_fill_id:
            lines.append(f"**Broker Fill ID:** `{fill.broker_fill_id}`")
        
        return "\n".join(lines)
    
    @staticmethod
    def summarize_reconciliation(result: ReconciliationResult) -> str:
        """Generate human-readable summary of reconciliation result.
        
        Args:
            result: Reconciliation result to summarize.
            
        Returns:
            Human-readable summary string.
        """
        # Match status emoji
        match_emoji = "✅" if result.status_matched else "⚠️"
        
        lines = [
            f"{match_emoji} **Reconciliation Result**",
            f"",
            f"**Submission ID:** `{result.submission_id[:16]}...`",
            f"**Broker Order ID:** `{result.broker_order_id}`",
            f"**Reconciled At:** {result.reconciled_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"",
            f"**Status Match:** {match_emoji} {'Yes' if result.status_matched else 'No'}",
            f"**Internal Status:** {result.internal_status}",
            f"**Broker Status:** {result.broker_status}",
        ]
        
        # Fills detected
        if result.fills_detected:
            lines.append(f"")
            lines.append(f"**Fills Detected:** {len(result.fills_detected)}")
            for fill in result.fills_detected:
                qty = fill.get("qty", 0)
                avg_price = fill.get("avg_price", 0.0)
                if avg_price:
                    lines.append(f"  - {qty} shares @ ${avg_price:.2f}")
                else:
                    lines.append(f"  - {qty} shares (price pending)")
        
        # Discrepancies
        if result.discrepancies:
            lines.append(f"")
            lines.append(f"⚠️ **Discrepancies Found:** {len(result.discrepancies)}")
            for discrepancy in result.discrepancies:
                lines.append(f"  - {discrepancy}")
        else:
            lines.append(f"")
            lines.append(f"✅ **No discrepancies detected**")
        
        return "\n".join(lines)
    
    @staticmethod
    def summarize_submissions_batch(submissions: list[OrderSubmission]) -> str:
        """Generate summary of multiple order submissions.
        
        Args:
            submissions: List of order submissions.
            
        Returns:
            Human-readable batch summary.
        """
        if not submissions:
            return "📤 **No order submissions.**"
        
        lines = [
            f"📤 **Order Submissions Summary**",
            f"",
            f"**Total Submissions:** {len(submissions)}",
            f"",
        ]
        
        # Group by status
        by_status = {}
        for submission in submissions:
            if submission.status not in by_status:
                by_status[submission.status] = []
            by_status[submission.status].append(submission)
        
        lines.append(f"**By Status:**")
        status_emoji = {
            "pending": "⏳",
            "submitted": "📤",
            "filled": "✅",
            "partially_filled": "🔄",
            "cancelled": "❌",
            "rejected": "🚫",
        }
        for status, status_submissions in by_status.items():
            emoji = status_emoji.get(status, "❓")
            lines.append(f"  {emoji} {status}: {len(status_submissions)}")
        
        # Group by symbol
        by_symbol = {}
        for submission in submissions:
            if submission.symbol not in by_symbol:
                by_symbol[submission.symbol] = []
            by_symbol[submission.symbol].append(submission)
        
        lines.append(f"")
        lines.append(f"**By Symbol:**")
        for symbol, symbol_submissions in sorted(by_symbol.items()):
            lines.append(f"  - {symbol}: {len(symbol_submissions)} orders")
        
        return "\n".join(lines)
