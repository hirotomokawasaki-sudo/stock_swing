"""Daily/Weekly summary generation service."""
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any
from collections import Counter
import sys
import json


class SummaryService:
    """Generate daily and weekly summaries."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        src_path = self.project_root / "src"
        if src_path.exists():
            src_str = str(src_path)
            if src_str not in sys.path:
                sys.path.insert(0, src_str)
    
    def generate_daily_summary(self) -> Dict[str, Any]:
        """Generate daily summary."""
        today = datetime.now().date().isoformat()
        
        # PnL summary
        try:
            from stock_swing.tracking.pnl_tracker import PnLTracker
            tracker = PnLTracker(self.project_root)
            
            today_closed = [t for t in tracker.state.trades 
                           if t.get("status") == "closed" and 
                           (t.get("exit_time", "")[:10] == today)]
            
            today_pnl = sum(t.get("pnl", 0) for t in today_closed)
            
            pnl_summary = {
                "today_pnl": round(today_pnl, 2),
                "today_trades": len(today_closed),
                "cumulative_pnl": tracker.state.cumulative_realized_pnl,
                "total_trades": tracker.state.total_trades,
            }
            
            # Get open positions for alerts
            open_positions = tracker.get_open_positions()
        except:
            pnl_summary = {}
            open_positions = []
        
        unresolved_mismatches = self._get_unresolved_mismatches()
        stale_positions = self._get_stale_positions(open_positions)
        strategy_health = self._get_strategy_health()
        
        # Top alerts
        alerts = self._generate_alerts(pnl_summary, open_positions, unresolved_mismatches, stale_positions, strategy_health)
        
        # Low conversion symbols
        low_conversion = self._analyze_low_conversion_symbols()
        
        return {
            "date": today,
            "alerts": alerts,
            "pnl_summary": pnl_summary,
            "unresolved_mismatches": unresolved_mismatches,
            "stale_positions": stale_positions,
            "strategy_health": strategy_health,
            "low_conversion_symbols": low_conversion,
            "generated_at": datetime.now().isoformat(),
        }
    
    def _generate_alerts(self, pnl_summary: Dict[str, Any], open_positions: list, unresolved_mismatches: Dict[str, Any] = None, stale_positions: Dict[str, Any] = None, strategy_health: Dict[str, Any] = None) -> list:
        """Generate top alerts based on current state.
        
        Severity levels:
        - critical: Immediate action required (system failure, major loss)
        - high: Attention needed soon (large losses, issues)
        - medium: Monitor closely (warnings, minor issues)
        - low: Informational (opportunities, minor notes)
        """
        alerts = []
        unresolved_mismatches = unresolved_mismatches or {}
        stale_positions = stale_positions or {}
        strategy_health = strategy_health or {}
        
        # Alert: Large daily loss (adjusted for ~$100K account)
        today_pnl = pnl_summary.get("today_pnl", 0)
        if today_pnl < -500:  # -0.5% of $100K
            severity = "critical" if today_pnl < -2000 else "high" if today_pnl < -1000 else "medium"
            alerts.append({
                "severity": severity,
                "code": "daily_loss",
                "title": f"Daily loss: ${abs(today_pnl):,.2f} ({today_pnl/100000*100:.1f}%)",
                "description": f"Today's P&L is negative (threshold: -$500)",
                "action": "Review stop loss settings and position sizing" if severity != "medium" else "Monitor closely"
            })
        
        # Alert: Winning streak (informational)
        elif today_pnl > 1000:  # +1% of $100K
            alerts.append({
                "severity": "low",
                "code": "strong_day",
                "title": f"Strong daily performance: +${today_pnl:,.2f}",
                "description": "Today's P&L is significantly positive",
                "action": "Review what worked well for future reference"
            })
        
        # Alert: Too many open positions (adjusted threshold)
        position_count = len(open_positions)
        if position_count > 20:  # Increased from 15 to reduce noise
            alerts.append({
                "severity": "medium" if position_count <= 25 else "high",
                "code": "high_position_count",
                "title": f"High position count: {position_count}",
                "description": "Too many open positions may reduce focus and increase risk",
                "action": "Consider closing underperforming positions"
            })
        
        # Alert: Unrealized loss threshold (adjusted for account size)
        total_unrealized = sum(
            (p.get('current_price', 0) - p.get('entry_price', 0)) * p.get('qty', 0)
            for p in open_positions
        )
        if total_unrealized < -1000:  # -1% of $100K
            severity = "critical" if total_unrealized < -5000 else "high" if total_unrealized < -2500 else "medium"
            alerts.append({
                "severity": severity,
                "code": "unrealized_loss",
                "title": f"Unrealized loss: ${abs(total_unrealized):,.2f} ({total_unrealized/100000*100:.1f}%)",
                "description": f"Unrealized losses are significant (threshold: -$1,000)",
                "action": "Review individual positions for stop loss triggers"
            })
        
        # Alert: Consecutive losing days
        try:
            from stock_swing.tracking.pnl_tracker import PnLTracker
            tracker = PnLTracker(self.project_root)
            recent_snapshots = sorted(tracker.state.daily_snapshots, key=lambda x: x.get('date', ''), reverse=True)[:5]
            consecutive_losses = 0
            for snap in recent_snapshots:
                daily_pnl = snap.get('daily_realized_pnl', 0)
                if daily_pnl < 0:
                    consecutive_losses += 1
                else:
                    break
            
            if consecutive_losses >= 3:
                alerts.append({
                    "severity": "high" if consecutive_losses >= 4 else "medium",
                    "code": "losing_streak",
                    "title": f"Consecutive losing days: {consecutive_losses}",
                    "description": f"{consecutive_losses} consecutive days with negative P&L",
                    "action": "Review strategy performance and market conditions"
                })
        except:
            pass

        # Alert: unresolved reconciliation mismatches
        mismatch_count = unresolved_mismatches.get("count", 0)
        if mismatch_count > 0:
            top_reason = None
            reason_counts = unresolved_mismatches.get("by_reason", [])
            if reason_counts:
                top_reason = reason_counts[0].get("reason")
            # Only alert if >= 3 mismatches (reduce noise)
            if mismatch_count >= 3:
                alerts.append({
                    "severity": "critical" if mismatch_count >= 10 else "high" if mismatch_count >= 5 else "medium",
                    "code": "unresolved_mismatches",
                    "title": f"Unresolved mismatches: {mismatch_count}",
                    "description": (
                        f"Recent reconciliation issues remain unresolved"
                        + (f" (top reason: {top_reason})" if top_reason else "")
                    ),
                    "action": "Review reconciliation status and broker truth for affected orders"
                })

        # Alert: stale positions (only if significantly old)
        stale_count = stale_positions.get("count", 0)
        if stale_count > 0:
            threshold_days = stale_positions.get("threshold_days", 10)
            # Only alert if stale positions are truly concerning
            if stale_count >= 2 or threshold_days > 15:
                alerts.append({
                    "severity": "medium" if stale_count <= 3 else "high",
                    "code": "stale_positions",
                    "title": f"Stale positions: {stale_count}",
                    "description": f"{stale_count} open position(s) held for {threshold_days}+ days",
                    "action": "Review exit criteria and long-held positions"
                })

        # Alert: unhealthy strategies (improved)
        weak_strategies = strategy_health.get("needs_attention", [])
        if weak_strategies:
            top = weak_strategies[0]
            # Check for critically low conversion
            critical_strategies = [s for s in weak_strategies if s.get("conversion_rate", 100) < 10]
            if critical_strategies:
                alerts.append({
                    "severity": "high",
                    "code": "strategy_critical",
                    "title": f"Critical strategy health: {len(critical_strategies)} strategy(ies)",
                    "description": f"{critical_strategies[0].get('strategy_id')} has <10% conversion rate",
                    "action": "Urgent review of strategy configuration and risk gates"
                })
            elif len(weak_strategies) >= 2:
                alerts.append({
                    "severity": "medium",
                    "code": "strategy_health_attention",
                    "title": f"Strategy health attention: {len(weak_strategies)}",
                    "description": f"{top.get('strategy_id')} and others have low conversion or high rejection",
                    "action": "Review strategy thresholds, risk gates, and execution eligibility"
                })
        
        # Alert: Low overall conversion rate
        try:
            all_strategies = strategy_health.get("items", [])
            if all_strategies:
                total_executable = sum(s.get("executable_decisions", 0) for s in all_strategies)
                total_submissions = sum(s.get("effective_submissions", 0) for s in all_strategies)
                overall_conversion = (total_submissions / total_executable * 100) if total_executable > 0 else 0
                
                if total_executable >= 10 and overall_conversion < 30:
                    alerts.append({
                        "severity": "high" if overall_conversion < 20 else "medium",
                        "code": "low_overall_conversion",
                        "title": f"Low overall conversion: {overall_conversion:.1f}%",
                        "description": f"Only {overall_conversion:.1f}% of executable decisions result in submissions",
                        "action": "Review risk gates, sector caps, and position size limits"
                    })
        except:
            pass
        
        # Alert: No trading activity (if significant)
        today_trades = pnl_summary.get("today_trades", 0)
        cumulative_trades = pnl_summary.get("total_trades", 0)
        if cumulative_trades >= 10 and today_trades == 0:
            # Check if market is open (heuristic: if we have positions, market was open recently)
            if position_count > 0:
                alerts.append({
                    "severity": "low",
                    "code": "no_trades_today",
                    "title": "No trades closed today",
                    "description": "No trading activity recorded today",
                    "action": "Verify market conditions and strategy signals"
                })

        # Sort by severity and return top alerts
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        alerts.sort(key=lambda a: (severity_rank.get(a.get("severity", "low"), 99), a.get("title", "")))
        
        # Return top 8 alerts (increased from 5 for better coverage)
        return alerts[:8]
    
    def _get_stale_positions(self, open_positions: list, threshold_days: int = 10) -> Dict[str, Any]:
        """Summarize open positions whose holding period exceeds the stale threshold.

        Source of truth: PnL tracker open positions. We derive holding days from entry_time
        when present, and fall back to a precomputed holding_days field if available.
        """
        try:
            stale_items = []
            now = datetime.now()
            for pos in open_positions or []:
                holding_days = pos.get("holding_days")
                if holding_days is None:
                    entry_time = pos.get("entry_time")
                    if entry_time:
                        entry_dt = self._parse_datetime(entry_time)
                        if entry_dt != datetime.min.replace(tzinfo=None):
                            holding_days = round((now - entry_dt).total_seconds() / 86400, 1)
                if holding_days is None:
                    continue
                if float(holding_days) >= threshold_days:
                    stale_items.append({
                        "symbol": pos.get("symbol"),
                        "qty": pos.get("qty"),
                        "entry_price": pos.get("entry_price"),
                        "current_price": pos.get("current_price"),
                        "holding_days": round(float(holding_days), 1),
                        "strategy_id": pos.get("strategy_id"),
                        "entry_time": pos.get("entry_time"),
                    })

            stale_items.sort(key=lambda x: x.get("holding_days", 0), reverse=True)
            return {
                "count": len(stale_items),
                "threshold_days": threshold_days,
                "items": stale_items[:20],
            }
        except Exception:
            return {"count": 0, "threshold_days": threshold_days, "items": []}

    def _get_strategy_health(self) -> Dict[str, Any]:
        """Summarize strategy-level health from decisions, submissions, and tracker trades.

        Source of truth:
        - decisions: data/decisions/decision_*.json
        - submissions: reconciliation/submission audit logs in data/audits/*.log
        - realized/open stats: PnL tracker trades
        """
        try:
            decisions_dir = self.project_root / "data" / "decisions"
            audits_dir = self.project_root / "data" / "audits"

            decision_counts: Dict[str, int] = {}
            reject_counts: Dict[str, int] = {}
            pass_counts: Dict[str, int] = {}

            if decisions_dir.exists():
                decision_files = sorted(
                    decisions_dir.glob("decision_*.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )[:200]
                for df in decision_files:
                    try:
                        decision = json.loads(df.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    strategy_id = decision.get("strategy_id") or "unknown"
                    decision_counts[strategy_id] = decision_counts.get(strategy_id, 0) + 1
                    risk_state = str(decision.get("risk_state") or "").lower()
                    if risk_state == "pass":
                        pass_counts[strategy_id] = pass_counts.get(strategy_id, 0) + 1
                    else:
                        reject_counts[strategy_id] = reject_counts.get(strategy_id, 0) + 1

            submissions_by_strategy: Dict[str, int] = {}
            if audits_dir.exists():
                audit_files = sorted(audits_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
                for path in audit_files:
                    try:
                        recent_decisions = []
                        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                            s = line.strip()
                            if not s:
                                continue

                            # Audit logs are pipe-delimited text, not JSON.
                            parts = [part.strip() for part in s.split("|")]
                            if len(parts) < 7:
                                continue
                            category = parts[2].lower()
                            action = parts[3].lower()
                            subject = parts[4]
                            details = parts[6]

                            if category == "decision" and action == "generated":
                                # Example subject: strategy:breakout_momentum_v1
                                strategy_id = subject.split(":", 1)[1].strip() if ":" in subject else (subject or "unknown")
                                detail_l = details.lower()
                                side = None
                                symbol = None
                                if detail_l.startswith("decision: buy "):
                                    side = "buy"
                                    symbol = details.split()[-1].upper()
                                elif detail_l.startswith("decision: sell "):
                                    side = "sell"
                                    symbol = details.split()[-1].upper()
                                if side and symbol:
                                    recent_decisions.append({
                                        "strategy_id": strategy_id,
                                        "side": side,
                                        "symbol": symbol,
                                    })
                                    recent_decisions = recent_decisions[-100:]
                                continue

                            if category != "submission" or action != "submitted":
                                continue

                            # Example details: Order submitted: buy 55 MRVL
                            detail_l = details.lower()
                            words = details.split()
                            if len(words) < 4:
                                continue
                            sub_side = words[2].lower() if words[0].lower() == "order" else None
                            sub_symbol = words[-1].upper()
                            if sub_side not in {"buy", "sell"}:
                                continue

                            strategy_id = "unknown"
                            for dec in reversed(recent_decisions):
                                if dec["side"] == sub_side and dec["symbol"] == sub_symbol:
                                    strategy_id = dec["strategy_id"]
                                    break
                            submissions_by_strategy[strategy_id] = submissions_by_strategy.get(strategy_id, 0) + 1
                    except Exception:
                        continue

            realized_pnl: Dict[str, float] = {}
            closes: Dict[str, int] = {}
            open_positions: Dict[str, int] = {}
            try:
                from stock_swing.tracking.pnl_tracker import PnLTracker
                tracker = PnLTracker(self.project_root)
                for trade in tracker.state.trades:
                    strategy_id = trade.get("strategy_id") or "unknown"
                    if trade.get("status") == "closed":
                        closes[strategy_id] = closes.get(strategy_id, 0) + 1
                        realized_pnl[strategy_id] = realized_pnl.get(strategy_id, 0.0) + float(trade.get("pnl") or 0.0)
                    elif trade.get("status") == "open":
                        open_positions[strategy_id] = open_positions.get(strategy_id, 0) + 1
            except Exception:
                pass

            strategy_ids = set(decision_counts) | set(submissions_by_strategy) | set(realized_pnl) | set(open_positions)
            rows = []
            needs_attention = []
            for strategy_id in sorted(strategy_ids):
                decisions = decision_counts.get(strategy_id, 0)
                submissions = submissions_by_strategy.get(strategy_id, 0)
                passes = pass_counts.get(strategy_id, 0)
                rejects = reject_counts.get(strategy_id, 0)

                # Operationally, conversion should be measured against executable/pass decisions,
                # not all generated decisions. Clamp the numerator to avoid >100% rates caused by
                # repeated/retried submissions in audit logs.
                executable_decisions = passes if passes > 0 else max(decisions - rejects, 0)
                effective_submissions = min(submissions, executable_decisions) if executable_decisions > 0 else 0
                conversion_rate = round((effective_submissions / executable_decisions * 100), 1) if executable_decisions > 0 else 0.0
                rejection_rate = round((rejects / decisions * 100), 1) if decisions > 0 else 0.0
                row = {
                    "strategy_id": strategy_id,
                    "decisions": decisions,
                    "executable_decisions": executable_decisions,
                    "submissions": submissions,
                    "effective_submissions": effective_submissions,
                    "closes": closes.get(strategy_id, 0),
                    "realized_pnl": round(realized_pnl.get(strategy_id, 0.0), 2),
                    "open_positions": open_positions.get(strategy_id, 0),
                    "conversion_rate": conversion_rate,
                    "rejection_rate": rejection_rate,
                }
                rows.append(row)
                if executable_decisions >= 5 and (conversion_rate < 20.0 or rejection_rate >= 80.0):
                    needs_attention.append(row)

            rows.sort(key=lambda x: (x.get("decisions", 0), x.get("submissions", 0)), reverse=True)
            needs_attention.sort(key=lambda x: (x.get("rejection_rate", 0), -x.get("conversion_rate", 0)), reverse=True)
            return {
                "count": len(rows),
                "items": rows[:20],
                "needs_attention": needs_attention[:10],
            }
        except Exception:
            return {"count": 0, "items": [], "needs_attention": []}

    def _get_unresolved_mismatches(self) -> Dict[str, Any]:
        """Summarize recent unresolved reconciliation mismatches from audit logs.

        Source of truth: recent reconciliation audit lines in data/audits/*.log.
        We count only records that are not clean reconciliations.
        """
        try:
            audits_dir = self.project_root / "data" / "audits"
            if not audits_dir.exists():
                return {"count": 0, "by_reason": [], "items": []}

            audit_files = sorted(audits_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
            rec_events = []
            for path in audit_files:
                try:
                    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                        s = line.strip()
                        if not s:
                            continue
                        try:
                            rec = json.loads(s)
                        except Exception:
                            continue
                        if rec.get("category") == "reconciliation":
                            rec_events.append(rec)
                except Exception:
                    continue

            unresolved = []
            reason_counter: Counter[str] = Counter()
            for evt in rec_events[-200:]:
                details = str(evt.get("details") or "")
                if "0 discrepancies" in details:
                    continue

                reason = "mismatch"
                if "qty_mismatch" in details:
                    reason = "qty_mismatch"
                elif "status_mismatch" in details:
                    reason = "status_mismatch"
                elif "order_not_found" in details:
                    reason = "order_not_found"
                elif "symbol_mismatch" in details:
                    reason = "symbol_mismatch"
                elif "side_mismatch" in details:
                    reason = "side_mismatch"
                elif "price_mismatch" in details:
                    reason = "price_mismatch"
                elif "1 discrepancies" in details:
                    reason = "single_discrepancy"

                reason_counter[reason] += 1
                unresolved.append({
                    "ts": evt.get("ts"),
                    "subject": evt.get("subject"),
                    "reason": reason,
                    "details": details,
                })

            unresolved = sorted(unresolved, key=lambda x: x.get("ts") or "", reverse=True)
            return {
                "count": len(unresolved),
                "by_reason": [
                    {"reason": reason, "count": count}
                    for reason, count in reason_counter.most_common(10)
                ],
                "items": unresolved[:20],
            }
        except Exception:
            return {"count": 0, "by_reason": [], "items": []}

    def _analyze_low_conversion_symbols(self) -> list:
        """Analyze symbols with low conversion rates."""
        try:
            # Load decisions
            decisions_dir = self.project_root / "data" / "decisions"
            if not decisions_dir.exists():
                return []
            
            # Count decisions and submissions by symbol
            from collections import defaultdict
            symbol_stats = defaultdict(lambda: {"decisions": 0, "submissions": 0})
            
            # Recent decisions (last 100)
            decision_files = sorted(
                decisions_dir.glob("decision_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )[:100]
            
            for df in decision_files:
                try:
                    decision = json.loads(df.read_text())
                    symbol = decision.get('symbol')
                    action = decision.get('action', '').lower()
                    
                    if symbol and action in ['buy', 'sell']:
                        symbol_stats[symbol]["decisions"] += 1
                        
                        # Check if submitted (risk_state == pass)
                        if decision.get('risk_state') == 'pass':
                            symbol_stats[symbol]["submissions"] += 1
                except:
                    continue
            
            # Calculate conversion rates
            low_conversion = []
            for symbol, stats in symbol_stats.items():
                if stats["decisions"] >= 3:  # At least 3 decisions
                    conv_rate = (stats["submissions"] / stats["decisions"]) * 100 if stats["decisions"] > 0 else 0
                    if conv_rate < 20:  # Less than 20% conversion
                        low_conversion.append({
                            "symbol": symbol,
                            "decisions": stats["decisions"],
                            "submissions": stats["submissions"],
                            "conversion_rate": round(conv_rate, 1)
                        })
            
            # Sort by decision count (most active first)
            low_conversion.sort(key=lambda x: x["decisions"], reverse=True)
            
            return low_conversion[:10]  # Top 10
        except:
            return []
    
    def generate_weekly_summary(self, weeks: int = 1) -> Dict[str, Any]:
        """Generate weekly summary for the last N weeks."""
        from stock_swing.tracking.pnl_tracker import PnLTracker
        
        try:
            tracker = PnLTracker(self.project_root)
            
            # Get date range
            end_date = datetime.now()
            start_date = end_date - timedelta(weeks=weeks)
            
            # Filter trades in this period
            period_trades = [
                t for t in tracker.state.trades
                if t.get("status") == "closed" and
                t.get("exit_time") and
                self._parse_datetime(t.get("exit_time")) >= start_date
            ]
            
            # Calculate metrics
            total_pnl = sum(t.get("pnl", 0) for t in period_trades)
            winning_trades = [t for t in period_trades if t.get("pnl", 0) > 0]
            losing_trades = [t for t in period_trades if t.get("pnl", 0) < 0]
            
            win_rate = (len(winning_trades) / len(period_trades) * 100) if period_trades else 0
            
            avg_win = sum(t.get("pnl", 0) for t in winning_trades) / len(winning_trades) if winning_trades else 0
            avg_loss = sum(t.get("pnl", 0) for t in losing_trades) / len(losing_trades) if losing_trades else 0
            
            profit_factor = abs(sum(t.get("pnl", 0) for t in winning_trades) / sum(t.get("pnl", 0) for t in losing_trades)) if losing_trades and sum(t.get("pnl", 0) for t in losing_trades) != 0 else 0
            
            # Best and worst trades
            best_trade = max(period_trades, key=lambda t: t.get("pnl", 0)) if period_trades else None
            worst_trade = min(period_trades, key=lambda t: t.get("pnl", 0)) if period_trades else None
            
            # Strategy breakdown
            from collections import defaultdict
            strategy_stats = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0})
            
            for trade in period_trades:
                strategy = trade.get("strategy_id", "unknown")
                strategy_stats[strategy]["trades"] += 1
                strategy_stats[strategy]["pnl"] += trade.get("pnl", 0)
                if trade.get("pnl", 0) > 0:
                    strategy_stats[strategy]["wins"] += 1
            
            # Convert to list
            strategies = [
                {
                    "strategy_id": strategy,
                    "trades": stats["trades"],
                    "pnl": round(stats["pnl"], 2),
                    "win_rate": round((stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0, 1)
                }
                for strategy, stats in strategy_stats.items()
            ]
            strategies.sort(key=lambda s: s["pnl"], reverse=True)
            
            # Symbol breakdown
            symbol_stats = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0})
            
            for trade in period_trades:
                symbol = trade.get("symbol", "unknown")
                symbol_stats[symbol]["trades"] += 1
                symbol_stats[symbol]["pnl"] += trade.get("pnl", 0)
                if trade.get("pnl", 0) > 0:
                    symbol_stats[symbol]["wins"] += 1
            
            # Top performers
            top_symbols = sorted(
                [
                    {
                        "symbol": symbol,
                        "trades": stats["trades"],
                        "pnl": round(stats["pnl"], 2),
                        "win_rate": round((stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0, 1)
                    }
                    for symbol, stats in symbol_stats.items()
                ],
                key=lambda s: s["pnl"],
                reverse=True
            )[:10]
            
            # Weekly equity progression (from snapshots)
            daily_snapshots = list(tracker.state.daily_snapshots)
            weekly_snapshots = [
                snap for snap in daily_snapshots
                if self._parse_datetime(snap.get("date")) >= start_date
            ]
            
            return {
                "period": {
                    "start": start_date.date().isoformat(),
                    "end": end_date.date().isoformat(),
                    "weeks": weeks
                },
                "summary": {
                    "total_trades": len(period_trades),
                    "winning_trades": len(winning_trades),
                    "losing_trades": len(losing_trades),
                    "win_rate": round(win_rate, 1),
                    "total_pnl": round(total_pnl, 2),
                    "avg_win": round(avg_win, 2),
                    "avg_loss": round(avg_loss, 2),
                    "profit_factor": round(profit_factor, 2)
                },
                "best_trade": {
                    "symbol": best_trade.get("symbol") if best_trade else None,
                    "pnl": round(best_trade.get("pnl", 0), 2) if best_trade else 0,
                    "exit_time": best_trade.get("exit_time") if best_trade else None
                } if best_trade else None,
                "worst_trade": {
                    "symbol": worst_trade.get("symbol") if worst_trade else None,
                    "pnl": round(worst_trade.get("pnl", 0), 2) if worst_trade else 0,
                    "exit_time": worst_trade.get("exit_time") if worst_trade else None
                } if worst_trade else None,
                "by_strategy": strategies,
                "top_symbols": top_symbols,
                "equity_progression": [
                    {
                        "date": snap.get("date"),
                        "equity": snap.get("equity"),
                        "realized_pnl": snap.get("realized_pnl")
                    }
                    for snap in weekly_snapshots[-7:]  # Last 7 days
                ],
                "generated_at": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "error": str(e),
                "period": {
                    "start": (datetime.now() - timedelta(weeks=weeks)).date().isoformat(),
                    "end": datetime.now().date().isoformat(),
                    "weeks": weeks
                }
            }
    
    def _parse_datetime(self, dt_str: Any) -> datetime:
        """Parse datetime string."""
        if not dt_str:
            return datetime.min.replace(tzinfo=None)
        if isinstance(dt_str, datetime):
            # Make naive for comparison
            return dt_str.replace(tzinfo=None) if dt_str.tzinfo else dt_str
        try:
            # Try ISO format and make naive
            dt = datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except:
            return datetime.min.replace(tzinfo=None)
