"""Compact AI context contract (P2-B)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODE_MINIMAL = "minimal"
MODE_NORMAL = "normal"
MODE_EXPANDED = "expanded"
MODE_EMERGENCY = "emergency"


@dataclass
class TokenUsageRecord:
    timestamp: str
    workflow_name: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float
    success: bool
    retry_count: int = 0
    error: str = ""
    skip_reason: str = ""


class TokenUsageTracker:
    """Append-only CSV token tracker."""

    def __init__(self, out_path: Path) -> None:
        self.out_path = out_path
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[TokenUsageRecord] = []

    def record(self, record: TokenUsageRecord) -> None:
        self._records.append(record)

    def record_skip(self, workflow: str, reason: str) -> None:
        self._records.append(
            TokenUsageRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                workflow_name=workflow,
                model="",
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                estimated_cost=0.0,
                success=True,
                skip_reason=reason,
            )
        )

    def flush(self) -> None:
        import csv

        if not self._records:
            return
        write_header = not self.out_path.exists()
        fields = [
            "timestamp",
            "workflow_name",
            "model",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "estimated_cost",
            "success",
            "retry_count",
            "error",
            "skip_reason",
        ]
        with open(self.out_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if write_header:
                writer.writeheader()
            for record in self._records:
                writer.writerow(
                    {
                        "timestamp": record.timestamp,
                        "workflow_name": record.workflow_name,
                        "model": record.model,
                        "input_tokens": record.input_tokens,
                        "output_tokens": record.output_tokens,
                        "total_tokens": record.total_tokens,
                        "estimated_cost": round(record.estimated_cost, 6),
                        "success": record.success,
                        "retry_count": record.retry_count,
                        "error": record.error,
                        "skip_reason": record.skip_reason,
                    }
                )
        self._records.clear()


def compact_trading_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a compact context pack for normal AI calls."""
    ctx: dict[str, Any] = {
        "equity": snapshot.get("equity"),
        "open_positions": snapshot.get("open_position_count"),
        "realized_pnl": snapshot.get("realized_pnl"),
        "win_rate": snapshot.get("win_rate"),
        "regime": snapshot.get("market_regime"),
        "stale_warnings": snapshot.get("stale_warnings", [])[:5],
    }
    # R2-B: ETF vs Stock PF (replaces single profit_factor)
    breakdown = snapshot.get("asset_class_breakdown") or {}
    if breakdown:
        ctx["etf_pf"] = (breakdown.get("etf") or {}).get("profit_factor")
        ctx["stock_pf"] = (breakdown.get("stock") or {}).get("profit_factor")
    else:
        ctx["profit_factor"] = snapshot.get("profit_factor")
    return ctx


def select_context_mode(
    *,
    stale_warning_count: int = 0,
    integrity_issues: int = 0,
    recent_error_count: int = 0,
    operator_requested_mode: str | None = None,
) -> str:
    """Select the AI context mode based on system state."""
    if operator_requested_mode:
        return operator_requested_mode
    if integrity_issues > 0 or stale_warning_count > 5:
        return MODE_EMERGENCY
    if recent_error_count > 3 or stale_warning_count > 2:
        return MODE_EXPANDED
    return MODE_NORMAL


def build_context_pack(
    snapshot: dict[str, Any],
    *,
    mode: str = MODE_NORMAL,
    console_summary: dict[str, Any] | None = None,
    recent_events: list[dict[str, Any]] | None = None,
    max_events: int = 10,
) -> dict[str, Any]:
    """Build a staged context pack for AI calls."""
    base = {
        "mode": mode,
        "equity": snapshot.get("equity"),
        "open_positions": snapshot.get("open_position_count"),
        "market_regime": snapshot.get("market_regime"),
    }
    if mode == MODE_MINIMAL:
        return base

    # R2-B: ETF vs Stock PF (replaces single profit_factor)
    breakdown = snapshot.get("asset_class_breakdown") or {}
    pf_ctx: dict[str, Any]
    if breakdown:
        pf_ctx = {
            "etf_pf": (breakdown.get("etf") or {}).get("profit_factor"),
            "stock_pf": (breakdown.get("stock") or {}).get("profit_factor"),
        }
    else:
        pf_ctx = {"profit_factor": snapshot.get("profit_factor")}
    base.update(
        {
            "realized_pnl": snapshot.get("realized_pnl"),
            "unrealized_pnl": snapshot.get("unrealized_pnl"),
            "win_rate": snapshot.get("win_rate"),
            **pf_ctx,
        }
    )

    if console_summary:
        base["last_run"] = {
            "run_id": console_summary.get("run_id"),
            "orders_submitted": (console_summary.get("orders") or {}).get("submitted"),
            "cluster_blocks": (console_summary.get("risk") or {}).get("cluster_blocks", []),
            "stale_symbols": (console_summary.get("data_quality") or {}).get("stale_symbols", []),
            "warnings": console_summary.get("warnings", []),
        }

    if recent_events:
        base["recent_events"] = recent_events[:max_events]

    if mode in (MODE_EXPANDED, MODE_EMERGENCY):
        base["stale_warnings"] = snapshot.get("stale_warnings", [])
        base["integrity_issues"] = snapshot.get("integrity_issues", [])

    return base


def estimate_token_count(context_pack: dict[str, Any]) -> int:
    """Rough token estimate: 1 token ≈ 4 chars of JSON."""
    import json

    return len(json.dumps(context_pack, ensure_ascii=False)) // 4


def attach_ai_telemetry(
    decision: Any,
    *,
    model: str | None = None,
    context_pack_name: str = "evidence_v1",
) -> None:
    """Fill AI telemetry fields on a DecisionRecord in-place (RF-5b).

    This function records rule-based strategy telemetry into the AI telemetry
    fields that were defined in RF-5/F5.  When a real LLM is integrated, callers
    can replace the estimated token counts with actual API usage values.

    Fields set:
      decision.model           ← model argument (defaults to decision.strategy_id)
      decision.input_tokens    ← estimated token count of decision.evidence
      decision.output_tokens   ← estimated token count of the decision output
      decision.context_pack    ← context_pack_name
      decision.prompt_version  ← decision.strategy_version_id (if present)
    """
    import json

    def _tok(obj: Any) -> int:
        try:
            return len(json.dumps(obj, ensure_ascii=False, default=str)) // 4
        except Exception:
            return 0

    # model: prefer explicit arg, fall back to strategy_id
    effective_model = model or getattr(decision, "strategy_id", "rule-based")
    decision.model = effective_model

    # input_tokens: evidence/context that feeds the decision
    evidence = getattr(decision, "evidence", {}) or {}
    decision.input_tokens = _tok(evidence)

    # output_tokens: decision summary (what the AI would output)
    output_payload = {
        "action": getattr(decision, "action", None),
        "confidence": getattr(decision, "confidence", None),
        "signal_strength": getattr(decision, "signal_strength", None),
        "deny_reasons": getattr(decision, "deny_reasons", []),
    }
    decision.output_tokens = _tok(output_payload)

    decision.context_pack = context_pack_name

    # prompt_version: use strategy_version_id if available, else strategy_id
    svid = getattr(decision, "strategy_version_id", None)
    if not getattr(decision, "prompt_version", None):
        decision.prompt_version = svid or effective_model


def build_ai_metrics_from_decisions(
    decisions: list[Any],
    *,
    daily_token_budget: int = 300_000,
    skipped_count: int = 0,
) -> dict[str, Any]:
    """Aggregate per-decision AI telemetry into a run-level ai_metrics dict.

    The returned dict is ready to be passed to ConsoleSummary.build(ai_metrics=...).
    """
    from collections import Counter

    total_in = 0
    total_out = 0
    pack_counter: Counter[str] = Counter()
    model_counter: Counter[str] = Counter()

    for d in decisions:
        total_in += getattr(d, "input_tokens", None) or 0
        total_out += getattr(d, "output_tokens", None) or 0
        pack = getattr(d, "context_pack", None) or "unknown"
        pack_counter[pack] += 1
        mdl = getattr(d, "model", None) or "unknown"
        model_counter[mdl] += 1

    return {
        "calls": len(decisions),
        "skipped": skipped_count,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "daily_token_budget": daily_token_budget,
        "context_pack_counts": dict(pack_counter),
        "model_counts": dict(model_counter),
    }
