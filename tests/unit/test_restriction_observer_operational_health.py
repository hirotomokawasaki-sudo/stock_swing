"""Regression 2026-11-10: workflow OK must not mask PF observer failure.

Only saved producer evidence is assessed; no store/ledger/broker mutation.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('restriction_health_audit', ROOT / 'scripts/audit_operational_readiness.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
NOW = datetime(2026, 11, 9, 16, 30, tzinfo=timezone.utc)
PROTOCOL = 'pf-review-v7-20261106'


def saved(root, *, clock=NOW, review=None):
    data = {'run': {'mode': 'paper', 'status': 'OK', 'run_id': 'paper_demo-fixture',
                    'timestamp': (clock - timedelta(minutes=1)).isoformat(),
                    'dry_run': False, 'invocation_source': 'paper_demo_scheduled'},
            'decision_funnel': {'entry_restriction_review': {
                'status': 'observing', 'protocol': PROTOCOL, 'observations': 0,
                'rows': [], 'candidates': [], 'eligible_to_trade': False,
                'automatic_release': False}}}
    if review is not None:
        data['decision_funnel']['entry_restriction_review'].update(review)
    path = root / 'reports/console/latest_console_summary.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path, data


def report(root):
    return audit.assess(root, now=NOW, expected_restriction_protocol=PROTOCOL)['restriction_observer']


def test_ac_workflow_ok_does_not_mask_observer_error(tmp_path):
    """Incident: Nov9 23:25/23:35 workflow OK while PF v7 was ValueError."""
    path, _ = saved(tmp_path, review={'status': 'error', 'reason': 'ValueError',
                                     'detail': 'private provider error not for output'})
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = report(tmp_path)
    assert result['status'] == 'error', 'producer failure must remain visible'
    assert result['reason_code'] == 'observer_error'
    assert result['reported_error_type'] == 'ValueError'
    assert result['producer_completed'] is False
    assert 'private provider' not in json.dumps(result)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_ac_zero_opportunities_is_observing_not_capture_or_execution_proof(tmp_path):
    saved(tmp_path)
    result = report(tmp_path)
    assert result['status'] == 'observing'
    assert result['reason_code'] == 'no_observations_reported'
    assert result['producer_completed'] is True
    assert result['observations'] == result['completed'] == result['pending'] == 0
    assert result['candidate_capture_reported'] is False
    assert result['store_integrity_verified'] is False
    assert result['trading_or_promotion_authorized'] is False


@pytest.mark.parametrize('mode', ['missing', 'corrupt', 'array', 'missing_review',
                                  'wrong_review_type', 'dry', 'manual', 'live',
                                  'stale', 'future', 'naive', 'no_run_id'])
def test_ac_missing_stale_or_nongenuine_input_is_not_completed(tmp_path, mode):
    path, data = saved(tmp_path)
    if mode == 'missing':
        path.unlink()
    elif mode == 'corrupt':
        path.write_text('{bad')
    elif mode == 'array':
        path.write_text('[]')
    else:
        if mode == 'missing_review': data['decision_funnel'].clear()
        if mode == 'wrong_review_type': data['decision_funnel']['entry_restriction_review'] = []
        if mode == 'dry': data['run']['dry_run'] = True
        if mode == 'manual': data['run']['invocation_source'] = 'manual'
        if mode == 'live': data['run']['mode'] = 'live'
        if mode == 'stale': data['run']['timestamp'] = '2026-11-06T20:55:05Z'
        if mode == 'future': data['run']['timestamp'] = (NOW + timedelta(seconds=1)).isoformat()
        if mode == 'naive': data['run']['timestamp'] = '2026-11-09T16:29:00'
        if mode == 'no_run_id': data['run'].pop('run_id')
        path.write_text(json.dumps(data))
    result = report(tmp_path)
    assert result['producer_completed'] is False, mode
    assert result['observations'] is None, 'unverified input is not zero observations'


@pytest.mark.parametrize('review,code', [
    ({'status': 'disabled'}, 'observer_not_running'),
    ({'protocol': 'pf-review-v2-20261029'}, 'protocol_mismatch'),
    ({'protocol': None}, 'invalid_protocol'),
    ({'eligible_to_trade': True}, 'invalid_release_flags'),
    ({'automatic_release': True}, 'invalid_release_flags'),
    ({'observations': True}, 'invalid_counts'),
    ({'observations': -1}, 'invalid_counts'),
    ({'observations': 1}, 'invalid_counts'),
    ({'rows': None}, 'invalid_counts'),
    ({'candidates': ['IBM']}, 'invalid_candidates'),
    ({'observations': 1, 'rows': [{'cohort': 'a', 'symbol': 'IBM', 'status': [],
                                 'completed': 0, 'pending': 1}]}, 'invalid_counts'),
])
def test_ac_invalid_schema_or_permission_is_not_accepted(tmp_path, review, code):
    saved(tmp_path, review=review)
    result = report(tmp_path)
    assert result['producer_completed'] is False
    assert result['reason_code'] == code


@pytest.mark.parametrize('complete,pending', [(0, 1), (1, 0), (1, 1)])
def test_ac_counts_remain_cohort_totals_not_independent_samples(tmp_path, complete, pending):
    saved(tmp_path, review={'observations': complete + pending, 'rows': [{
        'symbol': 'IBM', 'cohort': 'cohort-a', 'status': 'collecting',
        'completed': complete, 'pending': pending, 'eligible_to_trade': False}]})
    result = report(tmp_path)
    assert result['producer_completed'] is True
    assert result['observations'] == complete + pending
    assert result['completed'] == complete and result['pending'] == pending
    assert result['candidate_capture_reported'] is True
    assert result['store_integrity_verified'] is False
    assert result['trading_or_promotion_authorized'] is False


def test_ac_malformed_error_reason_is_not_exposed_or_thrown(tmp_path):
    saved(tmp_path, review={'status': 'error', 'reason': {'private': 'payload'}})
    result = report(tmp_path)
    assert result['reason_code'] == 'observer_error'
    assert result['reported_error_type'] is None


def test_ac_review_candidate_is_never_release_permission(tmp_path):
    saved(tmp_path, review={'observations': 30, 'candidates': ['IBM'], 'rows': [{
        'symbol': 'IBM', 'cohort': 'a', 'status': 'review_candidate', 'completed': 30,
        'pending': 0, 'eligible_to_trade': False}]})
    result = report(tmp_path)
    assert result['review_candidate_count'] == 1
    assert result['producer_completed'] is True
    assert result['trading_or_promotion_authorized'] is False


def test_ac_duplicate_cohorts_cannot_inflate_counts(tmp_path):
    row = {'symbol': 'IBM', 'cohort': 'a', 'status': 'collecting',
           'completed': 0, 'pending': 1, 'eligible_to_trade': False}
    saved(tmp_path, review={'observations': 2, 'rows': [row, row]})
    assert report(tmp_path)['reason_code'] == 'invalid_counts'


@pytest.mark.parametrize('status,strict,expected', [('error', True, 1),
                                                 ('error', False, 0),
                                                 ('observing', True, 0)])
def test_ac_real_cli_check_exit_and_output(tmp_path, status, strict, expected):
    saved(tmp_path, clock=datetime.now(timezone.utc), review={'status': status})
    command = [sys.executable, '-B', str(ROOT / 'scripts/audit_operational_readiness.py'),
               '--root', str(tmp_path), '--expected-restriction-protocol', PROTOCOL]
    if strict:
        command.append('--require-restriction-observer')
    run = subprocess.run(command, cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                         'PYTHONPATH': str(ROOT / 'src') + os.pathsep + str(ROOT)},
                         capture_output=True, text=True)
    assert run.returncode == expected, run.stdout + run.stderr
    assert json.loads(run.stdout)['restriction_observer']['producer_completed'] is (status == 'observing')
