#!/usr/bin/env python3
"""07-31 Go/No-Go 自動判定スクリプト.

Required 条件7件をシステム状態から自動確認し、
判定結果をコンソール出力 + docs/go_no_go_result_YYYYMMDD.md に保存する。

使い方:
    python scripts/check_go_no_go.py [--save]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import zoneinfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))  # for `console.*` imports (promotion readiness)

JST = zoneinfo.ZoneInfo("Asia/Tokyo")
CURRENT_MODE_PATH = PROJECT_ROOT / "config" / "runtime" / "current_mode.yaml"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# AUDIT FIX (2026-08-23): latest_console_summary.json is ONLY written by
# paper_demo.py's console_summary.emit() call, which (before the companion
# paper_demo.py fix landed) was skipped entirely on any run with zero
# actionable decisions -- leaving this file, and therefore every Required
# condition below that reads from `summary`/`health`, silently frozen at
# whatever an old run last wrote. Even with that upstream fix, a future
# regression or an unrelated paper_demo crash before console_summary.emit()
# could reproduce the same failure mode. Rather than trust health.status=OK
# unconditionally, independently verify the summary itself is fresh enough
# to be trustworthy before treating anything inside it as current.
# Paper_demo cron jobs run at minimum every ~4 hours on trading days (see
# docs/console_improvement_tasks.md schedule); a summary older than this
# is either a real staleness bug or a market-closed/weekend gap. Use a
# generous 30h threshold (covers one full weekday of a delayed cron plus
# overnight) rather than trying to model exact market-hours schedules here.
_CONSOLE_SUMMARY_MAX_AGE_HOURS = 30.0

# ── economic_viability gate (2026-09-05, ユーザー承認済み) ──────────────────
# 背景: Required 条件は従来すべて「システムが壊れていないか」（鮮度・整合性・
# ガードレール）の検査であり、「そのシステムが経済的に儲かっているか」を問う
# 条件が1つも存在しなかった。ペーパー運用実績（pnl_state.json、5/12〜09-05、
# closed 357件）は実現PnL -$38,253 / PF 0.888 / 勝率47.3% であり、この状態の
# ままRequired全緑=GOと報告するのは「壊れていないが儲からないシステム」への
# GOである。economic_viability は直近コホート（デフォルト: exit_time >=
# 2026-08-14、--econ-cohort-start で上書き可）の closed トレードから
# n / PF（粗利益/|粗損失|）/ expectancy（1トレード平均PnL）を算出し、
# n>=30 かつ PF>1.0 かつ expectancy>0 を要求する。n<30 は insufficient_sample
# として fail-closed（NO-GO）。
#
# 注意（意図の明文化）: 2026-09-05 時点の実測は PF<1 のため、このゲートは
# **意図的に NO-GO を出す**。これはユーザー承認済みの設計であり、GOを出す
# ために閾値を緩めることは許可されていない。
ECON_COHORT_START_DEFAULT = "2026-08-14"
ECON_MIN_SAMPLE = 30


def check_economic_viability(pnl_state: dict, cohort_start: str) -> dict:
    """Required condition: recent-cohort economics must be viable.

    Computes n / PF / expectancy over closed trades with
    exit_time >= cohort_start. Fail-closed: missing pnl_state, missing
    trades, or n < ECON_MIN_SAMPLE all fail (insufficient_sample).
    """
    trades = [
        t for t in (pnl_state.get("trades") or [])
        if t.get("status") == "closed"
        and (t.get("exit_time") or "")[:10] >= cohort_start
        and isinstance(t.get("pnl"), (int, float))
    ]
    n = len(trades)
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = sum(-t["pnl"] for t in trades if t["pnl"] < 0)
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else None)
    expectancy = (sum(t["pnl"] for t in trades) / n) if n else None

    insufficient = n < ECON_MIN_SAMPLE
    pf_ok = pf is not None and pf > 1.0
    expectancy_ok = expectancy is not None and expectancy > 0
    passed = (not insufficient) and pf_ok and expectancy_ok

    pf_str = "n/a" if pf is None else ("inf" if pf == float("inf") else f"{pf:.3f}")
    exp_str = "n/a" if expectancy is None else f"${expectancy:+,.2f}"
    actual = f"n={n}, PF={pf_str}, expectancy={exp_str} (cohort exit_time>={cohort_start})"
    if insufficient:
        actual = f"insufficient_sample: {actual}"

    return {
        "label": "economic_viability",
        "pass": passed,
        "actual": actual,
        "required": f"n>={ECON_MIN_SAMPLE} & PF>1.0 & expectancy>0",
        "econ_detail": {
            "cohort_start": cohort_start,
            "n": n,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "pf": pf_str,
            "expectancy": exp_str,
            "insufficient_sample": insufficient,
        },
    }


def _console_summary_age_hours(summary: dict) -> float | None:
    ts = ((summary.get("run") or {}).get("timestamp"))
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0
        return round(age, 2)
    except Exception:
        return None


def check(econ_cohort_start: str = ECON_COHORT_START_DEFAULT) -> dict[str, dict]:
    summary_path = PROJECT_ROOT / "reports" / "console" / "latest_console_summary.json"
    summary = _load(summary_path)
    health = summary.get("health", {})
    cb = health.get("circuit_breaker_detail", {})
    broker_tracker_diff = summary.get("broker_tracker_diff", {})

    # cron jobs最新run確認
    cron_path = PROJECT_ROOT / "data" / "audits" / "reconcile_status.json"
    reconcile = _load(cron_path)

    results: dict[str, dict] = {}

    # 0. console summary freshness (gates trust in every health.* field below)
    _age_hours = _console_summary_age_hours(summary)
    results["console_summary_freshness"] = {
        "label": "console_summary_freshness",
        "pass": _age_hours is not None and _age_hours <= _CONSOLE_SUMMARY_MAX_AGE_HOURS,
        "actual": f"{_age_hours}h old" if _age_hours is not None else "missing_timestamp",
        "required": f"<={_CONSOLE_SUMMARY_MAX_AGE_HOURS:.0f}h old",
    }

    # 0b. AUDIT FIX (2026-08-23): a diagnostic `--dry-run` invocation writes
    # to the exact same reports/console/latest_console_summary.json path as
    # a real scheduled run, with no way to tell them apart until the
    # dry_run/invocation_source provenance fields were added to
    # ConsoleSummary (2026-08-23). Manually running --dry-run refreshes
    # console_summary_freshness (condition 0 above) and made the overall
    # verdict flip to GO even though no real scheduled paper run had
    # occurred recently -- confirmed live during this same audit. Require
    # the current summary to be real (non-dry-run) evidence, not just fresh.
    _run_meta = summary.get("run", {}) or {}
    _is_dry_run = bool(_run_meta.get("dry_run", False))
    _invocation_source = _run_meta.get("invocation_source", "unknown")
    results["console_summary_not_dry_run"] = {
        "label": "console_summary_not_dry_run",
        "pass": not _is_dry_run,
        "actual": f"dry_run={_is_dry_run} (invocation_source={_invocation_source})",
        "required": "dry_run=False (real scheduled/manual paper run)",
    }

    # 1. ledger_quality VALID
    lg = health.get("ledger_gate_status", "UNKNOWN")
    results["ledger_quality"] = {
        "label": "ledger_quality_gate",
        "pass": lg == "VALID",
        "actual": lg,
        "required": "VALID",
    }

    # 2. circuit_breaker ok
    cb_status = cb.get("status", "UNKNOWN")
    results["circuit_breaker"] = {
        "label": "circuit_breaker",
        "pass": cb_status == "ok",
        "actual": cb_status,
        "required": "ok",
    }

    # 3. broker/tracker mismatch == 0
    #
    # 2026-08-05 fix: previously read health.broker_tracker_mismatch_count,
    # which is the RAW mismatch count before G1-v2/v2-b/v2-c/v2-d lag
    # exclusion is applied (e.g. new-BUY qty lag, SELL qty lag, fast-fill
    # phantom, add-to-existing-position qty lag -- see
    # src/stock_swing/guardrails/postrun_mismatch.py). That raw count can be
    # nonzero for perfectly normal, already-excused timing lag (as seen
    # 2026-08-05: raw=2 for NBIS qty lag, while the lag-exclusion logic
    # itself reports real_mismatch_count=0), causing a false NO-GO here even
    # though circuit_breaker correctly stayed "ok". Use
    # broker_tracker_diff.real_mismatch_count (the same field the live
    # circuit breaker guardrail acts on) so this check matches actual
    # operational risk instead of raw noise.
    if "real_mismatch_count" in broker_tracker_diff:
        mismatch = broker_tracker_diff.get("real_mismatch_count", -1)
        mismatch_label = "broker_tracker_mismatch (real, lag-excused)"
    else:
        # Fallback for older console_summary snapshots that predate the
        # real_mismatch_count field.
        mismatch = health.get("broker_tracker_mismatch_count", -1)
        mismatch_label = "broker_tracker_mismatch (raw, real_mismatch_count unavailable)"
    results["mismatch"] = {
        "label": mismatch_label,
        "pass": mismatch == 0,
        "actual": mismatch,
        "required": 0,
    }

    # 4. attribution coverage >= 98%
    attr = health.get("attribution_coverage_pct", 0.0)
    results["attribution"] = {
        "label": "attribution_coverage_pct",
        "pass": attr >= 95.0,
        "actual": f"{attr}%",
        "required": ">=95%",
    }

    # 5. guardrail hard-halt enabled
    gs = health.get("guardrail_status", "UNKNOWN")
    results["guardrail"] = {
        "label": "guardrail_hard_halt",
        "pass": gs in ("ok", "recovery_pending"),
        "actual": gs,
        "required": "ok or recovery_pending",
    }

    # 6. all crons healthy.
    # AUDIT FIX (2026-08-23): previously only re-read health.status, which is
    # itself one field *inside* the same latest_console_summary.json this
    # whole check() function already loads -- i.e. this condition was 100%
    # redundant with reading `summary` directly and told you nothing extra
    # about actual cron job health (paper_demo/reconcile_orders/collect_data/
    # etc. each have their OWN success/failure independent of paper_demo's
    # self-reported health.status, which only reflects the ledger/guardrail/
    # freshness evidence checked inside that one paper_demo run). Query the
    # real per-job cron run history via console's SystemAdapter
    # (_check_cron_run_history(), the same evidence source the console's own
    # /health endpoint uses) so a genuinely stuck or erroring cron job is
    # caught even when the last paper_demo run itself reported OK. Falls
    # back to the old reconcile_status.json check (fail-open on unavailable,
    # not silently pass) only if SystemAdapter can't be imported/queried.
    _cron_detail = "unavailable"
    _cron_ok = None
    try:
        from console.adapters.system_adapter import SystemAdapter
        _adapter = SystemAdapter(PROJECT_ROOT)
        _cron_evidence = _adapter._check_cron_run_history()
        _cron_ok = bool(_cron_evidence.get("ok"))
        _unhealthy = _cron_evidence.get("unhealthy_jobs") or []
        _cron_detail = (
            f"{_cron_evidence.get('parsed_jobs')}/{_cron_evidence.get('enabled_jobs')} jobs parsed "
            f"({len(_cron_evidence.get('parse_errors') or [])} parse error(s), "
            f"{len(_unhealthy)} job(s) with lastRunStatus=error or consecutiveErrors>0"
            + (f": {[j['job'] for j in _unhealthy]}" if _unhealthy else "")
            + ")"
        )
    except Exception as _cron_exc:
        _cron_detail = f"check_failed: {_cron_exc}"

    if _cron_ok is None:
        # Fall back to the reconcile-only heuristic rather than fail the
        # whole Required checklist on a SystemAdapter import/env issue that
        # is orthogonal to actual cron health.
        rec_status = reconcile.get("status", "UNKNOWN")
        results["cron_health"] = {
            "label": "cron_jobs_healthy",
            "pass": rec_status == "ok" and health.get("status", "") == "OK",
            "actual": f"reconcile={rec_status}, paper_demo_health={health.get('status', 'UNKNOWN')} (SystemAdapter check unavailable: {_cron_detail})",
            "required": "OK",
        }
    else:
        results["cron_health"] = {
            "label": "cron_jobs_healthy",
            "pass": _cron_ok,
            "actual": _cron_detail,
            "required": "all enabled cron jobs parse cleanly (openclaw cron list/runs)",
        }

    # 7. paper N日確認.
    # AUDIT FIX (2026-08-23): previously grepped a single hardcoded file
    # (docs/go_no_go_report_20260731.md) for the literal substring "07-30
    # ok"/"07-30 ✅"/"07-30完了" -- a snapshot of the ORIGINAL 07-31 decision
    # frozen in time. Once that file's content stopped changing (07-31 has
    # long since passed), this condition would return "pass=True" FOREVER
    # regardless of whether paper trading actually ran cleanly in the last 3
    # days, because it never looked at any date-relative or live data at
    # all. Replace with a live check: at least 3 distinct calendar dates
    # with a recorded daily_snapshot in pnl_state.json within the last 7
    # days (a rolling window, not a fixed历史 date), which reflects actual
    # recent operational continuity instead of a permanently-true historical
    # fact.
    # AUDIT FIX (2026-08-23, second pass): the 2026-08-23 rolling-window fix
    # above still had a gap -- it counted ANY daily_snapshots entry within 7
    # days as "paper trading ran that day", including snapshots written by
    # `daily_report_morning` (via performance_snapshot.build_snapshot()),
    # which calls record_daily_snapshot() with signals_generated/
    # orders_submitted/decisions_generated all defaulting to 0 -- i.e. it
    # is a portfolio-value-only bookkeeping snapshot, not evidence that a
    # scheduled paper_demo run actually evaluated signals that day. Confirmed
    # live: 2026-08-21 and 2026-08-22 both have a daily_snapshots entry with
    # decisions_generated=0, generated by the morning report cron on days
    # paper_demo itself produced zero decision files. Require at least one
    # snapshot per counted day with decisions_generated > 0 (i.e. paper_demo
    # actually ran its decision pipeline that day), not just any snapshot.
    _pnl_state_path = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
    _pnl_state = _load(_pnl_state_path)
    _snapshots = _pnl_state.get("daily_snapshots", []) or []
    _now_jst_date = datetime.now(JST).date()
    _recent_dates: set[str] = set()
    for _snap in _snapshots:
        _d = _snap.get("date")
        if not _d:
            continue
        if not _snap.get("decisions_generated"):
            continue  # generic bookkeeping snapshot, not a real paper_demo run
        try:
            _snap_date = datetime.fromisoformat(str(_d)).date()
        except Exception:
            continue
        if (_now_jst_date - _snap_date).days <= 7:
            _recent_dates.add(str(_d))
    _paper_ok = len(_recent_dates) >= 3
    results["paper_3day"] = {
        "label": "paper_3day_confirmation",
        "pass": _paper_ok,
        "actual": f"{len(_recent_dates)} distinct day(s) with a real paper_demo run (decisions_generated>0) in the last 7 days: {sorted(_recent_dates)}",
        "required": ">=3 distinct days with a real scheduled paper_demo run (decisions_generated>0) in the last 7 days",
    }

    # 8. economic_viability (2026-09-05, Required・fail-closed).
    # 「壊れていない」だけでなく「儲かっている」ことをGOの必須条件にする。
    # 詳細はモジュール上部の ECON_COHORT_START_DEFAULT コメント参照。
    # _pnl_state は条件7 (paper_3day) で読み込んだものを再利用。
    results["economic_viability"] = check_economic_viability(_pnl_state, econ_cohort_start)

    return results


def check_promotion_readiness() -> dict[str, dict] | None:
    """R5-v2 (2026-08-14): supplementary, non-required promotion-gate check.

    Separate from the Required conditions in check() above -- this covers
    the previously-missing "market beta / cluster cap / top-5 concentration
    / clean cohort PF" combination called out as the R5-v2 REOPENED reason.
    Recommendation-only: does not affect the overall Go/No-Go decision or
    return code, since these were never part of the original 07-31 Required
    checklist. Returns None (not evaluated) if promotion_gate.py or its
    inputs are unavailable, rather than raising.
    """
    try:
        from stock_swing.risk.promotion_gate import evaluate_promotion_readiness
        from stock_swing.risk.pairwise_correlation import (
            build_daily_closes_from_raw_bars,
            check_data_freshness,
            compute_pairwise_correlation,
            summarize_high_correlation_pairs,
        )
        from console.services.dashboard_service import DashboardService
        from console.services.benchmark_service import BenchmarkService
    except Exception:
        return None

    try:
        dash = DashboardService(PROJECT_ROOT)
        cluster_exposures = dash._get_cluster_exposure()
        positions = dash.get_positions()
        top5 = None
        top5_gross_pct = None
        gross_exposure_pct_of_equity = None
        top5_hhi = None
        held_symbols: list[str] = []
        if positions.get("available"):
            position_rows = positions.get("positions") or []
            # AUDIT FIX (2026-08-23): pass trading context (daily_snapshots)
            # through so _summarize_positions() can compute the equity-based
            # top5 metrics -- without it, latest_equity is None and
            # top5_concentration_equity_pct/gross_exposure_pct_of_equity
            # both come back None (fail-closed in _evaluate_top5_concentration).
            _pnl_state_for_summary = _load(PROJECT_ROOT / "data" / "tracking" / "pnl_state.json")
            summary = dash._summarize_positions(
                position_rows,
                trading={"daily_snapshots": _pnl_state_for_summary.get("daily_snapshots", [])},
            )
            # AUDIT FIX (2026-08-23): pass the EQUITY-based fraction as the
            # primary `top5` value (evaluated against the 40% threshold),
            # not the legacy gross-exposure-based one -- see
            # promotion_gate._evaluate_top5_concentration()'s docstring.
            top5 = summary.get("top5_concentration_equity_pct")
            top5_gross_pct = summary.get("top5_concentration_gross_pct")
            gross_exposure_pct_of_equity = summary.get("gross_exposure_pct_of_equity")
            top5_hhi = summary.get("hhi")
            held_symbols = sorted({str(p.get("symbol") or "").upper() for p in position_rows if p.get("symbol")})

        pnl_state_path = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
        pnl_state = _load(pnl_state_path)
        _all_closed_trades = [t for t in pnl_state.get("trades", []) if t.get("status") == "closed"]
        # AUDIT FIX (2026-08-23): clean_cohort_pf previously fed ALL closed
        # trades (including original_strategy_id in {"broker_reconstructed",
        # "reconciled_from_broker"} -- trades with no link back to any
        # DecisionEngine.process() call, synthesized purely from broker fill
        # history for positions opened before 2026-07-22's metadata-join
        # work) into the promotion-gate PF calculation. Confirmed live
        # (2026-08-23): 252 total closed vs. 49 attributable -- the untracked
        # cohort dominates the blended number by ~5x, so "clean_cohort_pf"
        # was measuring mostly pre-2026-07-22 legacy activity, not the
        # current strategy's actual performance. Mirror PnLTracker.
        # get_attribution_quality_breakdown()'s own classification here
        # (not re-derive it) so promotion readiness uses the same
        # attributable-only population this system's own attribution
        # reporting already considers canonical.
        _untracked_origin_ids = {"broker_reconstructed", "reconciled_from_broker"}
        closed_trades = [
            t for t in _all_closed_trades
            if (t.get("original_strategy_id") or t.get("strategy_id")) not in _untracked_origin_ids
        ]

        bench = BenchmarkService(PROJECT_ROOT)
        daily_snapshots = pnl_state.get("daily_snapshots", [])
        beta_data = bench.calculate_beta(daily_snapshots)

        # R5-v2 (2026-08-14): pairwise correlation among currently-held
        # symbols, reconstructed from accumulated collect_broker_bars()
        # raw snapshots (data/raw/broker/). Best-effort: symbols with too
        # little accumulated history simply drop out (compute_pairwise_
        # correlation / summarize_high_correlation_pairs already fail
        # closed on insufficient data rather than raising).
        raw_broker_dir = PROJECT_ROOT / "data" / "raw" / "broker"
        closes_by_symbol = {
            sym: build_daily_closes_from_raw_bars(sym, raw_broker_dir)
            for sym in held_symbols
        }
        closes_by_symbol = {sym: c for sym, c in closes_by_symbol.items() if c}
        # AUDIT FIX (2026-08-23): a collect_broker_bars() pagination bug (now
        # fixed in collect_data.py) previously left every accumulated
        # snapshot frozen at the same stale date range for weeks. Check
        # freshness explicitly rather than trusting "a correlation was
        # computable" as proof the data is current -- see
        # pairwise_correlation.check_data_freshness() docstring.
        _correlation_freshness = check_data_freshness(closes_by_symbol)
        pairwise = compute_pairwise_correlation(closes_by_symbol)
        correlation_summary = summarize_high_correlation_pairs(pairwise, freshness=_correlation_freshness)

        readiness = evaluate_promotion_readiness(
            cluster_exposures=cluster_exposures,
            top5_concentration=top5,
            top5_concentration_gross_pct=top5_gross_pct,
            gross_exposure_pct_of_equity=gross_exposure_pct_of_equity,
            top5_hhi=top5_hhi,
            beta_data=beta_data,
            closed_trades=closed_trades,
            correlation_summary=correlation_summary,
        )
        return {
            c.name: {
                "label": c.name,
                "pass": c.passed,
                "actual": c.actual,
                "required": c.required,
                "detail": c.detail,
            }
            for c in readiness.criteria
        }
    except Exception as exc:
        return {"error": {"label": "promotion_readiness_check_error", "pass": False, "actual": str(exc), "required": "no error", "detail": ""}}


def _update_ledger_gate_last_checked(ledger_pass: bool, now_jst: datetime) -> None:
    """Stamp ledger_quality_gate.last_checked in current_mode.yaml.

    console self-check (console/adapters/system_adapter.py::_check_ledger_validity)
    treats ledger_quality_gate as stale (and therefore reports it as a
    'critical_missing' evidence failure) if last_checked is more than 24h
    old, even when the gate is genuinely VALID and re-confirmed daily by
    this script. Previously last_checked was only ever bumped by manual
    edits during ledger repair work, so it silently went stale between
    repairs (observed 2026-08-01 -> 2026-08-07, 6 days unedited) and caused
    a false-positive 'blocked' /health status even though everything was
    actually fine. Bump it here on every --save run so daily re-verification
    is reflected without a manual edit each time.

    Only touches the `current_status:` and `last_checked:` lines via
    targeted regex substitution (not a full YAML round-trip) to avoid
    stripping the extensive human-authored comments in this file.
    """
    if not ledger_pass or not CURRENT_MODE_PATH.exists():
        return
    text = CURRENT_MODE_PATH.read_text(encoding="utf-8")
    today = now_jst.strftime("%Y-%m-%d")
    new_text, n1 = re.subn(
        r'(?m)^(  current_status:\s*)\S+(.*)$',
        lambda m: f"{m.group(1)}VALID{m.group(2)}",
        text,
        count=1,
    )
    new_text, n2 = re.subn(
        r'(?m)^(  last_checked:\s*)"?[0-9-]+"?(.*)$',
        lambda m: f'{m.group(1)}"{today}"{m.group(2)}',
        new_text,
        count=1,
    )
    if n1 and n2 and new_text != text:
        CURRENT_MODE_PATH.write_text(new_text, encoding="utf-8")
        print(f"[updated] {CURRENT_MODE_PATH} ledger_quality_gate.last_checked -> {today}", file=sys.stderr)


def format_report(results: dict[str, dict], save: bool = False, promotion: dict[str, dict] | None = None) -> str:
    now_jst = datetime.now(JST)
    all_pass = all(r["pass"] for r in results.values())
    # NOTE (2026-08-15): launch date was hardcoded as "08-20" here even after
    # the 2026-08-14 user decision moved the real-trade launch to 09-15 (see
    # docs/console_improvement_tasks.md "2026-08-14（金）... 09-15に再延期").
    # This script's output is read verbatim by the 08-19/08-21/08-28/09-05/
    # 09-10/09-14 review cron jobs, so a stale hardcoded date would have kept
    # misreporting the wrong launch date across all of them until 09-15
    # itself. Sourced from the roadmap doc; update there first if the date
    # changes again.
    LAUNCH_DATE_LABEL = "09-15"
    decision = f"🟢 **GO**（準備完了 / {LAUNCH_DATE_LABEL}以降にリアルトレード開始）" if all_pass else "🔴 **NO-GO**"

    lines = [
        f"# Go/No-Go 判定結果 — {now_jst.strftime('%Y-%m-%d %H:%M JST')}",
        "",
        f"## 最終判定: {decision}",
        "",
        "## Required 条件チェック",
        "",
        "| 条件 | 判定 | 実測値 | 必要値 |",
        "|------|------|--------|--------|",
    ]
    for r in results.values():
        mark = "✅" if r["pass"] else "❌"
        lines.append(f"| {r['label']} | {mark} | {r['actual']} | {r['required']} |")

    lines += [
        "",
        f"**判定時刻**: {now_jst.strftime('%Y-%m-%d %H:%M:%S JST')}",
        f"**全件 Pass**: {all_pass}",
        "",
    ]

    econ_detail = (results.get("economic_viability") or {}).get("econ_detail")
    if econ_detail:
        lines += [
            "## 経済性ゲート詳細: economic_viability（2026-09-05追加、Required判定に含まれる）",
            "",
            "| 項目 | 値 |",
            "|------|------|",
            f"| コホート | closed trades, exit_time >= {econ_detail['cohort_start']} |",
            f"| n | {econ_detail['n']}（必要: >={ECON_MIN_SAMPLE}、未満は insufficient_sample として fail-closed） |",
            f"| 粗利益 | ${econ_detail['gross_profit']:+,.2f} |",
            f"| 粗損失 | ${-econ_detail['gross_loss']:+,.2f} |",
            f"| PF（粗利益/\\|粗損失\\|） | {econ_detail['pf']}（必要: >1.0） |",
            f"| expectancy（1トレード平均PnL） | {econ_detail['expectancy']}（必要: >0） |",
            f"| insufficient_sample | {econ_detail['insufficient_sample']} |",
            "",
            "注: このゲートは意図的なfail-closed設計。PF<=1.0 の間は他のRequired条件が",
            "全緑でも NO-GO を維持する（2026-09-05 ユーザー承認済み。閾値の緩和は不可）。",
            "",
        ]

    if promotion is not None:
        lines += [
            "## 補足: R5-v2 Promotion Gate（参考情報、Required判定には含まれない）",
            "",
            "| 条件 | 判定 | 実測値 | 必要値 | 詳細 |",
            "|------|------|--------|--------|------|",
        ]
        for r in promotion.values():
            mark = "✅" if r["pass"] else "❌"
            lines.append(f"| {r['label']} | {mark} | {r['actual']} | {r['required']} | {r.get('detail', '')} |")
        lines.append("")

    if all_pass:
        lines += [
            "## 次のアクション",
            "- 本判定は `--save` 付き実行時に `docs/go_no_go_result_YYYYMMDD.md` として自動記録されます（固定ファイル名ではなく実行日ベース）",
            f"- リアルトレード開始: {LAUNCH_DATE_LABEL}以降（50%サイズ）",
            "- 引き続き sector_shock_hold A/B + 20 clean runs soak を継続",
        ]
    else:
        failed = [r["label"] for r in results.values() if not r["pass"]]
        lines += [
            "## ブロック項目",
            *[f"- ❌ {f}" for f in failed],
        ]

    report = "\n".join(lines)

    if save:
        out = PROJECT_ROOT / "docs" / f"go_no_go_result_{now_jst.strftime('%Y%m%d')}.md"
        out.write_text(report, encoding="utf-8")
        print(f"[saved] {out}", file=sys.stderr)
        ledger_pass = results.get("ledger_quality", {}).get("pass", False)
        _update_ledger_gate_last_checked(ledger_pass, now_jst)

    return report


def main() -> int:
    save = "--save" in sys.argv
    econ_cohort_start = ECON_COHORT_START_DEFAULT
    if "--econ-cohort-start" in sys.argv:
        _idx = sys.argv.index("--econ-cohort-start")
        if _idx + 1 >= len(sys.argv):
            print("error: --econ-cohort-start requires a YYYY-MM-DD value", file=sys.stderr)
            return 2
        econ_cohort_start = sys.argv[_idx + 1]
        try:
            datetime.fromisoformat(econ_cohort_start)
        except ValueError:
            print(f"error: invalid --econ-cohort-start date: {econ_cohort_start}", file=sys.stderr)
            return 2
    results = check(econ_cohort_start=econ_cohort_start)
    promotion = check_promotion_readiness()
    report = format_report(results, save=save, promotion=promotion)
    print(report)
    all_pass = all(r["pass"] for r in results.values())
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
