"""Dashboard service for aggregating system data."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from console.adapters.cron_adapter import CronAdapter
from console.adapters.data_adapter import DataAdapter
from console.adapters.system_adapter import SystemAdapter
from console.utils.time_utils import now_iso

# P&L tracker
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
try:
    from stock_swing.tracking.pnl_tracker import PnLTracker
    from stock_swing.sources.broker_client import BrokerClient
    _HAS_TRACKER = True
except Exception:
    _HAS_TRACKER = False
    BrokerClient = None


class DashboardService:
    """Aggregates data from multiple adapters for dashboard display."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.cron_adapter = CronAdapter(project_root)
        self.data_adapter = DataAdapter(project_root)
        self.system_adapter = SystemAdapter(project_root)
        self._tracker = PnLTracker(project_root) if _HAS_TRACKER else None
        self._broker = None

    def get_dashboard(self) -> Dict[str, Any]:
        trading = self.get_trading()
        positions = self.get_positions(trading=trading)
        cron_jobs = self.get_cron_jobs()
        data_status = self.get_data_status()
        system = self.get_system_status()
        overview = self.get_overview(
            trading=trading,
            positions=positions,
            cron_jobs=cron_jobs,
            data_status=data_status,
            system=system,
        )
        return {
            "time": now_iso(),
            "alerts": self.get_alerts(
                overview=overview,
                trading=trading,
                positions=positions,
                cron_jobs=cron_jobs,
                data_status=data_status,
            ),
            "overview": overview,
            "charts": self.get_charts(trading=trading, positions=positions),
            "pipeline": self.get_pipeline_summary(trading=trading),
            "cron_jobs": cron_jobs,
            "reconciliation": self.get_reconciliation_status(),
            "data_status": data_status,
            "system": system,
            "trading": trading,
            "positions": positions,
            "logs": self.get_logs(),
        }

    def get_overview(
        self,
        trading: Dict[str, Any] | None = None,
        positions: Dict[str, Any] | None = None,
        cron_jobs: Dict[str, Any] | None = None,
        data_status: Dict[str, Any] | None = None,
        system: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        cron_jobs = cron_jobs or self.get_cron_jobs()
        data_status = data_status or self.get_data_status()
        system = system or self.get_system_status()
        trading = trading or self.get_trading()
        positions = positions or self.get_positions(trading=trading)
        trading_summary = trading.get("summary", {})
        positions_summary = positions.get("summary", {})
        return {
            "time": now_iso(),
            "health_score": system.get("score", 0),
            "health_status": system.get("status", "unknown"),
            "cron_jobs_active": cron_jobs.get("active", 0),
            "cron_jobs_total": cron_jobs.get("total", 0),
            "data_counts": data_status.get("counts", {}),
            "runtime_mode": system.get("runtime_mode", "unknown"),
            "trading_summary": trading_summary,
            "positions_summary": positions_summary,
            "deltas": self.get_deltas(trading=trading, positions=positions),
        }

    def get_cron_jobs(self) -> Dict[str, Any]:
        jobs = self.cron_adapter.get_jobs()
        now = datetime.now().astimezone()
        enriched_jobs = [self._enrich_cron_job(job, now) for job in jobs]
        return {
            "time": now_iso(),
            "jobs": enriched_jobs,
            "total": len(enriched_jobs),
            "active": len([j for j in enriched_jobs if j.get("enabled")]),
        }

    def get_data_status(self) -> Dict[str, Any]:
        counts = self.data_adapter.get_counts()
        freshness = self.data_adapter.get_freshness()
        return {
            "time": now_iso(),
            "counts": counts,
            "freshness": freshness,
            "integrity": self._build_integrity(counts=counts, freshness=freshness),
        }

    def get_system_status(self) -> Dict[str, Any]:
        return {
            "time": now_iso(),
            **self.system_adapter.get_health(),
        }

    def get_trading(self) -> Dict[str, Any]:
        """Get trading performance data from PnL tracker."""
        if not self._tracker:
            return {"available": False, "error": "PnLTracker not available"}

        try:
            self._tracker.state = self._tracker._load_state()
            open_positions = self._tracker.get_open_positions()
            current_prices = self._fetch_current_prices([p.get("symbol") for p in open_positions])
            summary = self._tracker.get_summary()
            recent = self._tracker.get_recent_trades(10)
            daily_snapshots = list(self._tracker.state.daily_snapshots)
            if daily_snapshots:
                latest = dict(daily_snapshots[-1])
                unrealized = 0.0
                for p in open_positions:
                    symbol = p.get("symbol")
                    curr = current_prices.get(symbol)
                    entry = float(p.get("entry_price") or 0.0)
                    qty = float(p.get("qty") or 0.0)
                    if curr is not None and entry:
                        unrealized += (curr - entry) * qty
                latest["unrealized_pnl"] = round(unrealized, 2)
                latest["total_pnl"] = round(float(latest.get("realized_pnl") or 0.0) + unrealized, 2)
                daily_snapshots[-1] = latest

            return {
                "available": True,
                "time": now_iso(),
                "summary": summary,
                "recent_trades": recent,
                "daily_snapshots": daily_snapshots[-30:],
                "open_positions": open_positions,
                "current_prices": current_prices,
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    def get_positions(self, trading: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Get open positions from PnL tracker."""
        if not self._tracker:
            return {"available": False, "positions": [], "summary": {}}

        try:
            self._tracker.state = self._tracker._load_state()
            positions = self._tracker.get_open_positions()
            current_prices = (trading or {}).get("current_prices") or self._fetch_current_prices([p.get("symbol") for p in positions])
            enriched_positions = [self._enrich_position(p, current_prices=current_prices) for p in positions]
            return {
                "available": True,
                "time": now_iso(),
                "positions": enriched_positions,
                "count": len(enriched_positions),
                "summary": self._summarize_positions(enriched_positions, trading=trading),
            }
        except Exception as e:
            return {"available": False, "positions": [], "summary": {}, "error": str(e)}

    def get_logs(self, max_lines: int = 200) -> Dict[str, Any]:
        """Get recent audit log lines."""
        today = datetime.now().strftime("%Y%m%d")
        log_path = self.project_root / "data" / "audits" / f"paper_demo_{today}.log"

        lines = []
        if log_path.exists():
            try:
                raw = log_path.read_text(encoding="utf-8").splitlines()
                lines = raw[-max_lines:]
            except Exception:
                pass

        # Also check daily report
        report_path = self.project_root / "data" / "audits" / f"daily_report_{datetime.now().strftime('%Y-%m-%d')}.txt"
        report_text = ""
        if report_path.exists():
            try:
                report_text = report_path.read_text(encoding="utf-8")
            except Exception:
                pass

        return {
            "time": now_iso(),
            "log_file": str(log_path),
            "lines": lines,
            "line_count": len(lines),
            "daily_report": report_text,
        }

    def get_deltas(self, trading: Dict[str, Any], positions: Dict[str, Any]) -> Dict[str, Any]:
        summary = trading.get("summary", {}) if trading else {}
        snapshots = trading.get("daily_snapshots", []) if trading else []
        latest = snapshots[-1] if snapshots else {}
        previous = snapshots[-2] if len(snapshots) >= 2 else {}
        latest_equity = latest.get("equity")
        prev_equity = previous.get("equity")
        latest_signals = latest.get("signals_generated")
        prev_signals = previous.get("signals_generated")
        latest_orders = latest.get("orders_submitted")
        prev_orders = previous.get("orders_submitted")
        decisions_now = (self.data_adapter.get_counts() or {}).get("decisions", 0)
        decisions_prev = max(0, decisions_now - (latest_signals or 0))
        return {
            "equity_vs_prev_snapshot": self._safe_delta(latest_equity, prev_equity),
            "open_trades_vs_prev_snapshot": None,
            "decisions_vs_prev_snapshot": decisions_now - decisions_prev,
            "signals_vs_prev_snapshot": self._safe_delta(latest_signals, prev_signals),
            "orders_vs_prev_snapshot": self._safe_delta(latest_orders, prev_orders),
            "equity_vs_prev_day": self._safe_delta(summary.get("peak_equity"), latest_equity),
            "unrealized_pnl": positions.get("summary", {}).get("unrealized_pnl"),
        }

    def get_charts(self, trading: Dict[str, Any], positions: Dict[str, Any]) -> Dict[str, Any]:
        snapshots = trading.get("daily_snapshots", []) if trading else []
        summary = trading.get("summary", {}) if trading else {}
        peak_equity = summary.get("peak_equity") or 0
        equity = []
        drawdown_pct = []
        open_positions = []
        signals_orders = []

        for idx, snap in enumerate(snapshots[-30:]):
            ts = f"{snap.get('date', '')}T00:00:00"
            eq = snap.get("equity")
            dd = None
            if peak_equity and eq is not None:
                dd = max(0.0, (peak_equity - eq) / peak_equity)
            equity.append({"ts": ts, "value": eq})
            drawdown_pct.append({"ts": ts, "value": dd})
            open_positions.append({"ts": ts, "value": positions.get("count", 0)})
            signals_orders.append({
                "ts": ts,
                "signals": snap.get("signals_generated"),
                "orders": snap.get("orders_submitted"),
            })

        return {
            "overview": {
                "equity": equity,
                "drawdown_pct": drawdown_pct,
                "open_positions": open_positions,
                "signals_orders": signals_orders,
            }
        }

    def get_pipeline_summary(self, trading: Dict[str, Any] | None = None) -> Dict[str, Any]:
        counts = self.data_adapter.get_counts() or {}
        decisions = self._load_recent_decisions(limit=500)
        audits = self._load_recent_audit_lines(limit=500)
        submission_events = [a for a in audits if a.get("category") == "submission" and a.get("action") == "submitted"]
        reconciliation_events = [a for a in audits if a.get("category") == "reconciliation"]
        paper_runs = self._summarize_paper_runs(audits)

        funnel = {
            "raw": counts.get("raw", 0),
            "normalized": counts.get("normalized", 0),
            "features": counts.get("features", 0),
            "signals": counts.get("signals", 0),
            "decisions": len(decisions),
            "risk_rejected": sum(1 for d in decisions if str(d.get("action", "")).lower() == "deny" or str(d.get("risk_state", "")).lower() != "pass"),
            "orders_submitted": len(submission_events),
            "orders_filled": len(submission_events),
            "reconciliations": len(reconciliation_events),
            "paper_runs": len(paper_runs),
            "positions_opened": trading.get("summary", {}).get("open_trades", 0) if trading else 0,
            "positions_closed": trading.get("summary", {}).get("closed_trades", 0) if trading else 0,
        }

        by_strategy: Dict[str, Dict[str, Any]] = {}
        by_symbol: Dict[str, Dict[str, Any]] = {}
        decision_reasons: Dict[str, int] = {}
        normalized_reasons: Dict[str, int] = {}
        actions: Dict[str, int] = {}

        for d in decisions:
            strategy = d.get("strategy_id") or "unknown"
            symbol = d.get("symbol") or "unknown"
            action = str(d.get("action") or "unknown").lower()
            risk_state = str(d.get("risk_state") or "unknown").lower()
            deny_reasons = d.get("deny_reasons") or []

            s = by_strategy.setdefault(strategy, {"strategy_id": strategy, "decisions": 0, "buy": 0, "sell": 0, "deny": 0, "pass": 0, "reject": 0})
            s["decisions"] += 1
            s[action] = s.get(action, 0) + 1
            if risk_state == "pass":
                s["pass"] += 1
            else:
                s["reject"] += 1

            sym = by_symbol.setdefault(symbol, {"symbol": symbol, "decisions": 0, "buy": 0, "sell": 0, "deny": 0, "pass": 0, "reject": 0})
            sym["decisions"] += 1
            sym[action] = sym.get(action, 0) + 1
            if risk_state == "pass":
                sym["pass"] += 1
            else:
                sym["reject"] += 1

            actions[action] = actions.get(action, 0) + 1
            for reason in deny_reasons:
                raw_reason = str(reason)
                decision_reasons[raw_reason] = decision_reasons.get(raw_reason, 0) + 1
                normalized = self._normalize_rejection_reason(raw_reason)
                normalized_reasons[normalized] = normalized_reasons.get(normalized, 0) + 1

        if not decision_reasons and funnel["risk_rejected"] > 0:
            decision_reasons["deny_without_reason"] = funnel["risk_rejected"]
            normalized_reasons["deny_without_reason"] = funnel["risk_rejected"]

        execution_by_symbol: Dict[str, Dict[str, Any]] = {}
        for evt in submission_events:
            parsed = self._parse_submission_details(evt.get("details", ""))
            symbol = parsed.get("symbol") or "unknown"
            row = execution_by_symbol.setdefault(symbol, {"symbol": symbol, "submitted": 0, "buy": 0, "sell": 0, "qty": 0})
            row["submitted"] += 1
            side = parsed.get("side") or "unknown"
            row[side] = row.get(side, 0) + 1
            row["qty"] += parsed.get("qty") or 0

        position_symbols = {str(p.get("symbol") or "unknown").upper(): p for p in ((trading or {}).get("open_positions") or [])}

        def empty_symbol_row(symbol: str) -> Dict[str, Any]:
            return {
                "symbol": symbol,
                "decisions": 0,
                "buy": 0,
                "sell": 0,
                "deny": 0,
                "pass": 0,
                "reject": 0,
                "submitted": 0,
                "submitted_buy": 0,
                "submitted_sell": 0,
                "submitted_qty": 0,
                "open_position": False,
                "position_qty": 0,
                "conversion_rate": 0.0,
                "holding_days": None,
                "unrealized_pnl": None,
                "strategy_ids": [],
            }

        merged_symbol_stats: Dict[str, Dict[str, Any]] = {}
        strategy_map: Dict[str, set[str]] = {}
        for d in decisions:
            symbol = str(d.get("symbol") or "unknown").upper()
            strategy_map.setdefault(symbol, set()).add(str(d.get("strategy_id") or "unknown"))

        for sym_row in by_symbol.values():
            symbol = str(sym_row.get("symbol") or "unknown").upper()
            merged = merged_symbol_stats.setdefault(symbol, empty_symbol_row(symbol))
            for key in ["decisions", "buy", "sell", "deny", "pass", "reject"]:
                merged[key] = sym_row.get(key, 0)
            merged["strategy_ids"] = sorted(strategy_map.get(symbol, set()))

        for sub_row in execution_by_symbol.values():
            symbol = str(sub_row.get("symbol") or "unknown").upper()
            merged = merged_symbol_stats.setdefault(symbol, empty_symbol_row(symbol))
            merged["submitted"] = sub_row.get("submitted", 0)
            merged["submitted_buy"] = sub_row.get("buy", 0)
            merged["submitted_sell"] = sub_row.get("sell", 0)
            merged["submitted_qty"] = sub_row.get("qty", 0)

        enriched_positions = positions.get("positions", []) if (positions := self.get_positions(trading=trading)).get("available") else []
        for pos in enriched_positions:
            symbol = str(pos.get("symbol") or "unknown").upper()
            merged = merged_symbol_stats.setdefault(symbol, empty_symbol_row(symbol))
            merged["open_position"] = True
            merged["position_qty"] = pos.get("qty") or 0
            merged["holding_days"] = pos.get("holding_days")
            merged["unrealized_pnl"] = pos.get("unrealized_pnl")
            if pos.get("strategy_id"):
                merged["strategy_ids"] = sorted(set(merged.get("strategy_ids") or []).union({str(pos.get("strategy_id"))}))

        for row in merged_symbol_stats.values():
            row["conversion_rate"] = round((row.get("submitted", 0) / row.get("decisions", 0)) if row.get("decisions", 0) else 0.0, 3)

        discrepancies = self._summarize_reconciliation_discrepancies(reconciliation_events)

        return {
            "funnel": funnel,
            "actions": [{"action": k, "count": v} for k, v in sorted(actions.items(), key=lambda item: item[1], reverse=True)],
            "by_strategy": sorted(by_strategy.values(), key=lambda x: x.get("decisions", 0), reverse=True)[:10],
            "by_symbol": sorted(by_symbol.values(), key=lambda x: x.get("decisions", 0), reverse=True)[:10],
            "symbol_overview": sorted(merged_symbol_stats.values(), key=lambda x: (x.get("decisions", 0), x.get("submitted", 0)), reverse=True)[:15],
            "runs": paper_runs[:10],
            "execution": {
                "submitted_orders": len(submission_events),
                "reconciliations": len(reconciliation_events),
                "fills_estimated": len(submission_events),
                "recent_submissions": [dict(evt, **self._parse_submission_details(evt.get("details", ""))) for evt in submission_events[:10]],
                "by_symbol": sorted(execution_by_symbol.values(), key=lambda x: x.get("submitted", 0), reverse=True)[:10],
                "discrepancies": discrepancies,
            },
            "rejections": {
                "decision_reasons": [{"reason": k, "count": v} for k, v in sorted(decision_reasons.items(), key=lambda item: item[1], reverse=True)],
                "normalized_reasons": [{"reason": k, "count": v} for k, v in sorted(normalized_reasons.items(), key=lambda item: item[1], reverse=True)],
            }
        }

    def get_reconciliation_status(self) -> Dict[str, Any]:
        lines = self._load_recent_audit_lines(limit=500)
        rec_events = [l for l in lines if l.get("category") == "reconciliation"]
        sub_events = [l for l in lines if l.get("category") == "submission"]
        discrepancy_counts: Dict[str, int] = {}
        by_symbol: Dict[str, Dict[str, Any]] = {}
        last_run = rec_events[0].get("ts") if rec_events else None
        last_success = None
        pending_or_mismatched = 0

        for evt in rec_events:
            details = str(evt.get("details") or "")
            if "0 discrepancies" in details:
                last_success = last_success or evt.get("ts")
                normalized = "ok"
            elif "qty_mismatch" in details:
                normalized = "qty_mismatch"
                pending_or_mismatched += 1
            elif "status_mismatch" in details:
                normalized = "status_mismatch"
                pending_or_mismatched += 1
            elif "order_not_found" in details:
                normalized = "order_not_found"
                pending_or_mismatched += 1
            elif "1 discrepancies" in details:
                normalized = "single_discrepancy"
                pending_or_mismatched += 1
            else:
                normalized = details.split(":", 1)[1].strip() if ":" in details else details
                if normalized != "ok":
                    pending_or_mismatched += 1
            discrepancy_counts[normalized] = discrepancy_counts.get(normalized, 0) + 1

        pending_orders = []
        for evt in sub_events[:30]:
            parsed = self._parse_submission_details(str(evt.get("details") or ""))
            symbol = parsed.get("symbol") or "unknown"
            side = parsed.get("side") or "unknown"
            qty = parsed.get("qty") or 0
            matching_rec = next((r for r in rec_events if r.get("subject") == evt.get("subject")), None)
            rec_details = str(matching_rec.get("details") or "") if matching_rec else ""
            if not matching_rec:
                status = "pending_reconcile"
            elif "0 discrepancies" in rec_details:
                status = "reconciled_ok"
            elif "status_mismatch" in rec_details:
                status = "status_mismatch"
            elif "qty_mismatch" in rec_details:
                status = "qty_mismatch"
            else:
                status = "mismatch"
            pending_orders.append({
                "ts": evt.get("ts"),
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "status": status,
            })
            row = by_symbol.setdefault(symbol, {"symbol": symbol, "submissions": 0, "buy": 0, "sell": 0, "mismatches": 0})
            row["submissions"] += 1
            row[side] = row.get(side, 0) + 1
            if status != "reconciled_ok":
                row["mismatches"] += 1

        return {
            "recent_reconciliations": len(rec_events),
            "recent_submissions": len(sub_events),
            "pending_or_mismatched": pending_or_mismatched,
            "last_run": last_run,
            "last_success": last_success,
            "discrepancy_types": [{"reason": k, "count": v} for k, v in sorted(discrepancy_counts.items(), key=lambda item: item[1], reverse=True)[:10]],
            "by_symbol": sorted(by_symbol.values(), key=lambda x: (x.get("mismatches", 0), x.get("submissions", 0)), reverse=True)[:10],
            "pending_orders": pending_orders,
        }

    def get_alerts(
        self,
        overview: Dict[str, Any],
        trading: Dict[str, Any],
        positions: Dict[str, Any],
        cron_jobs: Dict[str, Any],
        data_status: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        counts = data_status.get("counts", {})
        freshness = data_status.get("freshness", {})
        trading_summary = trading.get("summary", {}) if trading else {}
        positions_summary = positions.get("summary", {}) if positions else {}
        integrity = data_status.get("integrity", {})

        upstream_empty = all((counts.get(stage, 0) == 0) for stage in ["raw", "normalized", "features", "signals"])
        if counts.get("decisions", 0) > 0 and upstream_empty:
            alerts.append({
                "severity": "critical",
                "code": "pipeline_inconsistency",
                "title": "Pipeline inconsistency",
                "message": "decisions exist while upstream stages are empty",
                "action_hint": "Inspect collection and analysis outputs",
                "updated_at": now_iso(),
            })

        if trading_summary.get("open_trades", 0) > 0 and trading_summary.get("closed_trades", 0) == 0:
            alerts.append({
                "severity": "warning",
                "code": "no_closed_trades",
                "title": "No closed trades recorded",
                "message": f"{trading_summary.get('open_trades', 0)} open positions but 0 closed trades",
                "action_hint": "Check exit logic and fill tracking",
                "updated_at": now_iso(),
            })

        decisions_freshness = freshness.get("decisions", {})
        if decisions_freshness.get("status") in {"aging", "stale"}:
            alerts.append({
                "severity": "warning",
                "code": "decision_freshness",
                "title": "Decision artifacts are aging",
                "message": f"Latest decision artifact is {decisions_freshness.get('age_hours')}h old",
                "action_hint": "Inspect data collection / analysis schedules",
                "updated_at": now_iso(),
            })

        if positions_summary.get("largest_position_weight", 0) >= 0.15:
            alerts.append({
                "severity": "warning",
                "code": "position_concentration",
                "title": "Position concentration elevated",
                "message": f"Largest position weight is {positions_summary.get('largest_position_weight', 0):.1%}",
                "action_hint": "Review exposure caps and symbol concentration",
                "updated_at": now_iso(),
            })

        stale_jobs = [j for j in cron_jobs.get("jobs", []) if j.get("enabled") and j.get("lag_seconds", 0) > 0]
        if stale_jobs:
            alerts.append({
                "severity": "warning",
                "code": "cron_lag",
                "title": "Cron lag detected",
                "message": f"{len(stale_jobs)} scheduled job(s) appear behind schedule",
                "action_hint": "Check scheduler health and recent runs",
                "updated_at": now_iso(),
            })

        long_holds = [p for p in positions.get("positions", []) if (p.get("holding_days") or 0) >= 10]
        if long_holds:
            alerts.append({
                "severity": "warning",
                "code": "long_holding_positions",
                "title": "Long holding positions detected",
                "message": f"{len(long_holds)} position(s) held for 10+ days",
                "action_hint": "Review stale positions and exit criteria",
                "updated_at": now_iso(),
            })

        low_conversion = [r for r in (self.get_pipeline_summary(trading=trading).get("symbol_overview", [])) if r.get("decisions", 0) >= 10 and r.get("conversion_rate", 0) == 0]
        if low_conversion:
            alerts.append({
                "severity": "warning",
                "code": "zero_conversion_symbols",
                "title": "Symbols with zero conversion",
                "message": f"{len(low_conversion)} symbol(s) have decisions but no submissions",
                "action_hint": "Review risk gates, sizing, and execution eligibility",
                "updated_at": now_iso(),
            })

        if integrity.get("status") == "fail":
            alerts.append({
                "severity": "critical",
                "code": "data_integrity_fail",
                "title": "Data integrity checks failed",
                "message": "One or more dashboard integrity checks failed",
                "action_hint": "Inspect Data Status tab for details",
                "updated_at": now_iso(),
            })

        severity_order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(alerts, key=lambda a: severity_order.get(a.get("severity", "info"), 99))

    def _build_integrity(self, counts: Dict[str, int], freshness: Dict[str, Any]) -> Dict[str, Any]:
        checks = []
        upstream_empty = all(counts.get(stage, 0) == 0 for stage in ["raw", "normalized", "features", "signals"])
        decisions_count = counts.get("decisions", 0)
        if decisions_count > 0 and upstream_empty:
            checks.append({
                "name": "upstream_presence",
                "status": "fail",
                "message": f"decisions={decisions_count} but raw/normalized/features/signals are empty",
            })
        else:
            checks.append({
                "name": "upstream_presence",
                "status": "ok",
                "message": "Upstream stages contain artifacts consistent with decisions",
            })

        decision_freshness = freshness.get("decisions", {})
        decision_status = decision_freshness.get("status", "unknown")
        checks.append({
            "name": "decision_freshness",
            "status": "warn" if decision_status in {"aging", "stale"} else "ok",
            "message": (
                f"Newest decision artifact is {decision_freshness.get('age_hours')}h old"
                if decision_freshness.get("age_hours") is not None
                else "No decision artifact freshness data"
            ),
        })

        failures = sum(1 for c in checks if c["status"] == "fail")
        warns = sum(1 for c in checks if c["status"] == "warn")
        status = "fail" if failures else "warning" if warns else "ok"
        return {"status": status, "checks": checks}

    def _enrich_cron_job(self, job: Dict[str, Any], now: datetime) -> Dict[str, Any]:
        enriched = dict(job)
        next_run = self._parse_iso_datetime(enriched.get("next_run"))
        last_run = datetime.fromtimestamp(enriched.get("updatedAtMs", 0) / 1000, tz=timezone.utc).astimezone() if enriched.get("updatedAtMs") else None
        last_success = last_run if enriched.get("enabled") else None
        duration_ms = 0
        if next_run and last_run:
            duration_ms = max(0, int((next_run - last_run).total_seconds() * 1000))
        lag_seconds = 0
        if next_run and next_run < now and enriched.get("enabled"):
            lag_seconds = int((now - next_run).total_seconds())

        enriched.update({
            "last_run": last_run.isoformat() if last_run else None,
            "last_success": last_success.isoformat() if last_success else None,
            "last_failure": None,
            "last_duration_ms": duration_ms or None,
            "avg_duration_ms": duration_ms or None,
            "success_rate_7d": 1.0 if enriched.get("enabled") else 0.0,
            "running": False,
            "lag_seconds": lag_seconds,
        })
        return enriched

    def _enrich_position(self, position: Dict[str, Any], current_prices: Dict[str, float] | None = None) -> Dict[str, Any]:
        enriched = dict(position)
        current_prices = current_prices or {}
        entry_price = float(enriched.get("entry_price") or 0.0)
        qty = float(enriched.get("qty") or 0.0)
        current_price = current_prices.get(enriched.get("symbol")) or (entry_price if entry_price > 0 else None)
        market_value = (current_price or 0.0) * qty if current_price is not None else None
        unrealized_pnl = ((current_price - entry_price) * qty) if current_price is not None and entry_price else None
        unrealized_return_pct = ((current_price - entry_price) / entry_price) if current_price is not None and entry_price else None
        entry_time = self._parse_iso_datetime(enriched.get("entry_time"))
        now = datetime.now().astimezone()
        holding_days = round((now - entry_time).total_seconds() / 86400, 1) if entry_time else None
        enriched.update({
            "current_price": current_price,
            "market_value": market_value,
            "unrealized_pnl": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
            "unrealized_return_pct": round(unrealized_return_pct, 4) if unrealized_return_pct is not None else None,
            "holding_days": holding_days,
            "portfolio_weight": None,
            "stop_price": None,
            "target_price": None,
            "sector": None,
        })
        return enriched

    def _summarize_positions(self, positions: List[Dict[str, Any]], trading: Dict[str, Any] | None = None) -> Dict[str, Any]:
        trading = trading or {}
        snapshots = trading.get("daily_snapshots", [])
        latest_equity = snapshots[-1].get("equity") if snapshots else None
        gross_exposure = sum(float(p.get("market_value") or 0.0) for p in positions)
        unrealized_pnl = sum(float(p.get("unrealized_pnl") or 0.0) for p in positions)
        avg_holding_days = round(sum((p.get("holding_days") or 0.0) for p in positions) / len(positions), 1) if positions else None

        if gross_exposure > 0:
            for p in positions:
                p["portfolio_weight"] = (float(p.get("market_value") or 0.0) / gross_exposure) if p.get("market_value") else 0.0

        weights = sorted((p.get("portfolio_weight") or 0.0) for p in positions)
        largest_weight = weights[-1] if weights else 0.0
        top5 = sum(weights[-5:]) if weights else 0.0
        return {
            "gross_exposure": gross_exposure,
            "net_exposure": gross_exposure,
            "long_count": len([p for p in positions if str(p.get("side", "")).lower() == "buy"]),
            "short_count": len([p for p in positions if str(p.get("side", "")).lower() == "sell"]),
            "largest_position_weight": largest_weight,
            "top5_concentration": top5,
            "unrealized_pnl": unrealized_pnl,
            "avg_holding_days": avg_holding_days,
        }

    def _fetch_current_prices(self, symbols: List[str | None]) -> Dict[str, float]:
        # Broker bootstrap is environment-dependent; fail closed.
        return {}

    def _parse_submission_details(self, details: str) -> Dict[str, Any]:
        text = details or ""
        if ":" in text:
            text = text.split(":", 1)[1].strip()
        parts = text.split()
        if len(parts) >= 3:
            side = parts[0].lower()
            try:
                qty = int(parts[1])
            except Exception:
                qty = 0
            symbol = parts[2].upper()
            return {"side": side, "qty": qty, "symbol": symbol}
        return {"side": None, "qty": 0, "symbol": None}

    def _summarize_reconciliation_discrepancies(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        total = 0
        for evt in events:
            details = str(evt.get("details") or "")
            if "Reconciliation:" in details:
                total += 1
                normalized = details.split(":", 1)[1].strip().lower().replace(" ", "_")
                counts[normalized] = counts.get(normalized, 0) + 1
        return {
            "total": total,
            "types": [{"reason": k, "count": v} for k, v in sorted(counts.items(), key=lambda item: item[1], reverse=True)]
        }

    def _normalize_rejection_reason(self, reason: str) -> str:
        text = (reason or "").strip().lower()
        if "position_size would exceed limit" in text:
            return "position_size_limit_exceeded"
        if "risk" in text and "exceed" in text:
            return "risk_limit_exceeded"
        if "approval" in text:
            return "operator_approval_required"
        if "duplicate" in text:
            return "duplicate_signal"
        if "cooldown" in text:
            return "cooldown_active"
        return text or "unknown"

    def _summarize_paper_runs(self, audits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        runs: List[Dict[str, Any]] = []
        current: Dict[str, Any] | None = None
        for evt in reversed(audits):
            if evt.get("category") == "system" and evt.get("action") == "paper_demo_start":
                if current:
                    runs.append(current)
                current = {
                    "started_at": evt.get("ts"),
                    "completed_at": None,
                    "decisions": 0,
                    "submitted": 0,
                    "symbols": evt.get("details"),
                    "conversion_rate": 0.0,
                }
                continue
            if current is None:
                continue
            if evt.get("category") == "decision":
                current["decisions"] += 1
            elif evt.get("category") == "submission":
                current["submitted"] += 1
            elif evt.get("category") == "system" and evt.get("action") == "paper_demo_complete":
                current["completed_at"] = evt.get("ts")
                current["summary"] = evt.get("details")
                current["conversion_rate"] = round((current["submitted"] / current["decisions"]) if current["decisions"] else 0.0, 3)
                runs.append(current)
                current = None
        if current:
            current["conversion_rate"] = round((current["submitted"] / current["decisions"]) if current["decisions"] else 0.0, 3)
            runs.append(current)
        runs.reverse()
        return runs

    def _load_recent_decisions(self, limit: int = 500) -> List[Dict[str, Any]]:
        decisions_dir = self.project_root / "data" / "decisions"
        if not decisions_dir.exists():
            return []
        files = sorted(decisions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        results: List[Dict[str, Any]] = []
        for path in files:
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return results

    def _load_recent_audit_lines(self, limit: int = 500) -> List[Dict[str, Any]]:
        audits_dir = self.project_root / "data" / "audits"
        if not audits_dir.exists():
            return []
        files = sorted(audits_dir.glob("paper_demo_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
        parsed: List[Dict[str, Any]] = []
        for path in files:
            try:
                for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                    evt = self._parse_audit_line(line)
                    if evt:
                        parsed.append(evt)
                    if len(parsed) >= limit:
                        return parsed
            except Exception:
                continue
        return parsed

    def _parse_audit_line(self, line: str) -> Dict[str, Any] | None:
        parts = [p.strip() for p in line.split(" | ", 6)]
        if len(parts) < 7:
            return None
        return {
            "ts": parts[0],
            "level": parts[1],
            "category": parts[2],
            "action": parts[3],
            "actor": parts[4],
            "subject": parts[5],
            "details": parts[6],
        }

    def _safe_delta(self, current: Any, previous: Any) -> Any:
        if current is None or previous is None:
            return None
        try:
            return round(float(current) - float(previous), 2)
        except Exception:
            return None

    def _parse_iso_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        except Exception:
            return None
