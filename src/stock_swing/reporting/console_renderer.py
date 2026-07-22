"""Plain text renderer for ConsoleSummary (C1)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stock_swing.reporting.console_summary import ConsoleSummary

_SEP = "─" * 56


def _fmt(value: Any, default: str = "unknown") -> str:
    if value is None:
        return default
    return str(value)


def _fmt_pct(value: Any, decimals: int = 1) -> str:
    if value is None:
        return "unknown"
    return f"{float(value):.{decimals}f}%"


def _fmt_ms(value: Any) -> str:
    if value is None:
        return "unknown"
    return f"{float(value):.0f}ms"


class ConsoleRenderer:
    def render(self, summary: "ConsoleSummary") -> str:
        d = summary.to_dict()
        sections = [
            self._run_health(d),
            self._safety_gate(d),
            self._alerts(d),
            self._portfolio(d),
            self._exit_attribution(d),
            self._price_integrity(d),
            self._decision_funnel(d),
            self._broker_tracker_diff(d),
            self._ledger_quality(d),
            self._equity_bridge(d),
            self._api_ai(d),
            self._missing_metrics(d),
        ]
        return "\n\n".join(s for s in sections if s)

    # ------------------------------------------------------------------ #

    def _run_health(self, d: dict) -> str:
        run = d.get("run", {})
        health = d.get("health", {})
        status = run.get("status", "OK")
        icon = {"OK": "✅", "DEGRADED": "⚠️ ", "HALTED": "🚨"}.get(status, "❓")
        lines = [
            f"{icon} RUN HEALTH  {status}",
            _SEP,
            f"  run_id    = {run.get('run_id', 'unknown')}",
            f"  exp_id    = {run.get('experiment_id', 'unknown')}",
            f"  guardrail = {run.get('guardrail_status', 'unknown')}",
        ]
        dur = run.get("duration_seconds")
        if dur is not None:
            lines.append(f"  duration  = {dur:.1f}s")
        lines.append(
            f"  critical={health.get('critical_count', 0)}  "
            f"warning={health.get('warning_count', 0)}  "
            f"stale_price={health.get('stale_price_count', 0)}  "
            f"api_errors={health.get('api_error_count', 0)}"
        )
        return "\n".join(lines)

    def _alerts(self, d: dict) -> str:
        alerts = d.get("alerts", [])
        if not alerts:
            return ""
        # Sort: critical -> warning -> info
        order = {"critical": 0, "warning": 1, "info": 2}
        sorted_alerts = sorted(alerts, key=lambda a: order.get(a.get("severity", "info"), 9))
        lines = ["ALERTS", _SEP]
        for a in sorted_alerts:
            sev = a.get("severity", "info").upper()
            code = a.get("code", "")
            msg = a.get("message", "")
            sym = a.get("symbol")
            sym_str = f" [{sym}]" if sym else ""
            lines.append(f"  [{sev}] {code}{sym_str}: {msg}")
        return "\n".join(lines)

    def _safety_gate(self, d: dict) -> str:
        """R0-v2-A: Safety Gate banner — ledger gate status + circuit breaker.

        When ledger_gate_status is INVALID:
        - Shows NO-GO for live-ready.
        - Signals downstream renderers (_portfolio, _exit_attribution) to suppress PF/WR.
        """
        health = d.get("health", {})
        ledger_status = health.get("ledger_gate_status", "UNKNOWN")
        cb_status = health.get("guardrail_status", "unknown")

        # Ledger gate icon + detail
        if ledger_status == "VALID":
            ledger_icon = "✅"
            live_ready_str = "🟡 PENDING (07-31 Go/No-Go 未実施)"
        elif ledger_status == "INVALID":
            ledger_icon = "🔴"
            live_ready_str = "🔴 NO-GO ← ledger=INVALID"
        else:
            ledger_icon = "❔"
            live_ready_str = "❔ UNKNOWN"

        # Circuit breaker icon
        cb_icons = {
            "ok": "✅ ok",
            "recovery_pending": "🟡 RECOVERY_PENDING ← clean scheduled run 必要",
            "degraded": "⚠️  degraded",
            "halted": "🚨 HALTED",
        }
        cb_str = cb_icons.get(cb_status, f"❔ {cb_status}")

        lines = [
            "SAFETY GATE",
            _SEP,
            f"  ledger_gate     = {ledger_icon} {ledger_status}",
            f"  circuit_breaker = {cb_str}",
            f"  live_ready      = {live_ready_str}",
        ]
        return "\n".join(lines)

    def _portfolio(self, d: dict) -> str:
        p = d.get("portfolio", {})
        ledger_invalid = d.get("health", {}).get("ledger_gate_status") == "INVALID"
        lines = [
            "PORTFOLIO",
            _SEP,
            f"  equity        = ${p.get('equity', 0):,.2f}",
            f"  realized_pnl  = ${p.get('realized_pnl', 0):+,.2f}",
            f"  unrealized_pnl= ${p.get('unrealized_pnl', 0):+,.2f}",
            f"  total_pnl     = ${p.get('total_pnl', 0):+,.2f}",
            f"  open_positions= {p.get('open_positions', 0)}",
        ]
        # R2-B: ETF vs Stock breakdown
        breakdown = p.get("asset_class_breakdown", {})
        if breakdown:
            lines.append("")
            lines.append("  ETF vs STOCK  (closed trades)")
            if ledger_invalid:
                lines.append("  PF / WR       = NOT_VALID (台帳 INVALID の間は非表示)")
            else:
                for ac in ("etf", "stock"):
                    m = breakdown.get(ac, {})
                    if not m or m.get("count", 0) == 0:
                        continue
                    pf = m.get("profit_factor")
                    pf_str = f"{pf:.3f}" if pf is not None else "∞"
                    wr = m.get("win_rate", 0)
                    net = m.get("net_pnl", 0)
                    cnt = m.get("count", 0)
                    lines.append(
                        f"  {ac.upper():<6} n={cnt:<4} PF={pf_str:<7} WR={wr*100:.1f}%  net=${net:+,.0f}"
                    )
        risk = d.get("risk", {})
        regime = risk.get("market_regime", "unknown")
        budget = risk.get("risk_budget_pct")
        lines.append(f"  regime        = {regime}")
        if budget is not None:
            lines.append(f"  open_risk_pct = {_fmt_pct(budget * 100)}")
        blocks = risk.get("cluster_blocks", [])
        if blocks:
            lines.append(f"  cluster_blocks= {', '.join(blocks[:5])}")
        return "\n".join(lines)

    def _exit_attribution(self, d: dict) -> str:
        attribution = d.get("portfolio", {}).get("exit_attribution_breakdown", {})
        by_reason = attribution.get("by_reason", {})
        if not by_reason:
            return ""

        ledger_invalid = d.get("health", {}).get("ledger_gate_status") == "INVALID"
        lines = ["EXIT ATTRIBUTION", _SEP]
        unknown_count = attribution.get("unknown_count", 0)
        if unknown_count:
            lines.append(f"  unknown/unattributed = {unknown_count}")

        if ledger_invalid:
            total = sum(m.get("count", 0) for m in by_reason.values())
            lines.append(f"  PF / WR = NOT_VALID (台帳 INVALID の間は非表示)")
            lines.append(f"  n={total} (countのみ表示)")
            for reason, m in sorted(by_reason.items())[:8]:
                cnt = m.get("count", 0)
                if cnt == 0:
                    continue
                net = float(m.get("net_pnl", 0) or 0)
                lines.append(f"  {reason:<24s} n={cnt:<4}  net=${net:+,.0f}")
        else:
            for reason, m in sorted(
                by_reason.items(),
                key=lambda item: abs(float(item[1].get("net_pnl", 0) or 0)),
                reverse=True,
            )[:8]:
                cnt = m.get("count", 0)
                if cnt == 0:
                    continue
                pf = m.get("profit_factor")
                pf_str = "∞" if pf is None else f"{float(pf):.3f}"
                wr = float(m.get("win_rate", 0) or 0) * 100
                net = float(m.get("net_pnl", 0) or 0)
                lines.append(
                    f"  {reason:<24s} n={cnt:<4} PF={pf_str:<7} WR={wr:.1f}%  net=${net:+,.0f}"
                )
        return "\n".join(lines)

    def _price_integrity(self, d: dict) -> str:
        pi = d.get("price_integrity", {})
        if not pi:
            return ""
        lines = ["PRICE INTEGRITY", _SEP]
        fresh = pi.get("fresh_price_count", _fmt(pi.get("fresh_price_count")))
        stale = pi.get("stale_price_count", 0)
        fallback = pi.get("fallback_price_count", 0)
        avg_age = pi.get("avg_price_age_seconds")
        max_age = pi.get("max_price_age_seconds")

        age_str = ""
        if avg_age is not None:
            age_str = f"  avg_age={avg_age:.0f}s  max_age={_fmt(max_age, 'unknown')}s"

        lines.append(f"  fresh={fresh}  stale={stale}  fallback={fallback}{age_str}")

        top_stale = pi.get("top_stale_symbols", [])
        if top_stale:
            lines.append(f"  top_stale: {', '.join(str(s) for s in top_stale[:5])}")
        else:
            lines.append("  top_stale: none")

        src = pi.get("price_source_breakdown") or pi.get("fallback_sources", {})
        if src:
            src_str = "  ".join(f"{k}:{v}" for k, v in sorted(src.items())[:5])
            lines.append(f"  sources: {src_str}")
        return "\n".join(lines)

    def _decision_funnel(self, d: dict) -> str:
        f = d.get("decision_funnel", {})
        lines = [
            "DECISION FUNNEL",
            _SEP,
            f"  candidates={f.get('candidates', 0)}"
            f"  buy={f.get('buy', 0)}"
            f"  sell={f.get('sell', 0)}"
            f"  deny={f.get('deny', 0)}"
            f"  blocked={f.get('blocked', 0)}",
            f"  submitted={f.get('submitted', 0)}"
            f"  rejected={f.get('rejected', 0)}",
        ]
        # R6-D: deny_reasons breakdown
        deny_reasons = f.get("deny_reasons", {})
        if deny_reasons:
            lines.append("  deny_reasons:")
            for reason, count in sorted(deny_reasons.items(), key=lambda x: -x[1])[:8]:
                bar = "▪" * min(count, 10)
                lines.append(f"    {reason:<40s} {count:>3}  {bar}")
        # RF-6b: stock-reduced mode ブロック
        lines.extend(self._decision_funnel_stock_reduced(f))
        return "\n".join(lines)

    def _broker_tracker_diff(self, d: dict) -> str:
        """R6-D: Broker vs Tracker position diff panel."""
        diff = d.get("broker_tracker_diff", {})
        if not diff:
            return ""
        lines = ["BROKER / TRACKER", _SEP]
        mismatch_count = diff.get("mismatch_count", 0)
        broker_only = diff.get("broker_only", [])
        tracker_only = diff.get("tracker_only", [])
        qty_mismatches = diff.get("qty_mismatches", [])

        status = "✅ OK" if mismatch_count == 0 else f"🚨 {mismatch_count} mismatch(es)"
        lines.append(f"  status         = {status}")
        lines.append(f"  broker_pos     = {diff.get('broker_count', '?')}")
        lines.append(f"  tracker_open   = {diff.get('tracker_count', '?')}")

        if broker_only:
            lines.append(f"  broker_only    = {', '.join(broker_only[:8])}")
        if tracker_only:
            lines.append(f"  tracker_only   = {', '.join(tracker_only[:8])}")
        if qty_mismatches:
            for m in qty_mismatches[:5]:
                lines.append(
                    f"  qty_mismatch   = {m['symbol']} broker={m['broker_qty']} tracker={m['tracker_qty']}"
                )
        return "\n".join(lines)

    def _ledger_quality(self, d: dict) -> str:
        """RF: 台帳品質パネル（clean/quarantined/attribution カバレッジ）."""
        lq = d.get("ledger_quality", {})
        if not lq:
            return ""
        clean      = lq.get("clean_closed", "?")
        quarantine = lq.get("quarantined", 0)
        coverage   = lq.get("attribution_coverage_pct")
        no_attr    = lq.get("no_exit_attribution", 0)
        total      = lq.get("total_closed", "?")

        cov_str = f"{coverage:.1f}%" if coverage is not None else "N/A"
        cov_icon = "✅" if (coverage or 0) >= 95 else ("🟡" if (coverage or 0) >= 65 else "🚨")
        q_icon = "✅" if quarantine == 0 else "⚠️"

        lines = [
            "LEDGER QUALITY",
            _SEP,
            f"  clean_closed   = {clean:>4}  (of {total} total)",
            f"  quarantined    = {quarantine:>4}  {q_icon}  ← 台帳外・分析除外",
            f"  attribution    = {cov_str:>6}  {cov_icon}  ({clean - no_attr if isinstance(clean,int) and isinstance(no_attr,int) else '?'}/{clean} 属性付き)",
        ]

        # RF-7: sector_shock_hold shadow カウント
        ssh = d.get("sector_shock_shadow", {})
        shadow_n = ssh.get("shadow_count", 0)
        if shadow_n > 0:
            lines.append(f"  sector_shock   = {shadow_n} シグナル [shadow]ログ済み")

        return "\n".join(lines)

    def _decision_funnel_stock_reduced(self, funnel: dict) -> list[str]:
        """stock-reduced ブロック情報を返す（_decision_funnel内で呼び出す）."""
        n = funnel.get("stock_reduced_blocked", 0)
        syms = funnel.get("stock_reduced_blocked_symbols", [])
        if not n:
            return []
        sym_str = ", ".join(syms[:8]) + (" ..." if len(syms) > 8 else "")
        return [
            f"  stock_reduced  = {n} ブロック: {sym_str}"
        ]

    def _api_ai(self, d: dict) -> str:
        api = d.get("api", {})
        ai = d.get("ai", {})
        if not api and not ai:
            return ""
        lines = ["API / AI COST", _SEP]

        if api:
            calls = api.get("call_count", api.get("api_call_count", 0))
            errors = api.get("error_count", api.get("api_error_count", 0))
            p50 = _fmt_ms(api.get("p50_latency_ms"))
            p95 = _fmt_ms(api.get("p95_latency_ms"))
            lines.append(f"  api_calls={calls}  errors={errors}  p50={p50}  p95={p95}")
            slowest = api.get("slowest_endpoints", [])
            if slowest:
                s = slowest[0]
                lines.append(f"  slowest={s.get('endpoint', '?')} {_fmt_ms(s.get('duration_ms'))}")

        if ai:
            ai_calls = ai.get("calls", ai.get("ai_call_count", 0))
            ai_skip = ai.get("skipped", ai.get("ai_skipped_count", 0))
            in_tok = ai.get("input_tokens", 0)
            out_tok = ai.get("output_tokens", 0)
            budget = ai.get("daily_token_budget", 300_000)
            lines.append(
                f"  ai_calls={ai_calls}  skipped={ai_skip}"
                f"  tokens={in_tok + out_tok:,}/{budget:,}"
            )
            packs = ai.get("context_pack_counts", {})
            if packs:
                pack_str = "  ".join(f"{k}:{v}" for k, v in packs.items())
                lines.append(f"  context={pack_str}")
            skip_r = ai.get("skip_reason_counts", {})
            if skip_r:
                sr_str = "  ".join(f"{k}:{v}" for k, v in skip_r.items())
                lines.append(f"  skip_reasons={sr_str}")
        return "\n".join(lines)

    def _equity_bridge(self, d: dict) -> str:
        """R0-v2-B: Broker equity bridge panel."""
        health = d.get("health", {})
        eb = health.get("equity_bridge", {})
        if not eb:
            return ""
        baseline = eb.get("baseline_equity", 0)
        realized = eb.get("tracker_realized", 0)
        unrealized = eb.get("tracker_unrealized", 0)
        computed = eb.get("tracker_computed", 0)
        broker = eb.get("broker_equity", 0)
        diff = eb.get("diff_usd", 0)
        diff_bp = eb.get("diff_bp", 0)
        q_pnl = eb.get("quarantined_pnl", 0)
        unexplained = eb.get("unexplained_diff", 0)
        within = eb.get("within_tolerance", True)
        tol = eb.get("tolerance_usd", 5000)

        tol_icon = "✅" if within else "🔴"
        lines = [
            "EQUITY BRIDGE",
            _SEP,
            f"  baseline        = ${baseline:>12,.2f}",
            f"  + realized      = ${realized:>+12,.2f}",
            f"  + unrealized    = ${unrealized:>+12,.2f}",
            f"  tracker_computed= ${computed:>12,.2f}",
            f"  broker_equity   = ${broker:>12,.2f}",
            f"  diff            = ${diff:>+12,.2f}  ({diff_bp:.0f}bp)",
            f"  quarantined_pnl = ${q_pnl:>+12,.2f}  (台帳外・ brokerは記録済み)",
            f"  unexplained     = ${unexplained:>+12,.2f}  {tol_icon} (tol=${tol:,.0f})",
        ]
        return "\n".join(lines)

    def _missing_metrics(self, d: dict) -> str:
        missing = d.get("missing_metrics", [])
        if not missing:
            return ""
        return "MISSING METRICS\n" + _SEP + "\n  " + ", ".join(missing)
