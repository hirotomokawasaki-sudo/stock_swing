"""Signal summarizer for human-readable candidate signal summaries.

This module generates operator-friendly summaries of candidate signals
from the strategy engine.
"""

from __future__ import annotations

from stock_swing.strategy_engine.base_strategy import CandidateSignal


class SignalSummarizer:
    """Summarizer for candidate signals.
    
    Generates human-readable summaries for operator review.
    """
    
    @staticmethod
    def summarize(signal: CandidateSignal) -> str:
        """Generate human-readable summary of candidate signal.
        
        Args:
            signal: Candidate signal to summarize.
            
        Returns:
            Human-readable summary string.
        """
        lines = [
            f"📊 **Candidate Signal: {signal.strategy_id}**",
            f"",
            f"**Symbol:** {signal.symbol}",
            f"**Action:** {signal.action.upper()}",
            f"**Signal Strength:** {signal.signal_strength:.2%}",
            f"**Confidence:** {signal.confidence:.2%}",
            f"**Time Horizon:** {signal.time_horizon}",
            f"",
            f"**Reasoning:** {signal.reasoning}",
        ]
        
        if signal.feature_refs:
            lines.append(f"")
            lines.append(f"**Features Used:** {', '.join(signal.feature_refs)}")
        
        if signal.metadata:
            lines.append(f"")
            lines.append(f"**Additional Context:**")
            for key, value in signal.metadata.items():
                if isinstance(value, float):
                    lines.append(f"  - {key}: {value:.2%}" if abs(value) < 10 else f"  - {key}: {value:.2f}")
                else:
                    lines.append(f"  - {key}: {value}")
        
        lines.append(f"")
        lines.append(f"⚠️ *This is a candidate signal only. Not actionable until risk-validated.*")
        
        return "\n".join(lines)
    
    @staticmethod
    def summarize_batch(signals: list[CandidateSignal]) -> str:
        """Generate summary of multiple candidate signals.
        
        Args:
            signals: List of candidate signals.
            
        Returns:
            Human-readable batch summary.
        """
        if not signals:
            return "📊 **No candidate signals generated.**"
        
        lines = [
            f"📊 **Candidate Signals Summary**",
            f"",
            f"**Total Signals:** {len(signals)}",
            f"",
        ]
        
        # Group by action
        by_action = {}
        for signal in signals:
            if signal.action not in by_action:
                by_action[signal.action] = []
            by_action[signal.action].append(signal)
        
        for action, action_signals in by_action.items():
            lines.append(f"**{action.upper()}:** {len(action_signals)} signals")
            for signal in action_signals:
                lines.append(
                    f"  - {signal.symbol}: "
                    f"strength {signal.signal_strength:.1%}, "
                    f"confidence {signal.confidence:.1%} "
                    f"({signal.strategy_id})"
                )
        
        lines.append(f"")
        lines.append(f"⚠️ *Candidate signals only. Not actionable until risk-validated.*")
        
        return "\n".join(lines)
