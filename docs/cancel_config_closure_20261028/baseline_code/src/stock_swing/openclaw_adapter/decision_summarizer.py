"""Decision summarizer for human-readable decision summaries.

This module generates operator-friendly summaries of decision records
from the decision engine.
"""

from __future__ import annotations

from stock_swing.decision_engine.decision_engine import DecisionRecord


class DecisionSummarizer:
    """Summarizer for decision records.
    
    Generates human-readable summaries for operator review.
    """
    
    @staticmethod
    def summarize(decision: DecisionRecord) -> str:
        """Generate human-readable summary of decision.
        
        Args:
            decision: Decision record to summarize.
            
        Returns:
            Human-readable summary string.
        """
        # Action emoji
        action_emoji = {
            "buy": "📈",
            "sell": "📉",
            "hold": "⏸️",
            "deny": "🚫",
            "review": "🔍",
        }
        emoji = action_emoji.get(decision.action, "📋")
        
        # Risk state emoji
        risk_emoji = {
            "pass": "✅",
            "deny": "❌",
            "review": "⚠️",
        }
        risk_status = risk_emoji.get(decision.risk_state, "❓")
        
        lines = [
            f"{emoji} **Decision: {decision.action.upper()}**",
            f"",
            f"**Symbol:** {decision.symbol}",
            f"**Strategy:** {decision.strategy_id}",
            f"**Risk State:** {risk_status} {decision.risk_state}",
            f"**Mode:** {decision.mode}",
            f"",
            f"**Signal Strength:** {decision.signal_strength:.2%}",
            f"**Confidence:** {decision.confidence:.2%}",
            f"**Time Horizon:** {decision.time_horizon}",
        ]
        
        # Proposed order details
        if decision.proposed_order:
            order = decision.proposed_order
            lines.append(f"")
            lines.append(f"**Proposed Order:**")
            lines.append(f"  - Side: {order.side.upper()}")
            lines.append(f"  - Type: {order.order_type}")
            lines.append(f"  - Quantity: {order.qty} shares")
            lines.append(f"  - Time in Force: {order.time_in_force}")
            if order.limit_price:
                lines.append(f"  - Limit Price: ${order.limit_price:.2f}")
        
        # Operator approval
        if decision.requires_operator_approval:
            lines.append(f"")
            lines.append(f"⚠️ **Requires Operator Approval**")
        
        # Deny reasons
        if decision.deny_reasons:
            lines.append(f"")
            lines.append(f"**Denial Reasons:**")
            for reason in decision.deny_reasons:
                lines.append(f"  - {reason}")
        
        # Evidence
        if decision.evidence:
            evidence = decision.evidence
            if evidence.get("notes"):
                lines.append(f"")
                lines.append(f"**Notes:**")
                for note in evidence["notes"]:
                    lines.append(f"  - {note}")
        
        # Actionability
        lines.append(f"")
        if decision.action == "deny":
            lines.append(f"🚫 **Not actionable** (denied by risk checks)")
        elif decision.action == "review":
            lines.append(f"🔍 **Requires manual review before execution**")
        elif decision.action == "hold":
            lines.append(f"⏸️ **Holding** (research mode or no action)")
        elif decision.risk_state == "pass" and decision.proposed_order:
            lines.append(f"✅ **Actionable** (passed risk validation)")
        else:
            lines.append(f"❓ **Status unclear**")
        
        return "\n".join(lines)
    
    @staticmethod
    def summarize_batch(decisions: list[DecisionRecord]) -> str:
        """Generate summary of multiple decisions.
        
        Args:
            decisions: List of decision records.
            
        Returns:
            Human-readable batch summary.
        """
        if not decisions:
            return "📋 **No decisions generated.**"
        
        lines = [
            f"📋 **Decisions Summary**",
            f"",
            f"**Total Decisions:** {len(decisions)}",
            f"",
        ]
        
        # Group by action
        by_action = {}
        for decision in decisions:
            if decision.action not in by_action:
                by_action[decision.action] = []
            by_action[decision.action].append(decision)
        
        # Group by risk state
        by_risk = {}
        for decision in decisions:
            if decision.risk_state not in by_risk:
                by_risk[decision.risk_state] = []
            by_risk[decision.risk_state].append(decision)
        
        lines.append(f"**By Action:**")
        for action, action_decisions in by_action.items():
            emoji = {"buy": "📈", "sell": "📉", "hold": "⏸️", "deny": "🚫", "review": "🔍"}.get(action, "📋")
            lines.append(f"  {emoji} {action.upper()}: {len(action_decisions)}")
        
        lines.append(f"")
        lines.append(f"**By Risk State:**")
        for risk_state, risk_decisions in by_risk.items():
            emoji = {"pass": "✅", "deny": "❌", "review": "⚠️"}.get(risk_state, "❓")
            lines.append(f"  {emoji} {risk_state}: {len(risk_decisions)}")
        
        # Actionable count
        actionable = [d for d in decisions if d.risk_state == "pass" and d.action in {"buy", "sell"}]
        lines.append(f"")
        lines.append(f"**Actionable:** {len(actionable)} decisions ready for execution")
        
        # Requires approval
        needs_approval = [d for d in decisions if d.requires_operator_approval]
        if needs_approval:
            lines.append(f"**Requires Approval:** {len(needs_approval)} decisions")
        
        return "\n".join(lines)
