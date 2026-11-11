"""Read-only presentation of research-review candidates; never an unlock gate."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import Any


def preflight_restriction_review(root: Path, environment: Mapping[str, str]) -> dict[str, Any]:
    """Nonblocking, read-only configuration check; never a trading permission.

    No observer store is opened/initialized and no pending journal is recovered.
    Success does not certify a later receipt, capture, completion, or performance.
    """
    base = {"as_of": datetime.now(timezone.utc).isoformat(),
            "scope": "configuration_only_not_observation_success",
            "eligible_to_trade": False, "automatic_release": False,
            "source": "scheduled_command_configuration_and_active_ledger_pair"}
    def result(status: str, reason: str) -> dict[str, Any]:
        return {**base, "status": status, "reason": reason}

    version = environment.get("ENTRY_RESTRICTION_REVIEW_VERSION", "")
    if not version:
        return result("error", "missing_version")
    if version not in {"v1", "v2", "v3", "v4", "v5", "v6", "v7", "v10", "v11", "v12", "v13", "v14", "v15", "v16"}:
        return result("error", "unsupported_version")
    if environment.get("ENTRY_RESTRICTION_REVIEW_ENABLED", "true").lower() in {"0", "false", "no"}:
        return result("disabled", "explicitly_disabled")
    if version not in {"v6", "v7", "v10", "v11", "v12", "v13", "v14", "v15", "v16"}:
        return result("ok", "legacy_version_no_ledger_binding")
    expected = environment.get("ENTRY_RESTRICTION_REVIEW_LEDGER_REVISION", "")
    if not expected or expected == "legacy":
        return result("error", "missing_ledger_revision")
    try:
        from stock_swing.tracking.compatibility import read_analysis_snapshot
        from stock_swing.tracking.ledger_transaction import ledger_transaction
        folder = Path(root) / "data/tracking"
        if not folder.is_dir():
            return result("error", "ledger_unavailable")
        with ledger_transaction(root, recover=False, blocking=False):
            state, provenance = read_analysis_snapshot(folder / "pnl_state.json")
            if version in {"v10", "v11", "v12", "v13", "v14", "v15", "v16"}:
                history = state.get("history_migrations", [])
                if len(history) != 2 or history[-1].get("intent", {}).get("schema_version") != 2:
                    return result("error", "second_financial_transition_required")
        if provenance["ledger_revision"] != expected:
            return result("error", "ledger_revision_mismatch")
        if version in {'v11', 'v12', 'v13', 'v14', 'v15', 'v16'}:
            from stock_swing.reporting.versioned_bridge import load_selected_reconciliation
            got = load_selected_reconciliation(root, expected_account_id=state.get('broker_account_id'),
                currency='USD', environment=environment)
            if got is None or got['ledger_revision'] != expected:
                return result('error', 'accounting_selector_unavailable_or_mismatched')
        return result("ok", "required_configuration_matches_active_ledger")
    except Exception:
        # Diagnostic failure must not delay or prevent protective SELL processing.
        # Do not copy exception messages, credentials, or private paths to delivery.
        return result("error", "ledger_unavailable")


def build_restriction_review_alerts(review: Any) -> list[dict[str, Any]]:
    """Project an observer result into operator alerts, rejecting invalid inputs.

    Eligibility is assessed only by the observer. This formatter does not pool
    cohorts, recompute performance, approve a release, or change trading health.
    """
    if (isinstance(review, dict) and review.get("status") == "error"
            and review.get("eligible_to_trade") is False
            and review.get("automatic_release") is False):
        return [{"severity": "info", "code": "entry_restriction_observation_failed",
                 "message": "PF観測失敗。観測設定・台帳との整合性・実行ログを確認してください。"
                            "売買処理の成否とは別の診断です。購入制限は継続中です。",
                 "details": {"observation_status": "error", "requires_attention": True,
                             "eligible_to_trade": False, "automatic_release": False}}]
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
