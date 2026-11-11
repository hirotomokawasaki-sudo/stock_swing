"""Bounded read-only operational evidence, not a trading gate or a researcher.

Only allowlisted fields leave this module. File mtime / page refresh never
substitute for acquisition or evaluation time. Nothing writes to a producer.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

SUMMARY = "reports/console/latest_console_summary.json"
CONTROL = "data/guardrails/circuit_breaker.json"
CONSOLE_FILES = ("console/app.py", "console/services/dashboard_service.py",
                 "console/services/operational_evidence_service.py")
INSTANCE_FAMILIES = {
    "DipBuySignalConfig", "DistanceFromHighConfig", "LotLevelExitDiagnosticConfig",
    "NewsSentimentConfig", "NewsShockHoldConfig", "RsiDiagnosticConfig",
    "SectorShockHoldConfig", "ShockAwareStagedExitConfig", "VolatilityGateConfig",
    "EntryFilterConfig", "LosingPositionAddGuardConfig",
}


def _read(root: Path, relative: str) -> tuple[dict, str]:
    path = root / relative
    try:
        if not path.resolve().is_relative_to(root.resolve()):
            return {}, "invalid"
        if not path.is_file():
            return {}, "missing"
        if path.stat().st_size > 8 * 1024 * 1024:
            return {}, "invalid"
        data = json.loads(path.read_text(encoding="utf-8"),
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        return (data, "ok") if isinstance(data, dict) else ({}, "invalid")
    except (OSError, ValueError, TypeError, RecursionError):
        return {}, "invalid"


def _stamp(value, now: datetime) -> tuple[str | None, float | None]:
    try:
        if not isinstance(value, str):
            return None, None
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None, None
        age = (now - stamp).total_seconds()
        return (stamp.isoformat(), age) if age >= 0 else (None, None)
    except (ValueError, TypeError, OverflowError):
        return None, None


def _number(value):
    if isinstance(value, bool) or value is None or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def console_fingerprints(root: Path) -> dict:
    """Fingerprint known Console files at startup, not arbitrary files/secrets."""
    result = {}
    for relative in CONSOLE_FILES:
        path = root / relative
        try:
            if path.resolve().is_relative_to(root.resolve()):
                result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
    return result


def get_control_evidence(root: Path, *, now: datetime | None = None) -> dict:
    """Read the latch and its actual evaluation time without resetting it."""
    now = now or datetime.now(timezone.utc)
    raw, acquisition = _read(root, CONTROL)
    state = raw.get("status")
    if not isinstance(state, str) or state not in {"ok", "halted", "recovery_pending", "degraded"}:
        acquisition = "invalid" if acquisition == "ok" else acquisition
        state = "unknown"
    evaluated, age = _stamp(raw.get("last_evaluated_at"), now)
    triggered, _ = _stamp(raw.get("triggered_at"), now)
    names = []
    if isinstance(raw.get("triggered_rules"), list):
        for row in raw["triggered_rules"][:20]:
            if isinstance(row, dict):
                name = row.get("name") or row.get("metric")
                if isinstance(name, str):
                    names.append(name[:100])
    return {"status": acquisition, "source": CONTROL, "state": state,
            "triggered_at": triggered, "rule_names": names,
            "as_of": evaluated, "age_seconds": age,
            "buy": "blocked_recorded" if state in {"halted", "recovery_pending"} else "not_certified",
            "sell_monitor": "unconfirmed",
            "reason": "停止記録と最終評価は別。status=okも全BUY許可・SELL監視実行の証明ではありません。"}


def _run_and_research(root: Path, now: datetime) -> tuple[dict, dict, dict]:
    snapshot, acquisition = _read(root, SUMMARY)
    raw = snapshot.get("run")
    raw = raw if isinstance(raw, dict) else {}
    stamp, age = _stamp(raw.get("timestamp"), now)
    provenance = (raw.get("mode") == "paper" and raw.get("dry_run") is False
                  and raw.get("invocation_source") in ("paper_demo_scheduled", "paper_demo_cli")
                  and isinstance(raw.get("run_id"), str) and bool(raw["run_id"].strip()))
    status = acquisition if acquisition != "ok" else "ok" if provenance and stamp else "invalid"
    if status == "ok" and age > 86400:
        status = "stale"  # Existing summary-alert display window; never a trading limit.
    result = raw.get("status")
    run = {"status": status, "source": SUMMARY, "as_of": stamp, "age_seconds": age,
           "result": result if isinstance(result, str) and result in {"OK", "DEGRADED", "HALTED", "ERROR"} else "unknown",
           "invocation": raw.get("invocation_source") if provenance else "unknown",
           "scheduled_verified": False, "effective_config_verified": False,
           "reason": "保存サマリーの申告。scheduler実行ID・完了receipt・実効設定との独立照合は未確認。"}
    review = snapshot.get("decision_funnel", {})
    review = review.get("entry_restriction_review") if isinstance(review, dict) else None
    research = {"status": "unknown", "source": SUMMARY, "as_of": stamp,
                "observations": None, "rows": [], "eligible_to_trade": False,
                "reason": "観測結果未取得。有効化・実行・捕捉・成熟評価は別。日数経過では解除しません。"}
    if status == "ok" and isinstance(review, dict):
        state = review.get("status")
        if isinstance(state, str) and state in {"observing", "disabled", "error", "dry_run", "unsupported_mode"}:
            research["status"] = state
        if (state == "observing" and review.get("eligible_to_trade") is False
                and review.get("protocol") in ("pf-review-v1-20261028", "pf-review-v2-20261029")
                and review.get("automatic_release") is False
                and type(review.get("observations")) is int and review["observations"] >= 0
                and isinstance(review.get("rows"), list)):
            rows = []
            for row in review["rows"]:
                if (not isinstance(row, dict) or not all(type(row.get(k)) is int and row[k] >= 0
                        for k in ("completed", "pending", "required"))
                        or not all(isinstance(row.get(k), str) and row[k] for k in ("symbol", "cohort", "strategy_id"))
                        or row.get("eligible_to_trade") is not False
                        or row.get("status") not in ("collecting", "deferred", "review_candidate")):
                    rows = None
                    break
                rows.append({k: row[k] for k in ("symbol", "cohort", "strategy_id", "status", "completed", "pending", "required")})
            if rows is not None and (sum(row["completed"] + row["pending"] for row in rows) != review["observations"]
                    or len({row["cohort"] for row in rows}) != len(rows)):
                rows = None
            if rows is not None:
                research.update(status="observing", observations=review["observations"], rows=rows,
                                protocol=review["protocol"], reason="保存された固定5日診断。cohortは合算せず、実運用PF・解除資格と扱いません。")
                legacy = review.get('legacy')
                if (review['protocol']=='pf-review-v2-20261029' and isinstance(legacy,dict)
                        and legacy.get('status')=='retained' and legacy.get('role')=='historical_only'
                        and all(type(legacy.get(k)) is int and legacy[k]>=0 for k in ('observations','completed','pending'))
                        and legacy['completed']+legacy['pending']==legacy['observations']):
                    research['legacy']={k:legacy[k] for k in ('observations','completed','pending')}
            else:
                research["status"] = "invalid"
        elif state == "observing":
            research["status"] = "invalid"
    elif status != "ok":
        research["status"] = status
    return run, research, snapshot


def _config_instances(snapshot: dict, run_status: str) -> dict:
    result = {"status": "unknown", "rows": [], "all_effective_verified": False,
              "reason": "保存サマリーの設定観測。全設定の実効性・durable receiptとの独立照合は未確認。値・生envはここへ転記しません。"}
    if run_status != "ok":
        result["status"] = run_status
        return result
    raw = snapshot.get("effective_config")
    if raw is None or raw == []:
        return result
    if not isinstance(raw, list) or len(raw) > 100:
        return {**result, "status": "invalid"}
    rows = []
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("kind"), str):
            return {**result, "status": "invalid"}
        if not row["kind"].startswith("instance:"):
            continue  # Legacy non-instance receipts have a different contract.
        family = row["kind"].split(":", 1)[1]
        state = row.get("status")
        if (family not in INSTANCE_FAMILIES or state not in ("observed", "not_reached", "unavailable", "construction_failed", "changed_since_capture")
                or type(row.get("recorded")) is not bool):
            return {**result, "status": "invalid"}
        fingerprint = row.get("source_sha256")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            fingerprint = None
        rows.append({"family": family, "status": state, "recorded": row["recorded"],
                     "source_sha256": fingerprint,
                     "field_count": len(row["effective"]) if isinstance(row.get("effective"), dict) else None})
    return {**result, "status": "reported" if rows else "unknown", "rows": rows}


def get_operational_evidence(root: Path, *, account: dict | None = None,
                             account_evidence: dict | None = None,
                             pending_evidence: dict | None = None,
                             loaded_fingerprints: dict | None = None,
                             positions=None, positions_evidence=None, orders=None,
                             scheduler_snapshot=None,
                             proposal=None,
                             now: datetime | None = None) -> dict:
    """Expose facts and missing inputs; never fetch brokers or calculate returns."""
    now = now or datetime.now(timezone.utc)
    run, research, snapshot = _run_and_research(root, now)
    evidence = account_evidence or {}
    stamp, age = _stamp(evidence.get("as_of"), now)
    account_ok = evidence.get("status") == "ok" and stamp is not None and age <= 120
    account = account or {}
    funds = {"status": "ok" if account_ok else "unknown", "as_of": stamp,
             "source": "broker.fetch_account (Console paper route)",
             "cash": _number(account.get("cash")) if account_ok else None,
             "buying_power": _number(account.get("buying_power")) if account_ok else None,
             "reserved_cash": None, "projected_concentration": None, "classification_coverage": None,
             "pending_status": (pending_evidence or {}).get("status", "unknown"),
             "reason": "cashとbuying_powerはbroker報告値。受渡・予約控除の定義/全未約定/注文案が未接続のため、自由に使える資金・予約額・注文後リスクは未確認。"}
    current = console_fingerprints(root)
    loaded = loaded_fingerprints or {}
    versions = {"console_startup_match": bool(current) and set(current) == set(CONSOLE_FILES)
                and current == loaded,
                "fingerprints": [{"path": k, "sha256": v} for k, v in current.items()],
                "trading_loaded_version": "unconfirmed", "effective_config": "unconfirmed",
                "reason": "Console起動時ファイルとの比較のみ。売買ジョブが読み込んだ版/設定や隔離候補の配備は認定しません。"}
    quality = snapshot.get("run", {})
    quality = quality.get("data_quality", {}) if isinstance(quality, dict) else {}
    quality = quality if isinstance(quality, dict) else {}
    qualification = {"source": SUMMARY, "as_of": run["as_of"], "summary_status": run["status"],
                     "reported_ledger_status": quality.get("status") if quality.get("status") in ("VALID", "INVALID", "UNKNOWN", "valid", "invalid", "unknown") else "unknown",
                     "formal_daily_dd": "unconfirmed", "net_return": "unconfirmed", "invoiced_cost": None,
                     "reason": "参考集計。正式な日次時価DD・同条件比較・全費用控除後の収益は未認定。記録cost=0は請求額でも無料の証拠でもありません。"}
    from console.services.followthrough_service import get_followthrough
    checks = get_followthrough(root, positions=positions, positions_evidence=positions_evidence,
                               orders=orders, orders_evidence=pending_evidence,
                               scheduler_snapshot=scheduler_snapshot, now=now)
    cfg = _config_instances(snapshot, run['status'])
    pending = checks['pending_risk']
    from console.services.operational_inputs_service import funds_projection, portfolio_projection, quality_context
    capacities = funds_projection(account, evidence, now=now)
    portfolio = portfolio_projection(root, positions, positions_evidence, pending, account, evidence, now=now, proposal=proposal)
    diagnostics = quality_context(root, now=now)
    funds_state = ('failed' if evidence.get('status')=='error' else 'not_acquired'
                   if not evidence or evidence.get('status') in (None,'unknown') else 'stale' if not account_ok else 'available'
                   if funds['cash'] is not None and funds['buying_power'] is not None else 'invalid')
    pending_state = ('available' if pending.get('observed_active_orders') is not None else
                     {'acquisition_failed':'failed','query_cap':'partial','partial_input':'partial',
                      'stale_input':'stale','invalid_order':'invalid'}.get(pending.get('reason_code'),'not_acquired'))
    availability = [
        {'key':'broker_funds','label':'現金・買付余力（broker報告）','state':funds_state,
         'as_of':funds['as_of'],'reason':'broker取得値。自由に使える資金とは別。' if funds_state=='available' else '元取得の状態・時刻・数値を確認。取得失敗をゼロにしません。'},
        {'key':'pending_orders','label':'現在の未約定注文','state':pending_state,
         'as_of':pending.get('as_of'),'reason':pending.get('reason'),'next_action':pending.get('next_action')},
        {'key':'reserved_cash','label':'予約資金・自由に使える資金','state':'not_connected',
         'reason':'brokerの予約/受渡控除の定義と取得値が未接続。limit買い残の概算で代用しません。'},
        {'key':'projected_risk','label':'注文後の集中度・分類coverage','state':'available' if portfolio['projected_status']=='limit_buy_scenario' else 'not_qualified',
         'reason':'読取専用の明示指値BUY試算へ接続済み。注文案・鮮度・分類・全未約定の条件が揃う場合だけ算出。自動注文案や売買許可へは未接続。'},
        {'key':'effective_config','label':'実効設定の観測記録','state':'recorded_unqualified' if cfg['rows'] else 'invalid' if cfg['status']=='invalid' else 'not_recorded',
         'as_of':run['as_of'],'reason':'表示可能な設定観測記録。記録OFF/未実行の識別や全設定の独立認定は別。'},
        {'key':'formal_performance','label':'正式な日次時価DD・費用控除後収益','state':'not_qualified',
         'reason':qualification['reason']},
        {'key':'invoiced_cost','label':'API等の実請求額','state':'not_connected',
         'reason':'実請求の通貨・金額が未接続。記録上のcost=0は無料を意味しません。'},
    ]
    return {"control": get_control_evidence(root, now=now), "run": run, "research": research,
            "config_instances": cfg, "data_availability":availability,
            "funds": funds, "capacities": capacities, "portfolio_inputs": portfolio,
            "quality_context": diagnostics,
            "versions": versions, "qualification": qualification, "followthrough": checks}
