"""Structured console summary builder and alert system (C0/C1)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ConsoleAlert:
    severity: str  # "critical" | "warning" | "info"
    code: str
    message: str
    symbol: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _compute_run_status(
    alerts: list[ConsoleAlert],
    guardrail_status: str,
    broker_tracker_mismatch_count: int,
    stale_price_count: int,
    api_error_count: int,
) -> str:
    """Determine HALTED / DEGRADED / OK."""
    has_critical = any(a.severity == "critical" for a in alerts)
    if (
        guardrail_status == "halted"
        or broker_tracker_mismatch_count > 0
        or has_critical
    ):
        return "HALTED"
    if stale_price_count > 0 or api_error_count > 0:
        return "DEGRADED"
    warning_count = sum(1 for a in alerts if a.severity == "warning")
    if warning_count > 0:
        return "DEGRADED"
    return "OK"


@dataclass
class ConsoleSummary:
    # --- core (backward compat) ---
    run_id: str
    timestamp: str
    equity: float
    open_position_count: int
    realized_pnl: float
    unrealized_pnl: float
    signals_total: int
    signals_buy: int
    signals_sell: int
    signals_deny: int
    orders_submitted: int
    orders_rejected: int
    cluster_blocks: list[str] = field(default_factory=list)
    risk_budget_pct: float = 0.0
    stale_symbols: list[str] = field(default_factory=list)
    price_sources: dict[str, int] = field(default_factory=dict)
    market_regime: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    # --- C0/C1 additions ---
    experiment_id: str = "unknown"
    run_status: str = "OK"  # OK / DEGRADED / HALTED
    guardrail_status: str = "unknown"
    duration_seconds: float | None = None
    alerts: list[ConsoleAlert] = field(default_factory=list)
    missing_metrics: list[str] = field(default_factory=list)

    # --- C2 additions ---
    price_integrity: dict[str, Any] = field(default_factory=dict)
    api_metrics: dict[str, Any] = field(default_factory=dict)
    ai_metrics: dict[str, Any] = field(default_factory=dict)

    # --- R2-B: ETF vs Stock breakdown ---
    asset_class_breakdown: dict[str, Any] = field(default_factory=dict)

    # --- R6-E: Exit attribution breakdown ---
    exit_attribution_breakdown: dict[str, Any] = field(default_factory=dict)

    # --- R6-D: Decision Funnel detail + Broker/Tracker diff ---
    deny_reason_counts: dict[str, int] = field(default_factory=dict)
    broker_tracker_diff: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        base = {
            "run": {
                "mode": "paper",
                "status": self.run_status,
                "run_id": self.run_id,
                "experiment_id": self.experiment_id,
                "timestamp": self.timestamp,
                "duration_seconds": self.duration_seconds,
                "guardrail_status": self.guardrail_status,
            },
            "health": {
                "status": self.run_status,
                "critical_count": sum(1 for a in self.alerts if a.severity == "critical"),
                "warning_count": sum(1 for a in self.alerts if a.severity == "warning"),
                "stale_price_count": len(self.stale_symbols),
                "broker_tracker_mismatch_count": 0,
                "api_error_count": self.api_metrics.get("error_count", 0),
                "guardrail_status": self.guardrail_status,
            },
            "portfolio": {
                "equity": round(self.equity, 2),
                "realized_pnl": round(self.realized_pnl, 2),
                "unrealized_pnl": round(self.unrealized_pnl, 2),
                "total_pnl": round(self.realized_pnl + self.unrealized_pnl, 2),
                "open_positions": self.open_position_count,
                "asset_class_breakdown": self.asset_class_breakdown,
                "exit_attribution_breakdown": self.exit_attribution_breakdown,
            },
            "decision_funnel": {
                "candidates": self.signals_total,
                "buy": self.signals_buy,
                "sell": self.signals_sell,
                "deny": self.signals_deny,
                "submitted": self.orders_submitted,
                "rejected": self.orders_rejected,
                "blocked": len(self.cluster_blocks),
                "deny_reasons": self.deny_reason_counts,
            },
            "broker_tracker_diff": self.broker_tracker_diff,
            "risk": {
                "cluster_blocks": self.cluster_blocks,
                "risk_budget_pct": round(self.risk_budget_pct, 3),
                "market_regime": self.market_regime,
            },
            "price_integrity": self.price_integrity
            or {
                "fresh_price_count": len(self.price_sources),
                "stale_price_count": len(self.stale_symbols),
                "top_stale_symbols": self.stale_symbols[:5],
                "price_source_breakdown": self.price_sources,
            },
            "api": self.api_metrics,
            "ai": self.ai_metrics,
            "alerts": [asdict(a) for a in self.alerts],
            "missing_metrics": self.missing_metrics,
        }
        return base

    def save_json(self, path: Path) -> None:
        """Atomically save summary JSON to path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def emit(self, save_path: Path | None = None) -> None:
        """Print machine-readable block + render text. Optionally save JSON."""
        from stock_swing.reporting.console_renderer import ConsoleRenderer

        renderer = ConsoleRenderer()
        print(renderer.render(self))
        print("\nCONSOLE_SUMMARY_JSON " + json.dumps(self.to_dict(), ensure_ascii=False))
        if save_path is not None:
            try:
                self.save_json(save_path)
            except Exception as exc:
                print(f"  WARN: console summary save failed: {exc}")

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        equity: float,
        open_position_count: int,
        realized_pnl: float = 0.0,
        unrealized_pnl: float = 0.0,
        decisions: list | None = None,
        submissions: list | None = None,
        cluster_blocks: list[str] | None = None,
        risk_budget_pct: float = 0.0,
        stale_symbols: list[str] | None = None,
        price_sources: dict[str, int] | None = None,
        market_regime: str = "unknown",
        warnings: list[str] | None = None,
        # C0/C1 additions (all optional)
        experiment_id: str = "unknown",
        guardrail_status: str = "unknown",
        duration_seconds: float | None = None,
        extra_alerts: list[ConsoleAlert] | None = None,
        # C2 additions (all optional)
        price_integrity: dict[str, Any] | None = None,
        api_metrics: dict[str, Any] | None = None,
        ai_metrics: dict[str, Any] | None = None,
        # R2-B: ETF vs Stock breakdown (optional)
        asset_class_breakdown: dict[str, Any] | None = None,
        # R6-E: exit attribution breakdown (optional)
        exit_attribution_breakdown: dict[str, Any] | None = None,
        # R6-D: Broker/Tracker diff (optional)
        broker_tracker_diff: dict[str, Any] | None = None,
    ) -> "ConsoleSummary":
        decisions = decisions or []
        submissions = submissions or []
        stale_symbols = stale_symbols or []
        extra_alerts = extra_alerts or []

        buy_dec = sum(1 for d in decisions if getattr(d, "action", "") == "buy")
        sell_dec = sum(1 for d in decisions if getattr(d, "action", "") == "sell")
        deny_dec = sum(1 for d in decisions if getattr(d, "action", "") == "deny")
        submitted = sum(1 for s in submissions if getattr(s, "status", "") == "submitted")
        rejected = sum(1 for s in submissions if getattr(s, "status", "") == "rejected")

        # R6-D: Aggregate deny reasons from denied decisions
        deny_reason_counts: dict[str, int] = {}
        for d in decisions:
            if getattr(d, "action", "") == "deny":
                for reason in (getattr(d, "deny_reasons", None) or []):
                    deny_reason_counts[reason] = deny_reason_counts.get(reason, 0) + 1

        # Auto-generate alerts
        alerts: list[ConsoleAlert] = list(extra_alerts)
        missing: list[str] = []

        if stale_symbols:
            alerts.append(
                ConsoleAlert(
                    severity="warning",
                    code="stale_price_detected",
                    message=f"{len(stale_symbols)} symbol(s) had stale price data",
                    details={"symbols": stale_symbols[:10]},
                )
            )

        api_err = (api_metrics or {}).get("error_count", 0)
        if api_err > 0:
            alerts.append(
                ConsoleAlert(
                    severity="warning",
                    code="api_errors",
                    message=f"{api_err} API error(s) during run",
                    details={"error_count": api_err},
                )
            )

        token_used = (ai_metrics or {}).get("input_tokens", 0) + (ai_metrics or {}).get("output_tokens", 0)
        token_budget = (ai_metrics or {}).get("daily_token_budget", 300_000)
        if token_budget and token_used / max(token_budget, 1) > 0.80:
            alerts.append(
                ConsoleAlert(
                    severity="warning",
                    code="token_budget_high",
                    message=f"Token usage {token_used}/{token_budget} exceeds 80%",
                )
            )

        if guardrail_status == "halted":
            alerts.append(
                ConsoleAlert(
                    severity="critical",
                    code="guardrail_halted",
                    message="Guardrail circuit breaker is HALTED",
                )
            )

        # Keep a stable severity-first order for tests and downstream consumers.
        order = {"critical": 0, "warning": 1, "info": 2}
        alerts = sorted(alerts, key=lambda alert: order.get(alert.severity, 9))

        # Track missing metrics
        if equity == 0.0:
            missing.append("equity")
        if market_regime == "unknown":
            missing.append("market_regime")

        status = _compute_run_status(
            alerts=alerts,
            guardrail_status=guardrail_status,
            broker_tracker_mismatch_count=0,
            stale_price_count=len(stale_symbols),
            api_error_count=api_err,
        )

        return cls(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            equity=equity,
            open_position_count=open_position_count,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            signals_total=len(decisions),
            signals_buy=buy_dec,
            signals_sell=sell_dec,
            signals_deny=deny_dec,
            orders_submitted=submitted,
            orders_rejected=rejected,
            cluster_blocks=cluster_blocks or [],
            risk_budget_pct=risk_budget_pct,
            stale_symbols=stale_symbols,
            price_sources=price_sources or {},
            market_regime=market_regime,
            warnings=warnings or [],
            experiment_id=experiment_id,
            run_status=status,
            guardrail_status=guardrail_status,
            duration_seconds=duration_seconds,
            alerts=alerts,
            missing_metrics=missing,
            price_integrity=price_integrity or {},
            api_metrics=api_metrics or {},
            ai_metrics=ai_metrics or {},
            asset_class_breakdown=asset_class_breakdown or {},
            exit_attribution_breakdown=exit_attribution_breakdown or {},
            deny_reason_counts=deny_reason_counts,
            broker_tracker_diff=broker_tracker_diff or {},
        )
