"""Acceptance: Oct29 operational follow-up must never manufacture green health.

Exercise real BrokerClient serialization/validation; mock only HTTP transport.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('readiness_audit', ROOT / 'scripts/audit_operational_readiness.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
NOW = datetime(2026, 10, 29, 7, tzinfo=timezone.utc)


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def seed(root):
    put(root, 'reports/console/latest_console_summary.json', {'run': {
        'timestamp': '2026-10-28T19:55:05Z', 'dry_run': False,
        'invocation_source': 'paper_demo_scheduled'}})
    put(root, 'data/guardrails/circuit_breaker.json', {
        'status': 'degraded', 'last_evaluated_at': '2026-10-28T19:55:05Z'})
    put(root, 'data/guardrails/day_start_snapshot.json', {'market_date': '2026-10-28'})
    put(root, 'data/tracking/pnl_state.json', {'trades': []})


def snapshot(*, orders=None, stamp=None):
    return {'status': 'captured', 'requests': [], 'items': {
        key: {'status': 'ok', 'as_of': stamp or NOW.isoformat(), 'complete': True, 'data': rows}
        for key, rows in [('positions', []), ('orders', [] if orders is None else orders)]}}


def order(**kwargs):
    return {'id': 'o1', 'status': 'pending_cancel', 'side': 'buy', 'type': 'limit',
            'qty': '10', 'filled_qty': '4', 'limit_price': '100', **kwargs}


def fingerprints(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def test_ac_overnight_due_slot_explains_age_but_never_clears_health(tmp_path):
    seed(tmp_path)
    before = fingerprints(tmp_path)
    r = audit.assess(tmp_path, now=NOW)
    context = r['scheduled_freshness_context']
    assert context['expected_completed_slot'] == '2026-10-28T19:55:00+00:00'
    assert context['summary_at_or_after_due'] and context['breaker_at_or_after_due']
    assert context['day_start_matches_due_session']
    assert not r['strict_health_unchanged']['guardrail_metric_freshness']['ok']
    assert not r['trading_or_promotion_authorized']
    assert fingerprints(tmp_path) == before


@pytest.mark.parametrize('mode', ['missing', 'corrupt', 'array', 'stale', 'future', 'manual', 'dry'])
def test_saved_evidence_missing_or_unqualified_is_not_fresh(tmp_path, mode):
    seed(tmp_path)
    p = tmp_path / 'reports/console/latest_console_summary.json'
    r = json.loads(p.read_text())
    if mode == 'missing': p.unlink()
    elif mode == 'corrupt': p.write_text('{bad')
    elif mode == 'array': p.write_text('[]')
    else:
        if mode == 'stale': r['run']['timestamp'] = '2026-10-27T19:55:05Z'
        if mode == 'future': r['run']['timestamp'] = (NOW + timedelta(minutes=2)).isoformat()
        if mode == 'manual': r['run']['invocation_source'] = 'diagnostic'
        if mode == 'dry': r['run']['dry_run'] = True
        p.write_text(json.dumps(r))
    assert not audit.assess(tmp_path, now=NOW)['scheduled_freshness_context']['summary_at_or_after_due']


def test_ac_true_empty_open_query_is_zero_not_missing_or_sell_proof(tmp_path):
    seed(tmp_path)
    r = audit.assess(tmp_path, capture=snapshot(), now=NOW)
    assert r['open_orders']['observed_active_orders'] == 0
    assert r['open_orders']['bounded_open_query_complete']
    assert r['open_orders']['reserved_cash'] is None
    assert not r['scheduler']['sell_monitor_verified']
    assert not r['trading_or_promotion_authorized']
    assert not audit.assess(tmp_path, now=NOW)['open_orders']['bounded_open_query_complete']


@pytest.mark.parametrize('rows,stamp,code', [
    ([order()] * 500, None, 'query_cap'),
    ([order(), order()], None, 'invalid_order'),
    ([order(qty='NaN')], None, 'invalid_order'),
    ([order(filled_qty='11')], None, 'invalid_order'),
    ([order(status='unknown')], None, 'invalid_order'),
    ([order()], '2026-10-29T06:55:00Z', 'stale_input'),
    ([order()], '2026-10-29T07:05:00Z', 'stale_input'),
])
def test_ac_cap_invalid_stale_and_future_remain_unknown(tmp_path, rows, stamp, code):
    r = audit.assess(tmp_path, capture=snapshot(orders=rows, stamp=stamp), now=NOW)
    assert r['open_orders']['reason_code'] == code
    assert r['open_orders']['observed_active_orders'] is None
    assert not r['open_orders']['bounded_open_query_complete']


def test_ac_pending_cancel_is_not_released_and_quarantine_blocks_parity(tmp_path):
    seed(tmp_path)
    put(tmp_path, 'data/tracking/pnl_state.json', {'trades': [{'status': 'quarantined'}]})
    r = audit.assess(tmp_path, capture=snapshot(orders=[order()]), now=NOW)
    assert r['open_orders']['pending_cancel'] == 1
    assert r['open_orders']['observed_limit_buy_notional'] == 600
    assert r['open_orders']['reserved_cash'] is None
    assert r['position_quantity_only']['status'] == 'quarantine_present'
    assert r['position_quantity_only']['mismatch_count'] is None


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setenv('BROKER_API_KEY', 'test-key-never-output')
    monkeypatch.setenv('BROKER_API_SECRET', 'test-secret-never-output')
    monkeypatch.setenv('BROKER_BASE_URL', audit.PAPER)
    seen = []
    payloads = [{'status': 'ACTIVE', 'currency': 'USD', 'id': 'sensitive-id'}, [], []]
    def get(self, url, **kwargs):
        seen.append((url, kwargs.get('params')))
        return httpx.Response(200, json=payloads[len(seen)-1], request=httpx.Request('GET', url))
    def forbidden(*args, **kwargs):
        pytest.fail('mutation method must never be called')
    monkeypatch.setattr(httpx.Client, 'get', get)
    monkeypatch.setattr(httpx.Client, 'post', forbidden)
    monkeypatch.setattr(httpx.Client, 'delete', forbidden)
    return seen, payloads


def test_ac_real_broker_client_three_gets_open_scope_and_private_allowlist(tmp_path, transport):
    seen, _ = transport
    r = audit.capture_paper(tmp_path)
    assert len(seen) == 3
    assert seen[-1] == (audit.PAPER + '/v2/orders', {'status': 'open', 'limit': 500})
    assert r['items']['orders']['data'] == []
    assert r['items']['orders']['complete']
    assert r['atomic_snapshot'] is False
    body = json.dumps(r)
    assert 'sensitive-id' not in body and 'test-key' not in body and 'test-secret' not in body


@pytest.mark.parametrize('route', ['https://api.alpaca.markets', 'https://evil.test',
                                   audit.PAPER + '/v3', audit.PAPER + '?x=1'])
def test_other_routes_refused_before_network(tmp_path, transport, monkeypatch, route):
    monkeypatch.setenv('BROKER_BASE_URL', route)
    assert audit.capture_paper(tmp_path)['status'] == 'refused_route'
    assert not transport[0]


def test_credentials_missing_no_network(tmp_path, transport, monkeypatch):
    monkeypatch.delenv('BROKER_API_KEY')
    assert audit.capture_paper(tmp_path)['status'] == 'missing_credentials'
    assert not transport[0]


@pytest.mark.parametrize('payload', [None, {'orders': []}, [None], [float('nan')]])
def test_bad_provider_schema_not_replaced_by_empty(tmp_path, transport, payload):
    transport[1][-1] = payload
    r = audit.capture_paper(tmp_path)
    assert len(transport[0]) == 3
    assert r['items']['orders']['status'] == 'error'
    assert r['items']['orders']['data'] is None
    assert not r['items']['orders']['complete']


def test_provider_error_never_prints_secret_and_no_retry(tmp_path, transport, monkeypatch):
    seen = []
    def fail(*args, **kwargs):
        seen.append(1)
        raise RuntimeError('test-secret-never-output')
    monkeypatch.setattr(httpx.Client, 'get', fail)
    r = audit.capture_paper(tmp_path)
    assert len(seen) == 3  # once per distinct endpoint, not retries
    assert r['status'] == 'partial_or_failed'
    assert 'test-secret' not in json.dumps(r)


def test_existing_or_financial_output_refused_before_get(tmp_path, transport, capsys):
    for destination in (tmp_path, tmp_path / 'data/tracking/new'):
        assert audit.main(['--root', str(tmp_path), '--paper-get', '--output-dir', str(destination)]) == 2
    assert not transport[0]


def test_ac_real_cli_offline_no_network_no_original_writes(tmp_path):
    seed(tmp_path)
    before = fingerprints(tmp_path)
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src') + ':' + str(ROOT)}
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/audit_operational_readiness.py'),
                                '--root', str(tmp_path)], cwd=ROOT, env=env,
                               capture_output=True, text=True, check=True)
    r = json.loads(completed.stdout)
    assert r['paper_get']['status'] == 'not_requested'
    assert not r['paper_get']['requests']
    assert fingerprints(tmp_path) == before


def test_cli_report_output_new_private_directory(tmp_path, transport, capsys):
    destination = tmp_path / 'reports/operations/readonly-audit'
    assert audit.main(['--root', str(tmp_path), '--paper-get', '--output-dir', str(destination)]) == 0
    r = json.loads((destination / 'report.json').read_text())
    assert len(r['paper_get']['requests']) == 3
    assert destination.stat().st_mode & 0o777 == 0o700
    assert (destination / 'report.json').stat().st_mode & 0o777 == 0o600
    assert audit.main(['--root', str(tmp_path), '--output-dir', str(destination)]) == 2
