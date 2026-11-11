#!/usr/bin/env python3
"""Read-only operational evidence, not permission to trade or promote.

Offline by default. --paper-get permits at most three existing BrokerClient
GETs, once each; it does not run paper_demo, reconciliation or any writer.
By default exit zero means a report was produced, not that its checks passed.
--require-restriction-observer makes producer-summary completion a checked exit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src'), str(ROOT / 'scripts')]
from check_operational_recovery import expected_run_at, _fresh, _read, _timestamp
from console.adapters.system_adapter import SystemAdapter
from console.services.guardrail_service import _load_dotenv, _get_env
from console.services.followthrough_service import (
    acceptance_evidence, pending_risk, position_comparison, research_inputs,
    scheduler_evidence,
)
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.retry import RetryConfig

PAPER = 'https://paper-api.alpaca.markets'
FIELDS = {
    'account': ('status', 'currency', 'trading_blocked', 'account_blocked'),
    'positions': ('symbol', 'qty', 'side'),
    'orders': ('id', 'symbol', 'side', 'status', 'qty', 'filled_qty',
               'type', 'limit_price', 'created_at', 'updated_at'),
}


def capture_paper(root: Path) -> dict:
    """Explicit bounded GET capture. Never return credentials/provider errors."""
    env = _load_dotenv(root)
    route = _get_env('BROKER_BASE_URL', PAPER, env).strip().strip('\"\'').rstrip('/')
    # Do not silently substitute a different account/route for configured live.
    if route not in (PAPER, PAPER + '/v2'):
        return {'status': 'refused_route', 'requests': [], 'items': {}}
    key = _get_env('BROKER_API_KEY', '', env).strip().strip('\"\'')
    secret = _get_env('BROKER_API_SECRET', '', env).strip().strip('\"\'')
    if not key or not secret:
        return {'status': 'missing_credentials', 'requests': [], 'items': {}}
    client = BrokerClient(api_key=key, api_secret=secret, paper_mode=True,
                          base_url=route, retry_config=RetryConfig(max_attempts=1, timeout=10))
    result = {'status': 'captured', 'started_at': datetime.now(timezone.utc).isoformat(),
              'requests': [], 'items': {}, 'atomic_snapshot': False}
    calls = [('account', '/v2/account', client.fetch_account),
             ('positions', '/v2/positions', client.fetch_positions),
             ('orders', '/v2/orders?status=open&limit=500',
              lambda: client.fetch_orders(status='open', limit=500))]
    for kind, endpoint, fetch in calls:
        trace = {'method': 'GET', 'endpoint': endpoint}
        try:
            envelope = fetch()
            raw = envelope.payload
            valid = (isinstance(raw, dict) if kind == 'account' else
                     isinstance(raw, list) and all(isinstance(row, dict) for row in raw))
            if not valid:
                raise ValueError('invalid schema')
            rows = [raw] if kind == 'account' else raw
            data = [{k: row[k] for k in FIELDS[kind] if k in row} for row in rows]
            # Reject non-JSON/nonfinite values before an evidence file is written.
            json.dumps(data, allow_nan=False)
            item = {'status': 'ok', 'as_of': envelope.fetched_at.isoformat(),
                    'complete': kind != 'orders' or len(data) < 500,
                    'data': data[0] if kind == 'account' else data}
            trace['status'] = 'ok'
        except Exception as exc:
            item = {'status': 'error', 'as_of': None, 'complete': False,
                    'error_type': type(exc).__name__, 'data': None}
            trace['status'] = 'error'
            result['status'] = 'partial_or_failed'
        result['items'][kind] = item
        result['requests'].append(trace)
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    return result


def restriction_observer_status(summary: dict, *, due: datetime, now: datetime,
                                expected_protocol: str | None = None) -> dict:
    """Check saved producer completion, not store integrity or trading permission.

    Workflow exit zero is deliberately not evidence of observer success. Read
    no store and import no observer: this check must not initialize a cohort or
    alter its source-hash definition while scheduled acceptance is pending.
    """
    result = {'status': 'unavailable', 'reason_code': 'missing_observer',
              'protocol': None, 'run_id': None, 'as_of': None,
              'reported_error_type': None, 'producer_completed': False,
              'observations': None, 'completed': None, 'pending': None,
              'review_candidate_count': None, 'candidate_capture_reported': False,
              'store_integrity_verified': False,
              'evidence_scope': 'saved_producer_summary_only',
              'trading_or_promotion_authorized': False}
    run = summary.get('run')
    if (not isinstance(run, dict) or run.get('mode') != 'paper'
            or run.get('dry_run') is not False
            or run.get('invocation_source') != 'paper_demo_scheduled'
            or not isinstance(run.get('run_id'), str) or not run['run_id']):
        return {**result, 'reason_code': 'invalid_run_provenance'}
    stamp = _timestamp(run.get('timestamp'))
    if stamp is None or not due <= stamp <= now:
        return {**result, 'reason_code': 'stale_or_invalid_summary_clock'}
    result.update(run_id=run['run_id'], as_of=stamp.isoformat())
    funnel = summary.get('decision_funnel')
    review = funnel.get('entry_restriction_review') if isinstance(funnel, dict) else None
    if not isinstance(review, dict):
        return result
    protocol = review.get('protocol')
    if not isinstance(protocol, str) or not protocol.startswith('pf-review-v'):
        return {**result, 'reason_code': 'invalid_protocol'}
    result['protocol'] = protocol
    if expected_protocol is not None and protocol != expected_protocol:
        return {**result, 'reason_code': 'protocol_mismatch'}
    if review.get('status') == 'error':
        error = review.get('reason')
        if isinstance(error, str) and error in {'ValueError', 'TypeError', 'KeyError', 'OSError',
                     'FileNotFoundError', 'PermissionError', 'BlockingIOError'}:
            result['reported_error_type'] = error
        return {**result, 'status': 'error', 'reason_code': 'observer_error'}
    if review.get('status') != 'observing':
        return {**result, 'reason_code': 'observer_not_running'}
    if review.get('automatic_release') is not False or review.get('eligible_to_trade') is not False:
        return {**result, 'reason_code': 'invalid_release_flags'}
    count, rows = review.get('observations'), review.get('rows')
    if type(count) is not int or count < 0 or not isinstance(rows, list):
        return {**result, 'reason_code': 'invalid_counts'}
    completed = pending = 0
    candidate_symbols = []
    cohorts = set()
    for row in rows:
        if (not isinstance(row, dict)
                or type(row.get('completed')) is not int or row['completed'] < 0
                or type(row.get('pending')) is not int or row['pending'] < 0
                or not isinstance(row.get('cohort'), str) or not row['cohort']
                or row['cohort'] in cohorts
                or not isinstance(row.get('symbol'), str) or not row['symbol']
                or not isinstance(row.get('status'), str)
                or row['status'] not in {'collecting', 'deferred', 'review_candidate'}
                or row['completed'] + row['pending'] == 0):
            return {**result, 'reason_code': 'invalid_counts'}
        if row.get('eligible_to_trade') is not False:
            return {**result, 'reason_code': 'invalid_release_flags'}
        cohorts.add(row['cohort'])
        completed += row['completed']
        pending += row['pending']
        if row['status'] == 'review_candidate':
            candidate_symbols.append(row['symbol'])
    if completed + pending != count:
        return {**result, 'reason_code': 'invalid_counts'}
    candidates = review.get('candidates')
    if (not isinstance(candidates, list) or any(not isinstance(s, str) for s in candidates)
            or sorted(candidates) != sorted(candidate_symbols)):
        return {**result, 'reason_code': 'invalid_candidates'}
    return {**result, 'status': 'observing', 'producer_completed': True,
            'reason_code': 'no_observations_reported' if count == 0 else 'observations_reported',
            'observations': count, 'completed': completed, 'pending': pending,
            'review_candidate_count': len(candidates), 'candidate_capture_reported': count > 0}


def assess(root: Path, *, capture: dict | None = None, now: datetime | None = None,
           expected_restriction_protocol: str | None = None) -> dict:
    """Describe saved evidence without changing its qualification or timestamps."""
    now = now or datetime.now(timezone.utc)
    due = expected_run_at(now)
    summary, summary_error = _read(root / 'reports/console/latest_console_summary.json')
    breaker, breaker_error = _read(root / 'data/guardrails/circuit_breaker.json')
    day_start, day_error = _read(root / 'data/guardrails/day_start_snapshot.json')
    run = summary.get('run') if isinstance(summary.get('run'), dict) else {}
    genuine = run.get('dry_run') is False and run.get('invocation_source') == 'paper_demo_scheduled'
    adapter = SystemAdapter(root)
    strict = {'ledger_validity': adapter._check_ledger_validity(),
              'guardrail_metric_freshness': adapter._check_guardrail_freshness(),
              'console_summary_freshness': adapter._check_console_summary_freshness()}
    captured = capture or {'status': 'not_requested', 'requests': [], 'items': {}}
    items = captured.get('items', {})
    positions = items.get('positions', {})
    orders = items.get('orders', {})
    pending = pending_risk(orders.get('data'), orders, now)
    pending['scope'] = ('Manual GET status=open/limit=500 only; not the Console status=all cache. '
                        'A moving snapshot, not execution history, reserved cash or buying power.')
    pending['bounded_open_query_complete'] = (
        orders.get('complete') is True and pending.get('status') == 'observed_scope_only')
    expected_date = due.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat()
    return {
        'as_of': now.isoformat(), 'purpose': 'read_only_operational_diagnosis',
        'strict_health_unchanged': strict,
        'scheduled_freshness_context': {
            'expected_completed_slot': due.isoformat(), 'expected_session_date': expected_date,
            'summary_genuine': genuine,
            'summary_at_or_after_due': genuine and _fresh(run.get('timestamp'), due, now),
            'breaker_at_or_after_due': _fresh(breaker.get('last_evaluated_at'), due, now),
            'day_start_matches_due_session': day_start.get('market_date') == expected_date,
            'read_errors': [summary_error, breaker_error, day_error],
            'note': 'Explains overnight age only; does not waive strict warnings or degraded control.'},
        'scheduler': scheduler_evidence(root, now),
        'paper_get': captured,
        'position_quantity_only': position_comparison(root, positions.get('data'), positions, now),
        'open_orders': pending,
        'historical_research_inputs': research_inputs(root),
        'restriction_observer': restriction_observer_status(
            summary, due=due, now=now, expected_protocol=expected_restriction_protocol),
        'adoption_inputs': acceptance_evidence(root),
        'not_certified': ['consumed_effective_settings', 'eligible_sell_start_and_completion',
                          'scheduler_history_run_id', 'whole_account_reconciliation',
                          'prospective_recording_enabled', 'profit_improvement'],
        'trading_or_promotion_authorized': False,
    }


def prepare_output(root: Path, requested: str | None) -> Path | None:
    """Reserve a new private audit directory, refusing canonical output paths."""
    if requested is None:
        return None
    directory = Path(requested).expanduser().resolve()
    if directory.is_relative_to(root.resolve()) and not directory.is_relative_to(
            (root / 'reports/operations').resolve()):
        raise ValueError('output inside repository must be under reports/operations')
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    return directory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--paper-get', action='store_true', help='Explicit three GET Paper probe')
    parser.add_argument('--output-dir', help='New directory only, checked before any GET')
    parser.add_argument('--expected-restriction-protocol', help='Require this producer cohort version')
    parser.add_argument('--require-restriction-observer', action='store_true',
                        help='Exit 1 unless a fresh scheduled Paper summary reports observer completion')
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        directory = prepare_output(root, args.output_dir)
        capture = capture_paper(root) if args.paper_get else None
        report = assess(root, capture=capture,
                        expected_restriction_protocol=args.expected_restriction_protocol)
        body = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if directory:
            fd = os.open(directory / 'report.json', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(body + '\n')
        print(body)
        return 1 if (args.require_restriction_observer
                     and not report['restriction_observer']['producer_completed']) else 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({'status': 'audit_failed', 'error_type': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
