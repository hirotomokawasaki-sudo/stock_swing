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
            self._alerts(d),
            self._portfolio(d),
            self._price_integrity(d),
            self._decision_funnel(d),
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

    def _portfolio(self, d: dict) -> str:
        p = d.get("portfolio", {})
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
        deny_reasons = f.get("deny_reasons", {})
        if deny_reasons:
            lines.append("  deny_reasons:")
            for reason, count in sorted(deny_reasons.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"    {reason}: {count}")
        return "\n".join(lines)

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

    def _missing_metrics(self, d: dict) -> str:
        missing = d.get("missing_metrics", [])
        if not missing:
            return ""
        return "MISSING METRICS\n" + _SEP + "\n  " + ", ".join(missing)
