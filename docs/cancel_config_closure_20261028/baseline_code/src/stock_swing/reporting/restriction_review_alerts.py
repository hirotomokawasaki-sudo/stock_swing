"""Read-only presentation of research-review candidates; never an unlock gate."""
from __future__ import annotations

from typing import Any


def build_restriction_review_alerts(review: Any) -> list[dict[str, Any]]:
    """Project an observer result into operator alerts, rejecting invalid inputs.

    Eligibility is assessed only by the observer. This formatter does not pool
    cohorts, recompute performance, approve a release, or change trading health.
    """
    if (not isinstance(review, dict) or review.get("status") != "observing"
            or review.get("eligible_to_trade") is not False
            or review.get("automatic_release") is not False):
        return []
    candidates, rows = review.get("candidates"), review.get("rows")
    if not isinstance(candidates, list) or not isinstance(rows, list):
        return []
    names = {name for name in candidates if isinstance(name, str) and name.strip()}
    valid_rows = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("symbol"), str):
            continue
        completed, required = row.get("completed"), row.get("required")
        if (row["symbol"] not in names or row.get("status") != "review_candidate"
                or row.get("eligible_to_trade") is not False
                or row.get("requires_operator_approval") is not True
                or row.get("requires_strategy_exit_validation") is not True
                or type(completed) is not int or type(required) is not int
                or required <= 0 or completed < required):
            continue
        valid_rows.append({key: row.get(key) for key in (
            "symbol", "strategy_id", "cohort", "completed", "required",
        )})
    if not valid_rows:
        return []
    symbols = sorted({row["symbol"] for row in valid_rows})
    return [{
        # This is a review event, not a runtime fault: warning would turn an
        # otherwise healthy ConsoleSummary into DEGRADED.
        "severity": "info", "code": "entry_restriction_review_candidate",
        "message": f"購入停止の再検証候補: {', '.join(symbols)}。購入制限は継続中。"
                   "固定期間の価格診断のみ。本来のExit検証と解除の手動承認が必要です。",
        "details": {"symbols": symbols, "cohorts": valid_rows,
                    "eligible_to_trade": False, "automatic_release": False,
                    "requires_operator_approval": True,
                    "requires_strategy_exit_validation": True},
    }]
