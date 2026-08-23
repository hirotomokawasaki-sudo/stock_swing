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

    # AUDIT FIX (2026-08-23): paper_demo.py's --dry-run branch previously
    # called ConsoleSummary.build()/.emit() with no way to distinguish the
    # resulting summary from a real scheduled paper run -- both write to the
    # exact same reports/console/latest_console_summary.json path. This let
    # a manual diagnostic dry-run silently "refresh" the evidence that
    # scripts/check_go_no_go.py's console_summary_freshness check reads,
    # making a stale/broken scheduled-run history look current. Persist
    # provenance explicitly so downstream consumers can require
    # dry_run=False evidence for real Go/No-Go decisions.
    dry_run: bool = False
    invocation_source: str = "unknown"  # e.g. "paper_demo_cli", "paper_demo_dry_run"

    # --- C2 additions ---
    price_integrity: dict[str, Any] = field(default_factory=dict)
    api_metrics: dict[str, Any] = field(default_factory=dict)
    ai_metrics: dict[str, Any] = field(default_factory=dict)

    # --- R2-B: ETF vs Stock breakdown ---
    asset_class_breakdown: dict[str, Any] = field(default_factory=dict)

    # --- 2026-08-14: attribution-quality breakdown (attributable vs
    # untracked-origin trades). See PnlTracker.get_attribution_quality_
    # breakdown() docstring for why this exists: the blended "overall PF"
    # conflates a materially-different-performing bucket of pre-2026-07-22
    # broker-reconstructed trades with no decision provenance.
    attribution_quality_breakdown: dict[str, Any] = field(default_factory=dict)

    # --- R6-E: Exit attribution breakdown ---
    exit_attribution_breakdown: dict[str, Any] = field(default_factory=dict)

    # --- R6-D: Decision Funnel detail + Broker/Tracker diff ---
    deny_reason_counts: dict[str, int] = field(default_factory=dict)
    broker_tracker_diff: dict[str, Any] = field(default_factory=dict)

    # --- RF: 台帳品質・フィルター情報 ---
    ledger_quality: dict[str, Any] = field(default_factory=dict)          # RF-1: clean/quarantined/attribution
    entry_filter_stats: dict[str, Any] = field(default_factory=dict)     # RF-6b: stock_reduced_blocked等
    sector_shock_shadow_count: int = 0                                   # RF-7: shadow発動回数
    ledger_gate_status: str = "UNKNOWN"                                  # R0-v2-A: VALID / INVALID / UNKNOWN
    equity_bridge: dict = field(default_factory=dict)                    # R0-v2-B: broker equity bridge
    funnel_stages: dict[str, int] = field(default_factory=dict)          # R6-v2: 7-stage decision funnel
    open_position_details: list[dict[str, Any]] = field(default_factory=list)  # entry signal per position
    circuit_breaker_detail: dict = field(default_factory=dict)           # triggered_at / triggered_rules / reason

    # --- Plan A: Stop Loss Health (2026-07-27) ---
    stop_loss_health: dict[str, Any] = field(default_factory=dict)

    # --- R7-v2-A: Source SLA (2026-07-30) ---
    source_sla: dict[str, Any] = field(default_factory=dict)
    # { "ok": bool, "required_sources": [...], "failing_sources": [...], "sources": [...] }
    # {
    #   "recent_30d": {count, net_pnl, avg_ret_pct},  # 30日以内の止損サマリー
    #   "suppression": {noise_7d, mid_3d, severe_1d, total},  # 今回 run の min_hold 抑制数
    #   "post_exit_check": {checked, correct_stops, correct_rate},  # 7-14日前止損の価格追跡
    #   "tiered_min_hold_enabled": bool,
    # }

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
                # AUDIT FIX (2026-08-23): provenance so Go/No-Go evidence
                # checks can require dry_run=False (a real scheduled/manual
                # non-dry-run) instead of trusting any write to this file.
                "dry_run": self.dry_run,
                "invocation_source": self.invocation_source,
                # R6-v2: separated status fields
                "last_run": {
                    "status": self.run_status,
                    "as_of": self.timestamp,
                    "guardrail": self.guardrail_status,
                },
                "data_quality": {
                    "status": self.ledger_gate_status,
                    "as_of": self.timestamp,
                    "details": {
                        "overlap": 0,
                        "reversed_chronology": 0,
                        "holding_days_missing": self.ledger_quality.get("negative_holding_days_in_clean", 0),
                        "attribution_coverage_pct": self.ledger_quality.get("attribution_coverage_pct"),
                    },
                },
            },
            "health": {
                "status": self.run_status,
                "critical_count": sum(1 for a in self.alerts if a.severity == "critical"),
                "warning_count": sum(1 for a in self.alerts if a.severity == "warning"),
                "stale_price_count": len(self.stale_symbols),
                "broker_tracker_mismatch_count": (
                    self.broker_tracker_diff.get("mismatch_count", 0)
                ),
                "api_error_count": self.api_metrics.get("error_count", 0),
                "guardrail_status": self.guardrail_status,
                # RF-1: 台帳品質ヘッドライン
                "attribution_coverage_pct": self.ledger_quality.get("attribution_coverage_pct"),
                "quarantined_trades": self.ledger_quality.get("quarantined", 0),
                # R0-v2-A: safety gate
                "ledger_gate_status": self.ledger_gate_status,
                # circuit breaker detail (triggered_at / triggered_rules for renderer)
                "circuit_breaker_detail": self.circuit_breaker_detail,
                # R0-v2-B: equity bridge
                "equity_bridge": self.equity_bridge,
            },
            "portfolio": {
                "equity": round(self.equity, 2),
                "realized_pnl": round(self.realized_pnl, 2),
                "unrealized_pnl": round(self.unrealized_pnl, 2),
                "total_pnl": round(self.realized_pnl + self.unrealized_pnl, 2),
                "open_positions": self.open_position_count,
                "asset_class_breakdown": self.asset_class_breakdown,
                "attribution_quality_breakdown": self.attribution_quality_breakdown,
                "exit_attribution_breakdown": self.exit_attribution_breakdown,
                "open_position_details": self.open_position_details,
            },
            "stop_loss_health": self.stop_loss_health,
            "decision_funnel": {
                "candidates": self.signals_total,
                "buy": self.signals_buy,
                "sell": self.signals_sell,
                "deny": self.signals_deny,
                "submitted": self.orders_submitted,
                "rejected": self.orders_rejected,
                "blocked": len(self.cluster_blocks),
                "deny_reasons": self.deny_reason_counts,
                "stages": self.funnel_stages,
                # RF-6b: stock-reduced modeブロック数
                "stock_reduced_blocked": len(
                    self.entry_filter_stats.get("stock_reduced_blocked", [])
                ),
                "stock_reduced_blocked_symbols": (
                    self.entry_filter_stats.get("stock_reduced_blocked", [])[:10]
                ),
                # BUY STOP LIST: 永続的にブロックされている全銘柄（run非依存）
                "buy_stop_list": self.entry_filter_stats.get("buy_stop_list", []),
                # 2026-08-05: 小サンプルウォッチリスト（可視化のみ、自動ブロックしない）
                "small_sample_watchlist": self.entry_filter_stats.get("small_sample_watchlist", []),
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
            # RF: 台帳品質・フィルター・シャドウ
            "ledger_quality": self.ledger_quality,
            "sector_shock_shadow": {
                "shadow_count": self.sector_shock_shadow_count,
            },
            # R7-v2-A: Source SLA
            "source_sla": self.source_sla,
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
        # 2026-08-14: attribution-quality breakdown (optional)
        attribution_quality_breakdown: dict[str, Any] | None = None,
        # R6-E: exit attribution breakdown (optional)
        exit_attribution_breakdown: dict[str, Any] | None = None,
        # R6-D: Broker/Tracker diff (optional)
        broker_tracker_diff: dict[str, Any] | None = None,
        # RF 追加パラメータ（全てoptional）
        ledger_quality: dict[str, Any] | None = None,
        entry_filter_stats: dict[str, Any] | None = None,
        sector_shock_shadow_count: int = 0,
        # R0-v2-A: safety containment
        ledger_gate_status: str = "UNKNOWN",
        # R0-v2-B: broker equity bridge
        equity_bridge: dict | None = None,
        # R6-v2: full funnel stages
        funnel_stages: dict[str, int] | None = None,
        # open position signal details
        open_position_details: list[dict[str, Any]] | None = None,
        # circuit breaker detail (triggered_at, triggered_rules, reason)
        circuit_breaker_detail: dict | None = None,
        # Plan A: Stop Loss Health (2026-07-27)
        stop_loss_health: dict[str, Any] | None = None,
        # R7-v2-A: Source SLA (2026-07-30)
        source_sla: dict[str, Any] | None = None,
        # AUDIT FIX (2026-08-23): dry-run provenance (see field docstring above)
        dry_run: bool = False,
        invocation_source: str = "unknown",
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

        # G2 fix + G1-v2 peak clarity:
        # Use real_mismatch_count (lag-excluded) for health status and alerts.
        # raw mismatch_count is still in broker_tracker_diff for full observability.
        _bt = broker_tracker_diff or {}
        _raw_mismatch_count = _bt.get("mismatch_count", 0)
        _mismatch_count = _bt.get("real_mismatch_count", _raw_mismatch_count)  # adjusted
        _lag_presence = _bt.get("lag_excused_presence", [])
        _lag_qty = _bt.get("lag_excused_qty", [])
        if _mismatch_count > 0 and not any(a.code == "broker_tracker_mismatch" for a in alerts):
            # Compute real (non-lag) tracker_only/broker_only for the alert
            _lag_syms = set(_lag_presence) | set(_lag_qty)
            _real_tracker_only = [s for s in _bt.get("tracker_only", []) if s not in _lag_syms]
            _real_broker_only  = [s for s in _bt.get("broker_only",  []) if s not in _lag_syms]
            _real_qty_mm = [q for q in _bt.get("qty_mismatches", []) if q["symbol"] not in _lag_syms]
            alerts.append(
                ConsoleAlert(
                    severity="critical",
                    code="broker_tracker_mismatch",
                    message=f"Broker/tracker mismatch: {_mismatch_count} real position(s) differ"
                            + (f" ({_raw_mismatch_count - _mismatch_count} lag-excused)" if _lag_presence or _lag_qty else ""),
                    details={
                        "mismatch_count": _mismatch_count,
                        "tracker_only": _real_tracker_only,
                        "broker_only": _real_broker_only,
                        "qty_mismatches": _real_qty_mm,
                        "lag_excused_presence": _lag_presence,
                        "lag_excused_qty": _lag_qty,
                    },
                )
            )
            # Re-sort after adding new alert
            alerts = sorted(alerts, key=lambda alert: order.get(alert.severity, 9))

        status = _compute_run_status(
            alerts=alerts,
            guardrail_status=guardrail_status,
            broker_tracker_mismatch_count=_mismatch_count,
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
            attribution_quality_breakdown=attribution_quality_breakdown or {},
            exit_attribution_breakdown=exit_attribution_breakdown or {},
            deny_reason_counts=deny_reason_counts,
            broker_tracker_diff=broker_tracker_diff or {},
            ledger_quality=ledger_quality or {},
            entry_filter_stats=entry_filter_stats or {},
            sector_shock_shadow_count=sector_shock_shadow_count,
            ledger_gate_status=ledger_gate_status,
            equity_bridge=equity_bridge or {},
            funnel_stages=funnel_stages or {},
            open_position_details=open_position_details or [],
            circuit_breaker_detail=circuit_breaker_detail or {},
            stop_loss_health=stop_loss_health or {},
            source_sla=source_sla or {},
            dry_run=dry_run,
            invocation_source=invocation_source,
        )
