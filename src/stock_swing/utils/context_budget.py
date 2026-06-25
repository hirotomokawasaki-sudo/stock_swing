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
    return {
        "equity": snapshot.get("equity"),
        "open_positions": snapshot.get("open_position_count"),
        "realized_pnl": snapshot.get("realized_pnl"),
        "win_rate": snapshot.get("win_rate"),
        "profit_factor": snapshot.get("profit_factor"),
        "regime": snapshot.get("market_regime"),
        "stale_warnings": snapshot.get("stale_warnings", [])[:5],
    }


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

    base.update(
        {
            "realized_pnl": snapshot.get("realized_pnl"),
            "unrealized_pnl": snapshot.get("unrealized_pnl"),
            "win_rate": snapshot.get("win_rate"),
            "profit_factor": snapshot.get("profit_factor"),
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
