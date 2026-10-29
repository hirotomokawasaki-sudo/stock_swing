from __future__ import annotations


def build_daily_summary(decision_count: int, denied_count: int) -> str:
    return f"Daily summary: decisions={decision_count}, denied={denied_count}"
