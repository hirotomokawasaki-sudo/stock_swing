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
        self._broker = self._init_broker() if _HAS_TRACKER and BrokerClient else None

    def _init_broker(self):
        """Initialize broker client if credentials available."""
        try:
            import os
            api_key = os.environ.get("BROKER_API_KEY", "")
            api_secret = os.environ.get("BROKER_API_SECRET", "")
            if not api_key or not api_secret:
                return None
            return BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
        except Exception:
            return None

    def get_dashboard(self) -> Dict[str, Any]:
        trading = self.get_trading()
        positions = self.get_positions(trading=trading)
        cron_jobs = self.get_cron_jobs()
        data_status = self.get_data_status()
        system = self.get_system_status()
        news = self.get_news(trading=trading)
        pipeline = self.get_pipeline_summary(trading=trading)
        overview = self.get_overview(
            trading=trading,
            positions=positions,
            cron_jobs=cron_jobs,
            data_status=data_status,
            system=system,
        )
        source_reliability = self.get_source_reliability_report(news)
        news_ingestion = self.get_news_ingestion_status(news)
        return {
            "time": now_iso(),
            "alerts": self.get_alerts(
                overview=overview,
                trading=trading,
                positions=positions,
                cron_jobs=cron_jobs,
                data_status=data_status,
                news=news,
            ),
            "overview": overview,
            "charts": self.get_charts(trading=trading, positions=positions),
            "pipeline": pipeline,
            "cron_jobs": cron_jobs,
            "reconciliation": self.get_reconciliation_status(),
            "news": news,
            "news_ingestion": news_ingestion,
            "source_reliability": source_reliability,
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
        
        # Get account info (equity, cash, buying power)
        account_info = self._get_account_info()
        
        return {
            "time": now_iso(),
            "health_score": system.get("score", 0),
            "health_status": system.get("status", "unknown"),
            "cron_jobs_active": cron_jobs.get("active", 0),
            "cron_jobs_total": cron_jobs.get("total", 0),
            "data_counts": data_status.get("counts", {}),
            "runtime_mode": system.get("runtime_mode", "unknown"),
            "account": account_info,
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

            # Get closed trades from tracker state
            closed_trades = [dict(t) for t in self._tracker.state.trades if t.get("status") == "closed"]
            
            return {
                "available": True,
                "time": now_iso(),
                "summary": summary,
                "recent_trades": recent,
                "closed_trades": closed_trades,
                "daily_snapshots": daily_snapshots[-30:],
                "open_positions": open_positions,
                "current_prices": current_prices,
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    def get_positions(self, trading: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Get open positions from broker (fallback to PnL tracker if unavailable)."""
        # Try broker first (source of truth)
        if self._broker:
            try:
                broker_positions = self._broker.fetch_positions()
                broker_data = broker_positions.payload if hasattr(broker_positions, 'payload') else broker_positions
                
                if broker_data:
                    enriched_positions = [self._enrich_broker_position(p) for p in broker_data]
                    return {
                        "available": True,
                        "time": now_iso(),
                        "positions": enriched_positions,
                        "count": len(enriched_positions),
                        "summary": self._summarize_positions(enriched_positions, trading=trading),
                        "source": "broker",
                    }
            except Exception as e:
                # Fall through to tracker
                pass
        
        # Fallback to PnL tracker
        if not self._tracker:
            return {"available": False, "positions": [], "summary": {}, "source": "none"}

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
                "source": "tracker",
            }
        except Exception as e:
            return {"available": False, "positions": [], "summary": {}, "error": str(e), "source": "error"}

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

        news_by_symbol = getattr(self, '_last_news_by_symbol', {}) or {}
        for row in merged_symbol_stats.values():
            news = news_by_symbol.get(row['symbol'], {})
            row['news_count'] = news.get('news_count', 0)
            row['avg_news_sentiment'] = news.get('avg_sentiment', 0.0)
            row['avg_news_impact'] = news.get('avg_impact', 0.0)
            row['latest_news_headline_ja'] = news.get('latest_headline_ja', '')
            row['decision_referenced_news_count'] = news.get('decision_referenced', 0)

        # Calculate conversion rates
        conversion_rates = {
            "decisions_to_orders": round((funnel["orders_submitted"] / funnel["decisions"]) * 100, 1) if funnel["decisions"] else 0.0,
            "orders_to_fills": round((funnel["orders_filled"] / funnel["orders_submitted"]) * 100, 1) if funnel["orders_submitted"] else 0.0,
            "decisions_to_fills": round((funnel["orders_filled"] / funnel["decisions"]) * 100, 1) if funnel["decisions"] else 0.0,
            "raw_to_normalized": round((funnel["normalized"] / funnel["raw"]) * 100, 1) if funnel["raw"] else 0.0,
        }
        
        return {
            "funnel": funnel,
            "conversion_rates": conversion_rates,
            "actions": [{"action": k, "count": v} for k, v in sorted(actions.items(), key=lambda item: item[1], reverse=True)],
            "by_strategy": self._enrich_strategy_overview(by_strategy, submission_events),
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

    def get_news(self, trading: Dict[str, Any] | None = None) -> Dict[str, Any]:
        external_items = self._load_external_news_items(limit=200)
        decision_items = self._build_news_items_from_decisions(limit=50)
        tracked_symbols = {str(r.get('symbol') or 'UNKNOWN').upper() for r in (self.get_pipeline_summary(trading=trading).get('symbol_overview') or [])[:10]}
        items = external_items or decision_items
        loaded_items = list(items)
        linked_items = self._link_news_to_decisions(items, decision_items)
        for item in linked_items:
            item['is_tracked_symbol'] = str(item.get('symbol') or 'UNKNOWN').upper() in tracked_symbols
        selected_items = self._select_balanced_news_items(linked_items, limit=50)
        items = selected_items
        by_symbol = self._group_news_by_symbol(items)
        self._last_news_by_symbol = {str(row.get('symbol') or 'UNKNOWN').upper(): row for row in by_symbol}
        diagnostics = {
            'loaded_by_symbol': self._count_items_by_symbol(loaded_items),
            'linked_by_symbol': self._count_items_by_symbol(linked_items),
            'selected_by_symbol': self._count_items_by_symbol(selected_items),
        }
        return {
            "summary": self._summarize_news(items),
            "items": items,
            "by_symbol": by_symbol,
            "by_source": self._group_news_by_source(items),
            "by_event_type": self._group_news_by_event_type(items),
            "timeline": self._build_news_timeline(items),
            "selected": items[0] if items else None,
            "diagnostics": diagnostics,
        }

    def get_news_ingestion_status(self, news: Dict[str, Any]) -> Dict[str, Any]:
        items = news.get('items', []) if news else []
        latest_time = None
        oldest_time = None
        sources = set()
        symbols = set()
        source_counts: Dict[str, int] = {}
        now_dt = datetime.now().astimezone()
        requested_symbols = ['MRVL', 'CIEN', 'DELL', 'RBRK', 'PLTR', 'NOW', 'INTU', 'NBIS']
        collected_symbols = set()
        source_failures: Dict[str, int] = {}
        for item in items:
            ts = self._parse_iso_datetime(item.get('published_at'))
            if ts:
                if latest_time is None or ts > latest_time:
                    latest_time = ts
                if oldest_time is None or ts < oldest_time:
                    oldest_time = ts
            source = str(item.get('source') or 'unknown')
            symbol = str(item.get('symbol') or 'UNKNOWN').upper()
            sources.add(source)
            symbols.add(symbol)
            collected_symbols.add(symbol)
            source_counts[source] = source_counts.get(source, 0) + 1
        freshness_hours = round((now_dt - latest_time).total_seconds() / 3600, 2) if latest_time else None
        displayed_symbols = {str(i.get('symbol') or 'UNKNOWN').upper() for i in items}
        displayed_tracked_symbols = {s for s in displayed_symbols if s in requested_symbols}
        displayed_non_tracked_symbols = sorted(s for s in displayed_symbols if s not in requested_symbols)
        raw_collected_symbols = set()
        missing_symbols = [s for s in requested_symbols if s not in displayed_tracked_symbols]
        missing_symbol_reasons = []
        failure_reason_counts: Dict[str, int] = {}
        status_path = self.project_root / 'data' / 'audits' / 'news_collection_status.json'
        if status_path.exists():
            try:
                status_obj = json.loads(status_path.read_text(encoding='utf-8'))
                for row in status_obj.get('symbols', []):
                    symbol = str(row.get('symbol') or '').upper()
                    raw_collected_symbols.add(symbol)
                    reason = str(row.get('reason') or 'unknown')
                    display_reason = reason
                    if symbol in raw_collected_symbols and symbol not in displayed_symbols:
                        display_reason = 'collected_but_not_displayed'
                    elif symbol in raw_collected_symbols and symbol in displayed_symbols:
                        display_reason = 'collected_and_displayed'
                    if symbol in missing_symbols or row.get('used_fallback') or display_reason != 'collected_and_displayed':
                        missing_symbol_reasons.append({'symbol': symbol, 'reason': display_reason, 'used_fallback': bool(row.get('used_fallback'))})
                        failure_reason_counts[display_reason] = failure_reason_counts.get(display_reason, 0) + 1
            except Exception:
                pass
        if missing_symbols:
            source_failures['coverage_gap'] = len(missing_symbols)
        cron_jobs = self.get_cron_jobs().get('jobs', [])
        news_job = next((j for j in cron_jobs if j.get('name') == 'stock_swing_news_collection'), None)
        last_success = latest_time.isoformat() if latest_time else None
        last_failure = None if not missing_symbols else now_iso()
        failure_count_24h = len(missing_symbols)
        status = 'stale' if freshness_hours is not None and freshness_hours > 24 else 'ok' if items else 'empty'
        if missing_symbols and status == 'ok':
            status = 'partial'
        return {
            'latest_news_time': latest_time.isoformat() if latest_time else None,
            'oldest_news_time': oldest_time.isoformat() if oldest_time else None,
            'freshness_hours': freshness_hours,
            'total_items': len(items),
            'sources': sorted(sources),
            'symbols_covered': len(symbols),
            'source_counts': [{'source': k, 'count': v} for k, v in sorted(source_counts.items(), key=lambda item: item[1], reverse=True)],
            'status': status,
            'last_success': last_success,
            'last_failure': last_failure,
            'failure_count_24h': failure_count_24h,
            'source_failures': [{'source': k, 'count': v} for k, v in source_failures.items()],
            'symbols_requested': len(requested_symbols),
            'symbols_collected': len(displayed_tracked_symbols),
            'raw_symbols_collected': len(raw_collected_symbols),
            'displayed_symbols_collected': len(displayed_symbols),
            'displayed_tracked_symbols_collected': len(displayed_tracked_symbols),
            'displayed_non_tracked_symbols': displayed_non_tracked_symbols,
            'missing_symbols': missing_symbols,
            'missing_symbol_reasons': missing_symbol_reasons,
            'failure_reason_counts': [{'reason': k, 'count': v} for k, v in sorted(failure_reason_counts.items(), key=lambda item: item[1], reverse=True)],
            'news_collection_job': news_job,
        }

    def get_source_reliability_report(self, news: Dict[str, Any]) -> Dict[str, Any]:
        items = news.get('items', []) if news else []
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in items:
            source = str(item.get('source') or 'unknown')
            row = grouped.setdefault(source, {
                'source': source,
                'current_reliability': float(item.get('source_reliability') or self._source_reliability(source)),
                'count': 0,
                'used_count': 0,
                'avg_influence': 0.0,
                'avg_sentiment_abs': 0.0,
                'avg_impact': 0.0,
                'observed_quality_score': 0.0,
                'suggested_reliability': 0.0,
                'delta': 0.0,
            })
            row['count'] += 1
            row['used_count'] += 1 if item.get('used_in_decision') else 0
            row['avg_influence'] += float(item.get('influence_score') or 0.0)
            row['avg_sentiment_abs'] += abs(float(item.get('sentiment_score') or 0.0))
            row['avg_impact'] += float(item.get('impact_score') or 0.0)
        rows = []
        for row in grouped.values():
            count = max(1, row['count'])
            row['avg_influence'] = round(row['avg_influence'] / count, 2)
            row['avg_sentiment_abs'] = round(row['avg_sentiment_abs'] / count, 2)
            row['avg_impact'] = round(row['avg_impact'] / count, 2)
            used_ratio = row['used_count'] / count
            observed = round(min(1.0, 0.35 * used_ratio + 0.35 * row['avg_influence'] + 0.15 * row['avg_impact'] + 0.15 * row['avg_sentiment_abs']), 2)
            suggested = round(0.7 * row['current_reliability'] + 0.3 * observed, 2)
            row['observed_quality_score'] = observed
            row['suggested_reliability'] = suggested
            row['delta'] = round(suggested - row['current_reliability'], 2)
            rows.append(row)
        history_path = self.project_root / 'data' / 'audits' / 'source_reliability_history.json'
        history = []
        if history_path.exists():
            try:
                history = json.loads(history_path.read_text(encoding='utf-8'))
            except Exception:
                history = []
        snapshot = {
            'time': now_iso(),
            'rows': rows,
        }
        if not history or history[-1].get('time', '')[:10] != snapshot['time'][:10]:
            history.append(snapshot)
            history = history[-30:]
            try:
                history_path.parent.mkdir(parents=True, exist_ok=True)
                history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception:
                pass
        return {
            'rows': sorted(rows, key=lambda x: x.get('count', 0), reverse=True),
            'summary': {
                'sources': len(rows),
                'with_positive_delta': sum(1 for r in rows if r.get('delta', 0) > 0),
                'with_negative_delta': sum(1 for r in rows if r.get('delta', 0) < 0),
            },
            'history': history[-7:],
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

        # Fetch broker truth for pending orders
        pending_orders = self._fetch_broker_pending_orders(sub_events[:30], rec_events)

        for order in pending_orders:
            symbol = order.get("symbol") or "unknown"
            side = order.get("side") or "unknown"
            status = order.get("status") or "unknown"
            row = by_symbol.setdefault(symbol, {"symbol": symbol, "submissions": 0, "buy": 0, "sell": 0, "mismatches": 0})
            row["submissions"] += 1
            row[side] = row.get(side, 0) + 1
            if status not in {"reconciled_ok", "filled"}:
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

    def _fetch_broker_pending_orders(self, sub_events: List[Dict[str, Any]], rec_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fetch broker truth for pending orders."""
        if not self._broker:
            # Fallback to audit-based status
            pending_orders = []
            for evt in sub_events:
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
                    "broker_status": None,
                    "broker_filled_qty": None,
                })
            return pending_orders

        try:
            # Fetch broker orders directly
            broker_orders_env = self._broker.fetch_orders(status="all", limit=100)
            broker_orders = broker_orders_env.payload if hasattr(broker_orders_env, "payload") else []
            broker_map = {}
            for order in broker_orders:
                symbol = str(order.get("symbol") or "").upper()
                side = str(order.get("side") or "").lower()
                key = f"{symbol}_{side}"
                if key not in broker_map:
                    broker_map[key] = order

            pending_orders = []
            for evt in sub_events:
                parsed = self._parse_submission_details(str(evt.get("details") or ""))
                symbol = parsed.get("symbol") or "unknown"
                side = parsed.get("side") or "unknown"
                qty = parsed.get("qty") or 0
                key = f"{symbol}_{side}"
                broker_order = broker_map.get(key)
                
                if broker_order:
                    broker_status = str(broker_order.get("status") or "unknown").lower()
                    filled_qty = float(broker_order.get("filled_qty") or 0)
                    if broker_status in {"filled", "partially_filled"} and filled_qty == qty:
                        status = "filled"
                    elif broker_status == "canceled":
                        status = "canceled"
                    elif broker_status == "rejected":
                        status = "rejected"
                    elif broker_status == "accepted":
                        status = "accepted"
                    else:
                        status = broker_status
                else:
                    status = "pending_reconcile"
                    broker_status = None
                    filled_qty = None

                pending_orders.append({
                    "ts": evt.get("ts"),
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "status": status,
                    "broker_status": broker_status if broker_order else None,
                    "broker_filled_qty": filled_qty if broker_order else None,
                })
            return pending_orders
        except Exception:
            # Fallback to audit-based on error
            return self._fetch_broker_pending_orders(sub_events, rec_events)

    def get_alerts(
        self,
        overview: Dict[str, Any],
        trading: Dict[str, Any],
        positions: Dict[str, Any],
        cron_jobs: Dict[str, Any],
        data_status: Dict[str, Any],
        news: Dict[str, Any] | None = None,
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

        news = news or {}
        news_by_symbol = {str(r.get('symbol') or 'UNKNOWN').upper(): r for r in (news.get('by_symbol') or [])}
        tracked_symbols = [str(r.get('symbol') or 'UNKNOWN').upper() for r in (self.get_pipeline_summary(trading=trading).get('symbol_overview') or [])[:10]]
        no_news_symbols = [s for s in tracked_symbols if s not in news_by_symbol]
        if no_news_symbols:
            alerts.append({
                "severity": "warning",
                "code": "no_news_for_tracked_symbols",
                "title": "Tracked symbols without news",
                "message": f"No news items found for {len(no_news_symbols)} tracked symbol(s): {', '.join(no_news_symbols[:5])}",
                "action_hint": "Check news collection coverage for active symbols",
                "updated_at": now_iso(),
            })

        stale_news_symbols = []
        now_dt = datetime.now().astimezone()
        for sym, row in news_by_symbol.items():
            headline = row.get('latest_headline_ja')
            items = [i for i in (news.get('items') or []) if str(i.get('symbol') or '').upper() == sym]
            if not items:
                continue
            latest = self._parse_iso_datetime(items[0].get('published_at'))
            if latest and (now_dt - latest).total_seconds() > 86400:
                stale_news_symbols.append(sym)
        if stale_news_symbols:
            alerts.append({
                "severity": "warning",
                "code": "stale_news_symbols",
                "title": "Stale news detected",
                "message": f"{len(stale_news_symbols)} symbol(s) have no fresh news in the last 24h: {', '.join(stale_news_symbols[:5])}",
                "action_hint": "Refresh news ingestion or verify external source availability",
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

    def _get_account_info(self) -> Dict[str, Any]:
        """Get account information from broker."""
        if not self._broker:
            return {
                "available": False,
                "equity": 0,
                "cash": 0,
                "buying_power": 0,
            }
        
        try:
            account = self._broker.fetch_account()
            acc_data = account.payload if hasattr(account, 'payload') else account
            
            return {
                "available": True,
                "equity": float(acc_data.get('equity', 0)),
                "cash": float(acc_data.get('cash', 0)),
                "buying_power": float(acc_data.get('buying_power', 0)),
                "portfolio_value": float(acc_data.get('portfolio_value', 0)),
                "long_market_value": float(acc_data.get('long_market_value', 0)),
            }
        except Exception as e:
            return {
                "available": False,
                "equity": 0,
                "cash": 0,
                "buying_power": 0,
                "error": str(e),
            }

    def _enrich_broker_position(self, broker_pos: dict) -> dict:
        """Enrich a broker position with calculated fields."""
        symbol = broker_pos.get('symbol', '')
        qty = int(float(broker_pos.get('qty', 0)))
        avg_entry = float(broker_pos.get('avg_entry_price', 0))
        current_price = float(broker_pos.get('current_price', 0))
        market_value = float(broker_pos.get('market_value', 0))
        unrealized_pl = float(broker_pos.get('unrealized_pl', 0))
        unrealized_plpc = float(broker_pos.get('unrealized_plpc', 0))
        
        # Calculate holding days (if created_at available)
        holding_days = None
        created_at = broker_pos.get('created_at')
        if created_at:
            try:
                from datetime import timezone as tz
                created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                now_dt = datetime.now(tz.utc)
                holding_days = (now_dt - created_dt).days
            except:
                pass
        
        return {
            'symbol': symbol,
            'qty': qty,
            'entry_price': avg_entry,
            'current_price': current_price,
            'market_value': market_value,
            'unrealized_pnl': unrealized_pl,
            'unrealized_pnl_pct': unrealized_plpc * 100,
            'holding_days': holding_days,
            'strategy_id': 'unknown',
            'source': 'broker',
        }

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
        # Count long/short positions
        # Broker positions: qty > 0 = long, qty < 0 = short
        long_count = len([p for p in positions if float(p.get("qty", 0)) > 0])
        short_count = len([p for p in positions if float(p.get("qty", 0)) < 0])
        
        return {
            "gross_exposure": gross_exposure,
            "net_exposure": gross_exposure,
            "long_count": long_count,
            "short_count": short_count,
            "largest_position_weight": largest_weight,
            "top5_concentration": top5,
            "unrealized_pnl": unrealized_pnl,
            "avg_holding_days": avg_holding_days,
        }

    def _fetch_current_prices(self, symbols: List[str | None]) -> Dict[str, float]:
        """Fetch current prices for symbols from latest raw broker data."""
        prices: Dict[str, float] = {}
        broker_raw_dir = self.project_root / "data" / "raw" / "broker"
        
        if not broker_raw_dir.exists():
            return prices
        
        for symbol in symbols:
            if not symbol:
                continue
            
            symbol_upper = str(symbol).upper()
            # Find latest broker file for symbol
            matching_files = sorted(
                broker_raw_dir.glob(f"broker_{symbol_upper.lower()}_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            if not matching_files:
                continue
            
            try:
                data = json.loads(matching_files[0].read_text(encoding="utf-8"))
                payload = data.get("payload", {})
                bars = payload.get("bars", [])
                
                if bars:
                    # Use latest bar close price
                    latest_bar = bars[-1]
                    close_price = float(latest_bar.get("c") or 0.0)
                    if close_price > 0:
                        prices[symbol_upper] = close_price
            except Exception:
                pass
        
        return prices

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

    def _load_external_news_items(self, limit: int = 50) -> List[Dict[str, Any]]:
        raw_dir = self.project_root / "data" / "raw" / "finnhub"
        if not raw_dir.exists():
            return []
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        paths = sorted(raw_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths:
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if obj.get("endpoint") != "company-news":
                continue
            payload = obj.get("payload", {})
            symbol = str(payload.get("symbol") or obj.get("request_params", {}).get("symbol") or "UNKNOWN").upper()
            grouped.setdefault(symbol, [])
            for idx, article in enumerate(payload.get("news", [])):
                headline = str(article.get("headline") or "")
                summary = str(article.get("summary") or "")
                sentiment_label, sentiment_score = self._infer_sentiment_from_text(f"{headline} {summary}")
                impact_label, impact_score = self._infer_impact_from_text(f"{headline} {summary}")
                ja_texts = self._build_ja_news_texts_from_external(symbol, headline, summary, sentiment_label, impact_label)
                source = article.get("source") or "finnhub"
                source_reliability = self._source_reliability(source)
                grouped[symbol].append({
                    "id": f"external_news_{symbol}_{idx}_{path.stem}",
                    "symbol": symbol,
                    "source": source,
                    "source_reliability": source_reliability,
                    "published_at": datetime.fromtimestamp(article.get("datetime", 0), tz=timezone.utc).isoformat() if article.get("datetime") else now_iso(),
                    "url": article.get("url"),
                    "headline": headline,
                    "headline_ja": ja_texts["headline_ja"],
                    "snippet": summary,
                    "summary_ja": ja_texts["summary_ja"],
                    "event_type": ja_texts["event_type"],
                    "related": article.get("related") or symbol,
                    "category": article.get("category") or 'company',
                    "sentiment_label": sentiment_label,
                    "sentiment_label_ja": self._translate_sentiment_label(sentiment_label),
                    "sentiment_score": sentiment_score,
                    "sentiment_confidence": 0.6,
                    "impact_label": impact_label,
                    "impact_label_ja": self._translate_impact_label(impact_label),
                    "impact_score": impact_score,
                    "relevance_score": 0.7,
                    "influence_score": 0.3,
                    "used_in_decision": False,
                    "is_tracked_symbol": False,
                    "decision_refs": [],
                    "strategy_refs": [],
                    "rationale": [summary] if summary else [],
                    "rationale_ja": ja_texts["rationale_ja"],
                })
        # per-symbol cap before global balancing to avoid dominance by a few symbols
        capped: List[Dict[str, Any]] = []
        per_symbol_cap = max(3, limit // max(1, len(grouped))) if grouped else limit
        for symbol, rows in grouped.items():
            rows.sort(key=lambda x: str(x.get('published_at') or ''), reverse=True)
            capped.extend(rows[:per_symbol_cap])
        capped.sort(key=lambda x: str(x.get('published_at') or ''), reverse=True)
        return capped[: max(limit * 2, 100)]

    def _link_news_to_decisions(self, news_items: List[Dict[str, Any]], decision_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        linked: List[Dict[str, Any]] = []
        general_market_terms = ['stock market today', 'market rebound', 'oil disruption', 'market stumbles', 'dow futures', 's&p 500', 'nasdaq']
        ticker_aliases = {
            'MRVL': ['marvell'], 'CIEN': ['ciena'], 'DELL': ['dell'], 'RBRK': ['rubrik'], 'PLTR': ['palantir'],
            'AVGO': ['broadcom'], 'GOOGL': ['alphabet', 'google'], 'META': ['meta'], 'MSFT': ['microsoft'], 'AAPL': ['apple']
        }
        for item in news_items:
            symbol = str(item.get("symbol") or "UNKNOWN").upper()
            published = self._parse_iso_datetime(item.get("published_at"))
            article_text = f"{item.get('headline','')} {item.get('snippet','')}".lower()
            is_general_market = any(term in article_text for term in general_market_terms)
            related_field = str(item.get('related') or '').upper()
            aliases = ticker_aliases.get(symbol, [])
            contains_own_name = any(alias in article_text for alias in aliases)
            related_matches = related_field == symbol if related_field else False
            own_mention_bonus = 0.2 if related_matches else 0.12 if contains_own_name else 0.0
            other_ticker_penalty = 0.0
            first_words = article_text[:120]
            for ticker, names in ticker_aliases.items():
                if ticker == symbol:
                    continue
                if ticker.lower() in first_words or any(name in first_words for name in names):
                    other_ticker_penalty = max(other_ticker_penalty, 0.35)
                elif ticker.lower() in article_text or any(name in article_text for name in names):
                    other_ticker_penalty = max(other_ticker_penalty, 0.25)
            scored_matches = []
            for dec in decision_items:
                if str(dec.get("symbol") or "UNKNOWN").upper() != symbol:
                    continue
                dec_time = self._parse_iso_datetime(dec.get("published_at"))
                if published and dec_time:
                    seconds = abs((dec_time - published).total_seconds())
                    if seconds > 86400 * 2:
                        continue
                    time_score = max(0.0, 1.0 - (seconds / (86400 * 2)))
                else:
                    time_score = 0.3
                note_text = ' '.join(dec.get('rationale') or dec.get('rationale_ja') or []) if isinstance(dec, dict) else ''
                keyword_overlap = 0.0
                keywords = ['partnership', 'guidance', 'earnings', 'probe', 'lawsuit', 'growth', 'momentum', 'breakout']
                for kw in keywords:
                    if kw in article_text and kw in note_text.lower():
                        keyword_overlap += 0.15
                headline_bonus = 0.0
                headline_patterns = ['why ', 'stock is surging', 'gains on', 'stock pops', 'adds $', 'partnership', 'deal', 'guidance', 'earnings']
                if any(p in article_text for p in headline_patterns):
                    headline_bonus += 0.12
                source_bonus = float(item.get('source_reliability') or 0.6) * 0.15
                related_bonus = own_mention_bonus
                general_penalty = 0.3 if is_general_market else 0.0
                score = round(min(1.0, max(0.0, 0.1 + time_score * 0.38 + keyword_overlap + headline_bonus + source_bonus + related_bonus - general_penalty - other_ticker_penalty)), 2)
                scored_matches.append((score, dec))
            scored_matches.sort(key=lambda x: x[0], reverse=True)
            top_matches = [m for m in scored_matches[:2] if m[0] >= 0.6]
            refs = []
            strategies = set()
            best_influence = float(item.get("influence_score") or 0.0)
            for score, dec in top_matches:
                refs.extend(dec.get("decision_refs") or [])
                for s in dec.get("strategy_refs") or []:
                    strategies.add(str(s))
                best_influence = max(best_influence, score)
            enriched = dict(item)
            enriched["decision_refs"] = sorted(set(refs))
            enriched["strategy_refs"] = sorted(strategies)
            enriched["used_in_decision"] = len(enriched["decision_refs"]) > 0
            enriched["influence_score"] = round(best_influence, 2 if enriched["used_in_decision"] else 2)
            if enriched["used_in_decision"]:
                base_rationale = enriched.get("rationale_ja") or []
                extra = f"{symbol} の意思決定に時間的・内容的に近い参考ニュースです。"
                enriched["rationale_ja"] = base_rationale + ([extra] if extra not in base_rationale else [])
            linked.append(enriched)
        return linked

    def _source_reliability(self, source: str) -> float:
        s = str(source or '').lower()
        if s in {'reuters', 'bloomberg', 'associated press', 'ap', 'wsj', 'wall street journal'}:
            return 0.95
        if s in {'yahoo', 'seekingalpha', 'marketwatch'}:
            return 0.75
        if s in {'finnhub', 'synthetic'}:
            return 0.4
        return 0.6

    def _build_ja_news_texts_from_external(self, symbol: str, headline: str, summary: str, sentiment_label: str, impact_label: str) -> Dict[str, Any]:
        text = f"{headline} {summary}".lower()
        if 'earnings' in text or 'guidance' in text:
            headline_ja = f"{symbol} に決算・見通し関連のニュース"
            summary_ja = f"{symbol} に関する決算または業績見通し関連の報道です。業績期待や短期的な値動きに影響する可能性があります。"
            rationale_ja = ["決算・見通し関連の報道は短期的な株価変動要因になりやすいため。"]
            event_type = 'earnings'
        elif 'probe' in text or 'lawsuit' in text or 'regulation' in text:
            headline_ja = f"{symbol} に規制・法務関連のニュース"
            summary_ja = f"{symbol} に関する規制・調査・訴訟関連の報道です。ネガティブサプライズやリスク再評価につながる可能性があります。"
            rationale_ja = ["規制・訴訟関連の報道はボラティリティ上昇やセンチメント悪化につながりやすいため。"]
            event_type = 'regulation'
        elif 'momentum' in text or 'surge' in text or 'strong' in text or sentiment_label == 'positive':
            headline_ja = f"{symbol} に追い風となるニュース"
            summary_ja = f"{symbol} に対してポジティブに受け取られやすい報道です。短期的なモメンタム継続の参考材料になります。"
            rationale_ja = ["ポジティブ材料として短期の上昇継続シナリオを補強するため。"]
            event_type = 'momentum'
        elif sentiment_label == 'negative':
            headline_ja = f"{symbol} に逆風となるニュース"
            summary_ja = f"{symbol} に対してネガティブに受け取られやすい報道です。ポジション縮小や慎重判断の材料になります。"
            rationale_ja = ["ネガティブ材料としてリスク回避や売却判断を支えるため。"]
            event_type = 'event'
        else:
            headline_ja = f"{symbol} に関する市場ニュース"
            summary_ja = f"{symbol} に関する一般的な市場ニュースです。方向感は中立ですが、監視対象として参考になります。"
            rationale_ja = ["判断材料の補助情報として参照するため。"]
            event_type = 'event'
        return {
            'headline_ja': headline_ja,
            'summary_ja': summary_ja,
            'rationale_ja': rationale_ja,
            'event_type': event_type,
        }

    def _infer_sentiment_from_text(self, text: str) -> tuple[str, float]:
        t = (text or '').lower()
        pos_words = ['beats', 'raise', 'raised', 'growth', 'upgrade', 'strong', 'gain', 'surge', 'positive', 'partnership', 'adds $', 'jumps', 'win', 'outperform']
        neg_words = ['miss', 'probe', 'lawsuit', 'drop', 'decline', 'cut', 'warning', 'negative', 'downgrade', 'investigation', 'fraud', 'weakness', 'slump']
        pos = sum(1 for w in pos_words if w in t)
        neg = sum(1 for w in neg_words if w in t)
        if pos > neg:
            return 'positive', round(min(1.0, 0.25 + pos * 0.12), 2)
        if neg > pos:
            return 'negative', round(-min(1.0, 0.25 + neg * 0.12), 2)
        return 'neutral', 0.0

    def _infer_impact_from_text(self, text: str) -> tuple[str, float]:
        t = (text or '').lower()
        critical_words = ['acquisition', 'merger', 'bankruptcy', 'fraud', 'probe', 'lawsuit']
        high_words = ['earnings', 'guidance', 'partnership', 'regulation', 'investigation', '$5b', 'market cap']
        critical_hits = sum(1 for w in critical_words if w in t)
        high_hits = sum(1 for w in high_words if w in t)
        score = round(min(1.0, 0.2 + critical_hits * 0.35 + high_hits * 0.18), 2)
        if score >= 0.85:
            return 'critical', score
        if score >= 0.6:
            return 'high', score
        if score >= 0.3:
            return 'medium', score
        return 'low', score

    def _translate_sentiment_label(self, label: str) -> str:
        mapping = {"positive": "ポジティブ", "negative": "ネガティブ", "neutral": "中立"}
        return mapping.get(str(label or "neutral").lower(), "中立")

    def _translate_impact_label(self, label: str) -> str:
        mapping = {"low": "低", "medium": "中", "high": "高", "critical": "重大"}
        return mapping.get(str(label or "low").lower(), "低")

    def _classify_news_from_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        action = str(decision.get("action") or "hold").lower()
        confidence = float(decision.get("confidence") or 0.0)
        signal_strength = float(decision.get("signal_strength") or 0.0)
        if action == "buy":
            sentiment_label = "positive"
            sentiment_score = round(max(0.25, signal_strength), 2)
        elif action == "sell":
            sentiment_label = "negative"
            sentiment_score = round(-max(0.25, signal_strength), 2)
        else:
            sentiment_label = "neutral"
            sentiment_score = 0.0
        impact_score = round(min(1.0, 0.4 + confidence * 0.4 + signal_strength * 0.2), 2)
        if impact_score >= 0.85:
            impact_label = "critical"
        elif impact_score >= 0.6:
            impact_label = "high"
        elif impact_score >= 0.3:
            impact_label = "medium"
        else:
            impact_label = "low"
        return {
            "sentiment_label": sentiment_label,
            "sentiment_score": sentiment_score,
            "sentiment_confidence": confidence,
            "impact_label": impact_label,
            "impact_score": impact_score,
            "relevance_score": round(min(1.0, 0.5 + signal_strength * 0.5), 2),
            "influence_score": round(min(1.0, 0.4 + confidence * 0.3 + signal_strength * 0.3), 2),
        }

    def _build_ja_news_texts_from_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        symbol = str(decision.get("symbol") or "UNKNOWN").upper()
        action = str(decision.get("action") or "hold").lower()
        strategy = str(decision.get("strategy_id") or "unknown")
        confidence = float(decision.get("confidence") or 0.0)
        evidence = decision.get("evidence") or {}
        notes = evidence.get("notes") or []
        note = str(notes[0]) if notes else "判断材料が検出されました。"
        event_type = "momentum" if strategy == "breakout_momentum_v1" else "event"

        if "stop loss triggered" in note.lower():
            headline_ja = f"{symbol} は損切り条件に達し、売り判断"
            summary_ja = f"{symbol} は損失拡大を防ぐため、損切り条件に基づいて売却候補と判定されました。信頼度は {confidence:.2f} です。"
            rationale_ja = [f"損切り条件が発動し、下落継続リスクを抑える必要があるため。"]
            event_type = "event"
        elif "bullish momentum" in note.lower() or "breakout" in note.lower():
            headline_ja = f"{symbol} は上昇モメンタムが強く、買い判断"
            summary_ja = f"{symbol} は強い上昇モメンタムが確認され、ブレイクアウト継続を狙う買い候補と判定されました。信頼度は {confidence:.2f} です。"
            rationale_ja = [f"価格モメンタムが強く、短期的な上昇継続シナリオを支持するため。"]
            event_type = "momentum"
        elif action == "buy":
            headline_ja = f"{symbol} にポジティブ材料、買い判断"
            summary_ja = f"{symbol} は戦略 {strategy} により買い候補と判定されました。信頼度は {confidence:.2f} です。"
            rationale_ja = [f"判断材料が買いシナリオを支持したため。"]
        elif action == "sell":
            headline_ja = f"{symbol} にネガティブ材料、売り判断"
            summary_ja = f"{symbol} は戦略 {strategy} により売り候補と判定されました。信頼度は {confidence:.2f} です。"
            rationale_ja = [f"判断材料が売り・縮小シナリオを支持したため。"]
        else:
            headline_ja = f"{symbol} の判断材料を更新"
            summary_ja = f"{symbol} の最新判断材料を評価しました。信頼度は {confidence:.2f} です。"
            rationale_ja = [f"判断材料の再評価を実施しました。"]

        return {
            "headline_ja": headline_ja,
            "summary_ja": summary_ja,
            "rationale_ja": rationale_ja,
            "event_type": event_type,
        }

    def _build_news_items_from_decisions(self, limit: int = 50) -> List[Dict[str, Any]]:
        decisions = self._load_recent_decisions(limit=limit)
        items: List[Dict[str, Any]] = []
        for idx, d in enumerate(decisions):
            evidence = d.get("evidence") or {}
            notes = evidence.get("notes") or []
            note = str(notes[0]) if notes else f"Decision generated for {d.get('symbol', 'UNKNOWN')}"
            classified = self._classify_news_from_decision(d)
            ja_texts = self._build_ja_news_texts_from_decision(d)
            symbol = str(d.get("symbol") or "UNKNOWN").upper()
            published_at = d.get("generated_at") or now_iso()
            action = str(d.get("action") or "hold").lower()
            event_type = ja_texts["event_type"]
            url = f"https://example.local/decisions/{d.get('decision_id')}"
            headline_ja = ja_texts["headline_ja"]
            summary_ja = ja_texts["summary_ja"]
            items.append({
                "id": f"news_decision_{idx}_{symbol}",
                "symbol": symbol,
                "source": "decision_engine",
                "published_at": published_at,
                "url": url,
                "headline": note,
                "headline_ja": headline_ja,
                "snippet": note,
                "summary_ja": summary_ja,
                "event_type": event_type,
                "sentiment_label": classified["sentiment_label"],
                "sentiment_label_ja": self._translate_sentiment_label(classified["sentiment_label"]),
                "sentiment_score": classified["sentiment_score"],
                "sentiment_confidence": classified["sentiment_confidence"],
                "impact_label": classified["impact_label"],
                "impact_label_ja": self._translate_impact_label(classified["impact_label"]),
                "impact_score": classified["impact_score"],
                "relevance_score": classified["relevance_score"],
                "influence_score": classified["influence_score"],
                "used_in_decision": True,
                "is_tracked_symbol": True,
                "decision_refs": [d.get("decision_id")],
                "strategy_refs": [d.get("strategy_id")],
                "rationale": notes[:3],
                "rationale_ja": ja_texts["rationale_ja"],
            })
        return items

    def _summarize_news(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "total_24h": len(items),
            "positive": sum(1 for i in items if i.get("sentiment_label") == "positive"),
            "negative": sum(1 for i in items if i.get("sentiment_label") == "negative"),
            "neutral": sum(1 for i in items if i.get("sentiment_label") == "neutral"),
            "high_impact": sum(1 for i in items if i.get("impact_label") == "high"),
            "critical_impact": sum(1 for i in items if i.get("impact_label") == "critical"),
            "decision_referenced": sum(1 for i in items if i.get("used_in_decision")),
            "symbols_covered": len({i.get("symbol") for i in items if i.get("symbol")}),
        }

    def _group_news_by_symbol(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in items:
            symbol = item.get("symbol") or "UNKNOWN"
            row = grouped.setdefault(symbol, {
                "symbol": symbol,
                "news_count": 0,
                "positive": 0,
                "negative": 0,
                "neutral": 0,
                "avg_sentiment": 0.0,
                "avg_impact": 0.0,
                "decision_referenced": 0,
            })
            row["news_count"] += 1
            row[item.get("sentiment_label") or "neutral"] += 1
            row["avg_sentiment"] += float(item.get("sentiment_score") or 0.0)
            row["avg_impact"] += float(item.get("impact_score") or 0.0)
            row["decision_referenced"] += 1 if item.get("used_in_decision") else 0
        latest_by_symbol: Dict[str, str] = {}
        for item in items:
            symbol = item.get("symbol") or "UNKNOWN"
            if symbol not in latest_by_symbol:
                latest_by_symbol[symbol] = item.get("headline_ja") or item.get("headline") or ""
        for row in grouped.values():
            count = max(1, row["news_count"])
            row["avg_sentiment"] = round(row["avg_sentiment"] / count, 2)
            row["avg_impact"] = round(row["avg_impact"] / count, 2)
            row["latest_headline_ja"] = latest_by_symbol.get(row["symbol"], "")
            row["is_tracked_symbol"] = False
        symbol_overview = self.get_pipeline_summary().get("symbol_overview", [])
        symbol_map = {str(r.get("symbol") or "UNKNOWN").upper(): r for r in symbol_overview}
        rows = sorted(grouped.values(), key=lambda x: x.get("news_count", 0), reverse=True)
        for row in rows:
            sym = str(row.get("symbol") or "UNKNOWN").upper()
            linked = symbol_map.get(sym, {})
            row["submitted"] = linked.get("submitted", 0)
            row["open_position"] = linked.get("open_position", False)
            row["conversion_rate"] = linked.get("conversion_rate", 0.0)
            row["is_tracked_symbol"] = bool(linked)
        return rows

    def _select_balanced_news_items(self, items: List[Dict[str, Any]], limit: int = 50) -> List[Dict[str, Any]]:
        if len(items) <= limit:
            return items
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            symbol = str(item.get('symbol') or 'UNKNOWN').upper()
            grouped.setdefault(symbol, []).append(item)
        selected: List[Dict[str, Any]] = []
        used_ids = set()
        # First pass: at least one item per symbol, sorted by influence then impact then time
        for symbol, rows in grouped.items():
            rows_sorted = sorted(rows, key=lambda x: (float(x.get('influence_score') or 0.0), float(x.get('impact_score') or 0.0), str(x.get('published_at') or '')), reverse=True)
            top = rows_sorted[0]
            selected.append(top)
            used_ids.add(top.get('id'))
            if len(selected) >= limit:
                return selected[:limit]
        # Second pass: fill remaining slots globally by influence/impact/freshness
        remaining = [i for i in items if i.get('id') not in used_ids]
        remaining.sort(key=lambda x: (float(x.get('influence_score') or 0.0), float(x.get('impact_score') or 0.0), str(x.get('published_at') or '')), reverse=True)
        selected.extend(remaining[:max(0, limit - len(selected))])
        return selected[:limit]

    def _count_items_by_symbol(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        counts: Dict[str, int] = {}
        for item in items:
            sym = str(item.get('symbol') or 'UNKNOWN').upper()
            counts[sym] = counts.get(sym, 0) + 1
        return [{'symbol': k, 'count': v} for k, v in sorted(counts.items(), key=lambda item: item[1], reverse=True)]

    def _group_news_by_source(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in items:
            source = item.get("source") or "unknown"
            row = grouped.setdefault(source, {"source": source, "count": 0, "positive": 0, "negative": 0, "neutral": 0})
            row["count"] += 1
            row[item.get("sentiment_label") or "neutral"] += 1
        return sorted(grouped.values(), key=lambda x: x.get("count", 0), reverse=True)

    def _group_news_by_event_type(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in items:
            event_type = item.get("event_type") or "event"
            row = grouped.setdefault(event_type, {"event_type": event_type, "count": 0, "positive": 0, "negative": 0, "neutral": 0})
            row["count"] += 1
            row[item.get("sentiment_label") or "neutral"] += 1
        return sorted(grouped.values(), key=lambda x: x.get("count", 0), reverse=True)

    def _build_news_timeline(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        timeline: Dict[str, Dict[str, Any]] = {}
        for item in items:
            ts = str(item.get("published_at") or now_iso())[:13] + ":00:00"
            row = timeline.setdefault(ts, {"ts": ts, "count": 0, "positive": 0, "negative": 0, "neutral": 0})
            row["count"] += 1
            row[item.get("sentiment_label") or "neutral"] += 1
        return sorted(timeline.values(), key=lambda x: x["ts"])

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

    # ── Phase 1 Enhancement APIs ──────────────────────────────────────────────

    def get_strategy_analysis(self) -> Dict[str, Any]:
        """Get strategy performance analysis.
        
        Returns detailed metrics by strategy including win rates, Sharpe ratios,
        profit factors, and symbol-level breakdowns.
        """
        if not self._tracker:
            return {"available": False, "error": "PnLTracker not available"}
        
        try:
            # Import analyzer
            from stock_swing.analysis.strategy_analyzer import StrategyAnalyzer
            
            # Get trades
            self._tracker.state = self._tracker._load_state()
            trades = self._tracker.state.trades
            
            # Analyze
            analyzer = StrategyAnalyzer()
            by_strategy = analyzer.analyze_by_strategy(trades)
            top_performers = analyzer.get_top_performers(by='sharpe', n=5)
            comparison_data = analyzer.get_comparison_data()
            
            # Get symbol breakdowns for each strategy
            symbol_breakdowns = {}
            for strategy_id in by_strategy.keys():
                symbol_breakdowns[strategy_id] = analyzer.get_symbol_breakdown(
                    strategy_id, trades
                )
            
            return {
                "available": True,
                "time": now_iso(),
                "by_strategy": by_strategy,
                "top_performers": top_performers,
                "comparison_data": comparison_data,
                "symbol_breakdowns": symbol_breakdowns,
            }
        except Exception as e:
            return {"available": False, "error": str(e)}
    
    def get_live_metrics(self) -> Dict[str, Any]:
        """Get real-time risk and portfolio metrics.
        
        Returns Kelly Criterion, risk score, drawdown, portfolio heat,
        and other live risk metrics.
        """
        try:
            # Import calculator
            from stock_swing.analysis.risk_calculator import RiskCalculator
            
            # Get current data
            trading = self.get_trading()
            positions = self.get_positions(trading=trading)
            
            if not trading.get('available') or not positions.get('available'):
                return {"available": False, "error": "Required data not available"}
            
            calc = RiskCalculator()
            
            # Extract data
            summary = trading.get('summary', {})
            pos_summary = positions.get('summary', {})
            snapshots = trading.get('daily_snapshots', [])
            trades = trading.get('closed_trades', [])
            current_positions = positions.get('current', [])
            
            # Equity curve
            equity_curve = [s.get('equity', 0) for s in snapshots if s.get('equity')]
            
            # Current metrics
            current_equity = equity_curve[-1] if equity_curve else 100000.0
            current_dd = calc.calculate_current_drawdown(equity_curve, percentage=True)
            max_dd = calc.calculate_max_drawdown(equity_curve, percentage=True)
            
            # Kelly Criterion
            win_rate = summary.get('win_rate', 0)
            
            if trades and win_rate > 0:
                wins = [t.get('pnl', 0) for t in trades if t.get('pnl', 0) > 0]
                losses = [abs(t.get('pnl', 0)) for t in trades if t.get('pnl', 0) < 0]
                avg_win = sum(wins) / len(wins) if wins else 0
                avg_loss = sum(losses) / len(losses) if losses else 0
                kelly = calc.calculate_kelly_criterion(win_rate, avg_win, avg_loss)
            else:
                kelly = 0.0
            
            # Portfolio heat
            portfolio_heat = calc.calculate_portfolio_heat(current_positions, current_equity)
            
            # Open P&L
            open_pnl = pos_summary.get('unrealized_pnl', 0)
            
            # Risk score
            risk_score = calc.calculate_risk_score(
                current_positions,
                current_equity,
                current_dd,
                portfolio_heat,
                open_pnl
            )
            
            # Days since last trade
            days_since = calc.days_since_last_trade(trades)
            
            # Risk level and emoji
            risk_level = calc.get_risk_level(risk_score)
            risk_emoji = calc.get_risk_emoji(risk_score)
            
            return {
                "available": True,
                "time": now_iso(),
                "current_drawdown_pct": current_dd,
                "max_drawdown_pct": max_dd,
                "kelly_suggested_size_pct": kelly * 100,  # Convert to percentage
                "portfolio_heat_pct": portfolio_heat,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "risk_emoji": risk_emoji,
                "days_since_last_trade": days_since,
                "open_pnl": open_pnl,
                "current_equity": current_equity,
                "open_positions_count": len(current_positions),
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    def _enrich_strategy_overview(self, by_strategy: Dict[str, Dict], submission_events: list) -> list:
        """Enrich strategy overview with submissions, PnL, and position data."""
        # Get submissions by strategy
        submissions_by_strategy = {}
        for evt in submission_events:
            details = self._parse_submission_details(evt.get("details", ""))
            strategy = details.get("strategy_id", "unknown")
            submissions_by_strategy[strategy] = submissions_by_strategy.get(strategy, 0) + 1
        
        # Get PnL data from tracker
        try:
            from stock_swing.tracking.pnl_tracker import PnLTracker
            tracker = PnLTracker(self.project_root)
            closed_trades = [t for t in tracker.state.trades if t.get("status") == "closed"]
            open_trades = [t for t in tracker.state.trades if t.get("status") == "open"]
            
            # Aggregate by strategy
            pnl_by_strategy = {}
            closes_by_strategy = {}
            for trade in closed_trades:
                strategy = trade.get("strategy_id", "unknown")
                pnl_by_strategy[strategy] = pnl_by_strategy.get(strategy, 0.0) + trade.get("pnl", 0.0)
                closes_by_strategy[strategy] = closes_by_strategy.get(strategy, 0) + 1
            
            open_by_strategy = {}
            for trade in open_trades:
                strategy = trade.get("strategy_id", "unknown")
                open_by_strategy[strategy] = open_by_strategy.get(strategy, 0) + 1
        except Exception:
            pnl_by_strategy = {}
            closes_by_strategy = {}
            open_by_strategy = {}
        
        # Enrich each strategy
        enriched = []
        for strategy_id, stats in by_strategy.items():
            stats["submissions"] = submissions_by_strategy.get(strategy_id, 0)
            stats["closes"] = closes_by_strategy.get(strategy_id, 0)
            stats["realized_pnl"] = round(pnl_by_strategy.get(strategy_id, 0.0), 2)
            stats["open_positions"] = open_by_strategy.get(strategy_id, 0)
            stats["rejection_rate"] = round((stats.get("reject", 0) / stats.get("decisions", 1)) * 100, 1)
            stats["conversion_rate"] = round((stats["submissions"] / stats.get("decisions", 1)) * 100, 1)
            enriched.append(stats)
        
        return sorted(enriched, key=lambda x: x.get("decisions", 0), reverse=True)[:10]

    def get_symbol_detail(self, symbol: str) -> Dict[str, Any]:
        """Get detailed information for a specific symbol."""
        symbol = symbol.upper()
        
        # Latest decisions
        decisions_dir = self.project_root / "data" / "decisions"
        decisions = []
        for f in sorted(decisions_dir.glob(f"decision_{symbol}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
            try:
                decisions.append(json.loads(f.read_text()))
            except:
                pass
        
        # Submissions
        audit_dir = self.project_root / "data" / "audits"
        submissions = []
        for f in sorted(audit_dir.glob("paper_demo_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
            for line in f.read_text(encoding='utf-8').splitlines():
                if f'| submission |' in line and symbol in line:
                    submissions.append(line)
                if len(submissions) >= 10:
                    break
        
        # Open/closed trades from PnL tracker
        try:
            from stock_swing.tracking.pnl_tracker import PnLTracker
            tracker = PnLTracker(self.project_root)
            open_trades = [t for t in tracker.state.trades if t.get("symbol") == symbol and t.get("status") == "open"]
            closed_trades = [t for t in tracker.state.trades if t.get("symbol") == symbol and t.get("status") == "closed"]
        except:
            open_trades = []
            closed_trades = []
        
        # Current position
        try:
            positions = self.get_positions()
            current_position = next((p for p in positions.get('positions', []) if p.get('symbol') == symbol), None)
        except:
            current_position = None
        
        return {
            "symbol": symbol,
            "latest_decisions": decisions[:10],
            "submissions": submissions,
            "open_trades": open_trades,
            "closed_trades": closed_trades[:20],
            "current_position": current_position,
            "total_decisions": len(decisions),
            "total_closed_trades": len(closed_trades),
            "total_realized_pnl": sum(t.get("pnl", 0) for t in closed_trades),
        }

    def get_daily_conversion_rate(self, date: str = None) -> Dict[str, Any]:
        """Get conversion rate for a specific date.
        
        Args:
            date: Date in YYYY-MM-DD format. Defaults to today.
        
        Returns:
            Dict with decisions, submissions, and conversion_rate for the specified date.
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        # Get today's audit log
        audit_file = self.project_root / "data" / "audits" / f"paper_demo_{date.replace('-', '')}.log"
        
        if not audit_file.exists():
            return {
                "date": date,
                "decisions": 0,
                "submissions": 0,
                "conversion_rate": 0.0,
                "error": f"No audit log found for {date}"
            }
        
        # Count decisions and submissions
        decisions = 0
        submissions = 0
        
        with open(audit_file, 'r') as f:
            for line in f:
                if '| decision |' in line and '| generated |' in line:
                    decisions += 1
                elif '| submission |' in line and '| submitted |' in line:
                    submissions += 1
        
        conversion_rate = (submissions / decisions * 100) if decisions > 0 else 0.0
        
        return {
            "date": date,
            "decisions": decisions,
            "submissions": submissions,
            "conversion_rate": round(conversion_rate, 1),
        }
