"""Prospective, non-order price diagnostics for PF-restricted BUY candidates.

No code here can release a restriction, update the trading ledger, or submit an
order. A review candidate is a research triage result, not a promotion decision.
The protocol is fixed in docs/entry_restriction_review_20261028/SPEC.md.
"""
from __future__ import annotations

import fcntl
import hashlib
import html
import json
import math
import os
import tempfile
from contextlib import nullcontext
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from stock_swing.utils.market_calendar import MarketCalendar

ET = ZoneInfo("America/New_York")
STORE = Path("data/analysis/entry_restriction_review_v1.json")
STORE_V2 = Path("data/analysis/entry_restriction_review_v2.json")
STORE_V3 = Path("data/analysis/entry_restriction_review_v3.json")
STORE_V4 = Path("data/analysis/entry_restriction_review_v4.json")
STORE_V5 = Path("data/analysis/entry_restriction_review_v5.json")
STORE_V6 = Path("data/analysis/entry_restriction_review_v6.json")
STORE_V7 = Path("data/analysis/entry_restriction_review_v7.json")
# Financial-only successor; research v8/v9 and all old stores are never migrated.
STORE_V10 = Path("data/analysis/entry_restriction_review_v10.json")
STORE_V11 = Path("data/analysis/entry_restriction_review_v11.json")
STORE_V12 = Path("data/analysis/entry_restriction_review_v12.json")
STORE_V13 = Path("data/analysis/entry_restriction_review_v13.json")
STORE_V14 = Path("data/analysis/entry_restriction_review_v14.json")
STORE_V15 = Path("data/analysis/entry_restriction_review_v15.json")
STORE_V16 = Path("data/analysis/entry_restriction_review_v16.json")
PROTOCOL = {
    "version": "pf-review-v1-20261028",
    "horizon_sessions": 5, "min_completed": 30,
    "base_round_trip_bps": 20, "stress_round_trip_bps": 30,
    "min_stress_pf": 1.20, "min_path_return": -0.07,
    "capture_boundary": "entry_filter_pf_before_downstream_gates",
    "method": "next_session_open_to_fifth_session_close_price_proxy",
    "automatic_release": False,
}


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def _hash(value) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _aware(value) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("ambiguous timestamp")
    return stamp.astimezone(timezone.utc)


def _trading_day(day: date) -> bool:
    return day.weekday() < 5 and not MarketCalendar.is_us_holiday(
        datetime.combine(day, time(12), ET)
    )[0]


def _sessions_after(day: date, count: int) -> list[date]:
    result = []
    while len(result) < count:
        day += timedelta(days=1)
        if _trading_day(day):
            result.append(day)
    return result


def _completed_day(now: datetime) -> date:
    local = now.astimezone(ET)
    day = local.date()
    if local.time() < time(16, 5):
        day -= timedelta(days=1)
    while not _trading_day(day):
        day -= timedelta(days=1)
    return day


def _definition(protocol: dict | None = None) -> dict:
    # Hash actual relevant source, not the Git HEAD (unrelated commits should
    # not reset a study). Never read .env or persist secrets.
    package = Path(__file__).resolve().parents[1]
    files = [Path(__file__), package / "risk/entry_filter.py",
             package / "utils/market_calendar.py", package / "cli/paper_demo.py",
             package / "sources/hybrid_data_fetcher.py"]
    if protocol is not None and protocol.get("version") in {"pf-review-v3-20261103", "pf-review-v4-20261104", "pf-review-v5-20261105", "pf-review-v6-20261105", "pf-review-v7-20261106", "pf-review-v10-20261110", "pf-review-v11-20261110", "pf-review-v12-20261110", "pf-review-v13-20261110", "pf-review-v14-20261110", "pf-review-v15-20261110", "pf-review-v16-20261110"}:
        files.append(package / "sources/massive_client.py")
    if protocol is not None and protocol.get("version") in {"pf-review-v4-20261104", "pf-review-v5-20261105", "pf-review-v6-20261105", "pf-review-v7-20261106", "pf-review-v10-20261110", "pf-review-v11-20261110", "pf-review-v12-20261110", "pf-review-v13-20261110", "pf-review-v14-20261110", "pf-review-v15-20261110", "pf-review-v16-20261110"}:
        files += sorted((package / "execution").glob("*.py"))
        files += [package / "sources/broker_client.py", package / "sources/broker_client_protocol.py"]
    if protocol is not None and protocol.get("version") in {"pf-review-v5-20261105", "pf-review-v6-20261105", "pf-review-v7-20261106", "pf-review-v10-20261110", "pf-review-v11-20261110", "pf-review-v12-20261110", "pf-review-v13-20261110", "pf-review-v14-20261110", "pf-review-v15-20261110", "pf-review-v16-20261110"}:
        files += [package / "experiments/feature_snapshot_store.py",
                  package / "tracking/exit_reason_store.py", package / "tracking/pnl_tracker.py"]
    if protocol is not None and protocol.get("version") in {"pf-review-v6-20261105", "pf-review-v7-20261106", "pf-review-v10-20261110", "pf-review-v11-20261110", "pf-review-v12-20261110", "pf-review-v13-20261110", "pf-review-v14-20261110", "pf-review-v15-20261110", "pf-review-v16-20261110"}:
        files += sorted((package / "tracking").glob("*.py"))
    if protocol is not None and protocol.get("version") in {"pf-review-v11-20261110", "pf-review-v12-20261110", "pf-review-v13-20261110", "pf-review-v14-20261110", "pf-review-v15-20261110", "pf-review-v16-20261110"}:
        files += [package / "reporting/versioned_bridge.py", package / "reporting/equity_bridge_reconciliation.py",
                  package / "reporting/equity_bridge.py", package / "core/runtime.py",
                  package / "guardrails/economic_risk_off.py"]
        files += sorted((package / "execution").glob("*.py"))
        files += sorted((package / "sources").glob("broker*.py"))
        files += sorted((package / "normalization").glob("*broker*.py"))
    if protocol is not None and protocol.get("version") in {"pf-review-v14-20261110", "pf-review-v15-20261110", "pf-review-v16-20261110"}:
        files += sorted((package / "decision_engine").glob("*.py"))
    if protocol is not None and protocol.get("version") in {"pf-review-v15-20261110", "pf-review-v16-20261110"}:
        files.append(package / "reporting/restriction_review_alerts.py")
    files += sorted((package / "strategy_engine").glob("*.py"))
    files += sorted((package / "feature_engine").glob("*.py"))
    files += sorted((package / "risk").glob("*.py"))
    return {
        "protocol": dict(PROTOCOL if protocol is None else protocol),
        "source_hashes": {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in files},
    }


def _study() -> tuple[dict, Path]:
    """Only an explicit fixed version selects a new namespace; never auto-reset."""
    version = os.environ.get("ENTRY_RESTRICTION_REVIEW_VERSION", "v1")
    if version == "v1":
        return dict(PROTOCOL), STORE
    if version == "v2":
        return dict(PROTOCOL, version="pf-review-v2-20261029"), STORE_V2
    if version == "v3":
        return dict(PROTOCOL, version="pf-review-v3-20261103"), STORE_V3
    if version == "v4":
        return dict(PROTOCOL, version="pf-review-v4-20261104"), STORE_V4
    if version == "v5":
        return dict(PROTOCOL, version="pf-review-v5-20261105"), STORE_V5
    if version == "v6":
        return dict(PROTOCOL, version="pf-review-v6-20261105"), STORE_V6
    if version == "v7":
        return dict(PROTOCOL, version="pf-review-v7-20261106"), STORE_V7
    if version == "v10":
        return dict(PROTOCOL, version="pf-review-v10-20261110", history_transition_count=2), STORE_V10
    if version == "v11":
        return dict(PROTOCOL, version="pf-review-v11-20261110", history_transition_count=2), STORE_V11
    if version == "v12":
        return dict(PROTOCOL, version="pf-review-v12-20261110", history_transition_count=2), STORE_V12
    if version == "v13":
        return dict(PROTOCOL, version="pf-review-v13-20261110", history_transition_count=2), STORE_V13
    if version == "v14":
        return dict(PROTOCOL, version="pf-review-v14-20261110", history_transition_count=2), STORE_V14
    if version == "v15":
        return dict(PROTOCOL, version="pf-review-v15-20261110", history_transition_count=2), STORE_V15
    if version == "v16":
        return dict(PROTOCOL, version="pf-review-v16-20261110", history_transition_count=2), STORE_V16
    raise ValueError("unsupported explicit observation version")


def _no_links(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked observation storage")


def _legacy_summary(root: Path, now: datetime) -> dict:
    """Read-only historical counts, never prior rows/candidates or zero fallback."""
    result = {"protocol": PROTOCOL["version"], "role": "historical_only",
              "observations": None, "completed": None, "pending": None,
              "eligible_to_trade": False, "automatic_release": False}
    try:
        path = Path(root) / STORE
        _no_links(path)
        if not path.exists():
            return dict(result, status="missing")
        envelope = json.loads(path.read_text())
        definition = envelope["state"]["definition"]
        if definition["protocol"] != PROTOCOL:
            raise ValueError("legacy protocol mismatch")
        state = _load(path, definition, now)
        items = state["observations"]
        if not all(isinstance(row, dict) and isinstance(row.get("cohort"), str)
                   and "outcome" in row for row in items):
            raise ValueError("legacy observations malformed")
        done = sum(row["outcome"] is not None for row in items)
        return dict(result, status="retained", observations=len(items), completed=done,
                    pending=len(items)-done, definition_hash=state["definition_hash"])
    except Exception:
        return dict(result, status="error")


def _bars(records, symbol: str, now: datetime) -> dict[str, dict | None]:
    result: dict[str, dict | None] = {}
    latest = _completed_day(now)
    for record in records:
        # A malformed record invalidates its identifiable session; unidentifiable
        # timestamps invalidate this fetch instead of quietly cherry-picking rows.
        stamp = _aware(record.event_time)
        day = stamp.astimezone(ET).date()
        if day > latest:
            continue  # Never complete an observation with an intraday/future bar.
        key = day.isoformat()
        try:
            if (record.symbol != symbol or record.event_type != "bar_daily"
                    or record.quality_flags or not record.source or not record.record_id
                    or not _trading_day(day) or _aware(record.ingested_at) > now
                    or _aware(record.as_of) > now):
                raise ValueError("invalid bar provenance")
            values = {k: float(record.payload[k]) for k in ("open", "high", "low", "close", "volume")}
            if (not all(math.isfinite(v) and v > 0 for v in values.values())
                    or values["low"] > min(values["open"], values["close"])
                    or values["high"] < max(values["open"], values["close"])):
                raise ValueError("invalid OHLCV")
            bar = {**values, "source": record.source, "record_id": record.record_id,
                   "event_time": stamp.isoformat(), "ingested_at": _aware(record.ingested_at).isoformat()}
            bar["input_hash"] = _hash(bar)
            # Identical duplicated market values are fine; disagreement or an
            # invalid duplicate poisons the whole date, independent of row order.
            if key in result:
                prior = result[key]
                if prior is None or any(prior[k] != bar[k] for k in (*values, "source")):
                    bar = None
            result[key] = bar
        except (ValueError, TypeError, KeyError, AttributeError):
            result[key] = None
    return result


def _load(path: Path, definition: dict, now: datetime) -> dict:
    if not path.exists():
        return {"definition": definition, "definition_hash": _hash(definition),
                "frozen_at": now.isoformat(), "last_observed_at": now.isoformat(), "observations": []}
    envelope = json.loads(path.read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    state = envelope["state"]
    if envelope["checksum"] != _hash(state) or not isinstance(state["observations"], list):
        raise ValueError("corrupt observation store")
    if state["definition"] != definition or state["definition_hash"] != _hash(definition):
        raise ValueError("study definition changed; explicit new version required")
    if _aware(state["last_observed_at"]) > now or _aware(state["frozen_at"]) > now:
        raise ValueError("observation clock moved backwards")
    return state


def _save(path: Path, state: dict) -> None:
    content = _json({"state": state, "checksum": _hash(state)}) + "\n"
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        # Persist the rename as well as the bytes.
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _assess(observations: list[dict], bars: dict, stopped: set, config_hash: str,
            now: datetime) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for observation in observations:
        groups.setdefault(observation["cohort"], []).append(observation)
    rows = []
    for cohort, items in sorted(groups.items()):
        first = items[0]
        symbol = first["symbol"]
        complete = [item for item in items if item.get("outcome") is not None]
        returns = [item["outcome"]["stress_return"] for item in complete]
        losses = -sum(value for value in returns if value < 0)
        gains = sum(value for value in returns if value > 0)
        pf = gains / losses if losses else None  # No Infinity or misleading sentinel.
        reasons = []
        if symbol not in stopped:
            reasons.append("not_currently_pf_stopped")
        if first["config_hash"] != config_hash:
            reasons.append("different_current_config")
        if bars.get(symbol, {}).get(_completed_day(now).isoformat()) is None:
            reasons.append("latest_completed_bar_missing_or_invalid")
        if any(item.get("waiting_reason") for item in items):
            reasons.append("due_outcome_missing_or_invalid")
        if len(complete) < PROTOCOL["min_completed"]:
            reasons.append("insufficient_nonoverlapping_observations")
        else:
            split = len(returns) // 2
            if mean(returns) <= 0 or gains < PROTOCOL["min_stress_pf"] * losses:
                reasons.append("stress_cost_performance_not_positive")
            if mean(returns[:split]) <= 0 or mean(returns[split:]) <= 0:
                reasons.append("subperiod_inconsistent")
            if min(item["outcome"]["path_return"] for item in complete) < PROTOCOL["min_path_return"]:
                reasons.append("path_loss_exceeds_review_budget")
        rows.append({
            "symbol": symbol, "strategy_id": first["strategy_id"], "cohort": cohort,
            "status": "review_candidate" if not reasons else ("collecting" if len(complete) < PROTOCOL["min_completed"] else "deferred"),
            "completed": len(complete), "pending": len(items) - len(complete),
            "required": PROTOCOL["min_completed"], "stress_mean_return": mean(returns) if returns else None,
            "stress_pf": pf, "reasons": reasons, "eligible_to_trade": False,
            "requires_operator_approval": True, "requires_strategy_exit_validation": True,
        })
    return rows



def _ledger_binding(root, receipt, run_id, config_hash, config, now, decisions, blocked, *, required_history_transitions=None):
    """Verify consumed PF projection against the same locked four-file epoch.

    Stable migration revision partitions studies; changing daily input hashes do
    not reset a cohort. Never recover a journal or infer an absent ledger is zero.
    """
    from stock_swing.tracking.compatibility import read_analysis_snapshot
    from stock_swing.tracking.ledger_transaction import FILES, ledger_transaction, digest
    from stock_swing.risk.pf_history_receipt import load_pf_history, project_pf_history
    expected = os.environ.get('ENTRY_RESTRICTION_REVIEW_LEDGER_REVISION')
    if not expected or expected == 'legacy':
        raise ValueError('explicit corrected ledger revision required')
    state, provenance = read_analysis_snapshot(Path(root)/'data/tracking/pnl_state.json')
    if provenance['ledger_revision'] != expected:
        raise ValueError('unexpected financial revision')
    if required_history_transitions is not None:
        history = state.get('history_migrations', [])
        if (len(history) != required_history_transitions
                or history[-1].get('intent', {}).get('schema_version') != 2):
            raise ValueError('second immutable financial transition required')
    doc = load_pf_history(root, receipt)
    from stock_swing.risk.config_instance_receipts import instance_receipt
    source = instance_receipt(config, 'paper_demo:EntryFilterConfig')
    expected_decisions = [(d.decision_id, d.symbol, d.action, _aware(d.generated_at)) for d in decisions]
    recorded_decisions = [(d['decision_id'], d['symbol'], d['action'], _aware(d['generated_at'])) for d in doc['decisions']]
    if (source['status'] != 'observed' or doc['entry_filter_source_sha256'] != source['source_sha256']
            or recorded_decisions != expected_decisions
            or doc['outputs']['blocked'] != [list(row) for row in blocked]):
        raise ValueError('actual PF boundary receipt mismatch')
    if (doc['run_id'] != run_id or doc['experiment_config_hash'] != config_hash
            or doc['entry_config'] != asdict(config) or _aware(doc['observed_at']) > now
            or doc['history'] != project_pf_history(state['trades'])):
        raise ValueError('PF consumed input does not match locked ledger')
    with ledger_transaction(root, recover=False, blocking=False) as tx:
        hashes = {name: digest(tx.read(Path(root)/'data/tracking'/name)) for name in sorted(FILES)}
    if any(value is None for value in hashes.values()):
        raise ValueError('missing financial input')
    return {**provenance, 'financial_file_sha256': hashes, 'pf_history_receipt': dict(receipt),
            'observed_at': now.isoformat(), 'run_id': run_id,
            'qualification': 'exact_PF_consumed_projection_not_full_execution_or_profit_qualification'}


def observe_restricted_entries(*, root: Path, decisions: list, blocked: list,
                               stop_list: list, records_by_symbol: dict,
                               entry_config, run_id: str, config_hash: str,
                               observed_at: datetime, dry_run: bool = False,
                               mode: str = "paper", signal_config: dict | None = None,
                               pf_history_receipt: dict | None = None) -> dict:
    """Capture actual PF exclusions; mature and review shadow diagnostics only.

    Failure is visible and yields zero candidates. It never changes caller-owned
    decisions, entry settings, real positions, breaker, or trading ledger.
    """
    base = {"protocol": PROTOCOL["version"], "eligible_to_trade": False,
            "automatic_release": False, "rows": [], "candidates": []}
    try:
        protocol, namespace = _study()
        base.update(protocol=protocol["version"], study_role="active", store=namespace.as_posix())
    except ValueError:
        return dict(base, status="error", reason="unsupported_version")
    if os.environ.get("ENTRY_RESTRICTION_REVIEW_ENABLED", "true").lower() in {"0", "false", "no"}:
        return {**base, "status": "disabled"}
    if dry_run or mode != "paper":
        return {**base, "status": "dry_run" if dry_run else "unsupported_mode"}
    try:
        now = _aware(observed_at)
        if not run_id or not config_hash or config_hash == "unknown":
            raise ValueError("missing run/config provenance")
        # Normal jobs intentionally use different PF settings (e.g. the close
        # job's stock-reduced gate). Partition these in prospective cohorts;
        # never treat an ordinary job switch as corrupt global study state.
        effective_config = {"experiment_config_hash": config_hash, "signal_config": signal_config or {},
                            "entry_config": asdict(entry_config)}
        raw_config_hash = config_hash
        config_hash = _hash(effective_config)
        from stock_swing.tracking.ledger_transaction import ledger_transaction
        with (ledger_transaction(root, recover=False, blocking=False) if namespace in {STORE_V6, STORE_V7, STORE_V10, STORE_V11, STORE_V12, STORE_V13, STORE_V14, STORE_V15, STORE_V16} else nullcontext()):
            definition = _definition() if namespace == STORE else _definition(protocol)
            if namespace in {STORE_V2, STORE_V3, STORE_V4, STORE_V5, STORE_V6, STORE_V7, STORE_V10, STORE_V11, STORE_V12, STORE_V13, STORE_V14, STORE_V15, STORE_V16}:
                base["legacy"] = _legacy_summary(root, now)
            binding = None
            if namespace in {STORE_V6, STORE_V7, STORE_V10, STORE_V11, STORE_V12, STORE_V13, STORE_V14, STORE_V15, STORE_V16}:
                binding = _ledger_binding(root, pf_history_receipt, run_id, raw_config_hash, entry_config, now, decisions, blocked,
                    required_history_transitions=protocol.get('history_transition_count'))
                definition['ledger_contract'] = {key: binding[key] for key in ('ledger_revision', 'measurement_status')}
            if namespace in {STORE_V11, STORE_V12, STORE_V13, STORE_V14, STORE_V15, STORE_V16}:
                from stock_swing.reporting.versioned_bridge import load_selected_reconciliation
                from stock_swing.tracking.compatibility import read_analysis_snapshot
                current, _ = read_analysis_snapshot(Path(root)/'data/tracking/pnl_state.json')
                accounting = load_selected_reconciliation(root, expected_account_id=current.get('broker_account_id'),
                    currency='USD', current_trades=current['trades'])
                if accounting is None or accounting['ledger_revision'] != binding['ledger_revision']:
                    raise ValueError('explicit matching accounting selector required')
                definition['accounting_contract'] = dict(version='immutable-adjustment-selector-v1',
                    ledger_revision=accounting['ledger_revision'],
                    artifact_sha256=accounting['reconciliation_artifact_sha256'])
                binding['accounting_contract'] = dict(definition['accounting_contract'])

            path = Path(root) / namespace
            _no_links(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            # A separate lock survives atomic replacement and serializes concurrent
            # regular runs; one-file commits keep capture and completion consistent.
            with path.with_suffix(".lock").open("a+") as lock:
                # A stalled observer must never hold up SELL/risk processing in the
                # regular workflow. Contention defers this observation immediately.
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                state = _load(path, definition, now)
                observations = state["observations"]
                if binding is not None:
                    state["last_ledger_input"] = binding
                bars = {symbol: _bars(records, symbol, now) for symbol, records in records_by_symbol.items()}
                latest = _completed_day(now)
                for item in observations:
                    if item.get("outcome") is not None:
                        continue
                    dates = [date.fromisoformat(day) for day in item["sessions"]]
                    if dates[-1] > latest:
                        continue
                    inputs = [bars.get(item["symbol"], {}).get(day.isoformat()) for day in dates]
                    if any(bar is None for bar in inputs):
                        item["waiting_reason"] = "required_completed_daily_bars_missing_or_invalid"
                        continue
                    opening = inputs[0]["open"]
                    gross = inputs[-1]["close"] / opening - 1
                    item["outcome"] = {
                        "gross_return": gross,
                        "base_return": gross - PROTOCOL["base_round_trip_bps"] / 10000,
                        "stress_return": gross - PROTOCOL["stress_round_trip_bps"] / 10000,
                        "path_return": min(bar["low"] for bar in inputs) / opening - 1 - PROTOCOL["stress_round_trip_bps"] / 10000,
                        "completed_at": now.isoformat(), "run_id": run_id, "inputs": inputs,
                    }
                    if binding is not None:
                        item["outcome"]["ledger_input"] = binding
                    item.pop("waiting_reason", None)
                pf_blocked = {symbol: reason for symbol, reason in blocked
                              if reason.startswith(("rolling_pf_gate:", "stock_reduced_mode:"))}
                for decision in decisions:
                    symbol = decision.symbol
                    if decision.action != "buy" or symbol not in pf_blocked:
                        continue
                    if symbol in entry_config.purchase_restricted_symbols:
                        continue
                    session = now.astimezone(ET).date()
                    if not _trading_day(session):
                        continue
                    prior = [item for item in observations if item["symbol"] == symbol]
                    if any(item.get("outcome") is None or item["capture_session"] >= session.isoformat() for item in prior):
                        continue
                    generated = _aware(decision.generated_at)
                    if generated > now or generated.astimezone(ET).date() != session:
                        raise ValueError("future/stale candidate timestamp")
                    if not decision.decision_id or not decision.strategy_id or not decision.strategy_version_id:
                        raise ValueError("missing decision provenance")
                    identity = {"symbol": symbol, "strategy_id": decision.strategy_id,
                                "strategy_version_id": decision.strategy_version_id, "config_hash": config_hash}
                    if namespace in {STORE_V2, STORE_V3, STORE_V4, STORE_V5, STORE_V6, STORE_V7, STORE_V10, STORE_V11, STORE_V12, STORE_V13, STORE_V14, STORE_V15, STORE_V16}:
                        identity["study_definition_hash"] = _hash(definition)
                        identity["protocol"] = protocol["version"]
                    if binding is not None:
                        from stock_swing.risk.pf_history_receipt import load_pf_history
                        doc = load_pf_history(root, pf_history_receipt, decision_id=decision.decision_id)
                        if [symbol, pf_blocked[symbol]] not in doc["outputs"]["blocked"]:
                            raise ValueError("PF exclusion receipt mismatch")
                    observations.append({
                        **({"ledger_input": binding} if binding is not None else {}),
                        **identity, "cohort": _hash(identity), "run_id": run_id,
                        "effective_config": effective_config,
                        "decision_id": decision.decision_id, "generated_at": generated.isoformat(),
                        "observed_at": now.isoformat(), "capture_session": session.isoformat(),
                        "block_reason": pf_blocked[symbol],
                        "sessions": [day.isoformat() for day in _sessions_after(session, PROTOCOL["horizon_sessions"])],
                        "outcome": None,
                        **({"pf_history_receipt": dict(getattr(decision, "evidence", {}).get("pf_history_receipt", {}))}
                           if namespace in {STORE_V2, STORE_V3, STORE_V4, STORE_V5, STORE_V6, STORE_V7, STORE_V10, STORE_V11, STORE_V12, STORE_V13, STORE_V14, STORE_V15, STORE_V16} else {}),
                    })
                stopped = {row["symbol"] for row in stop_list
                           if row["symbol"] not in entry_config.purchase_restricted_symbols}
                rows = _assess(observations, bars, stopped, config_hash, now)
                for row in rows:
                    row["protocol"] = protocol["version"]
                state["last_observed_at"] = now.isoformat()
                state["last_run_id"] = run_id
                _save(path, state)
        return {**base, "status": "observing", "definition_hash": _hash(definition),
                "frozen_at": state["frozen_at"], "observations": len(observations), "rows": rows,
                "candidates": [row["symbol"] for row in rows if row["status"] == "review_candidate"]}
    except Exception as exc:
        # Do not include exception text (paths or upstream payloads may contain
        # sensitive material). Existing trading gates retain all authority.
        return {**base, "status": "error", "reason": type(exc).__name__,
                "detail": "観測を保留。データ破損・仕様変更・時刻・保存先を確認してください。"}


def format_review_candidates(summary: dict, *, telegram: bool = False) -> str:
    """Bounded operator message; safe for the existing Telegram HTML summary."""
    if summary.get("status") != "observing" or not summary.get("candidates"):
        return ""
    names = ", ".join(sorted(set(summary["candidates"])))[:160]
    if telegram:
        names = html.escape(names)
    return (f"購入停止の再検証候補: {names}\n"
            "購入制限は維持。固定期間の価格診断のみ。本来のExit検証と解除の手動承認が必要。")
