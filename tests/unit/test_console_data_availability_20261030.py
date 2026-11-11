"""CONSOLE-DATA-20261030, base8909e79 + deployed 10/29 console.

Regression: historical all/500 saturation hid present open orders; unrelated
missing/unfinished/expired evidence was indistinguishable in the console.
External provider/transport only substituted; real service, JSON and renderer.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from console.services.dashboard_service import DashboardService
from console.services.followthrough_service import pending_risk
from console.services import followthrough_service
from console.services.operational_evidence_service import get_operational_evidence
from tests.unit.test_console_evidence_20261028 import js

NOW = datetime.now(timezone.utc)


def live_scheduler_evidence(*args):
    return followthrough_service.live_scheduler_evidence(*args)


def order(**kw):
    return dict(id='open-one', symbol='TEST', status='pending_cancel', side='buy',
                qty='3.7', filled_qty='1.2', type='limit', limit_price='10', **kw)


def service(root, opened, history=None):
    svc = object.__new__(DashboardService)
    svc.project_root = root
    svc._BROKER_CACHE_TTL = 60
    svc._broker = Mock()
    def fetch(*, status, limit):
        assert limit == 500, 'Existing bounded provider query is reused'
        if status == 'open':
            if isinstance(opened, Exception): raise opened
            return opened
        assert status == 'all', 'Historical query remains separate'
        return history or []
    svc._broker.fetch_orders.side_effect = fetch
    return svc


def test_regression_current_orders_independent_of_capped_history(tmp_path):
    s = service(tmp_path, [order()], [{'id':str(i), 'status':'filled'} for i in range(500)])
    payload = s.get_reconciliation_status()
    assert payload['pending_orders_evidence']['status'] == 'partial', 'Historical cap remains explicit'
    assert payload['current_orders_evidence']['query_status'] == 'open', 'Current acquisition has its own scope'
    assert payload['current_orders'] == dict(open=0, pending_cancel=1, partial=0, other=0)
    assert payload['current_pending_orders'][0]['order_id'] == 'open-one'
    s._get_broker_account = lambda: {}
    wire = json.loads(json.dumps(s.get_operational_evidence(), allow_nan=False))
    pending = wire['followthrough']['pending_risk']
    assert pending['observed_active_orders'] == 1 and pending['observed_limit_buy_notional'] == 25
    assert wire['funds']['reserved_cash'] is None, 'Limit notional is not reserved cash'
    html = js('renderFollowthroughEvidence', {'data':{'operational_evidence':wire}})
    assert '$25.00' in html and 'status=open' in html, 'Current provider→JSON→real renderer propagation'


def test_ac_current_empty_is_measured_zero_without_history_fallback(tmp_path):
    s = service(tmp_path, [], [order()])
    out = s.get_reconciliation_status()
    assert out['current_pending_orders'] == [] and sum(out['current_orders'].values()) == 0
    ev = out['current_orders_evidence']
    assert ev['complete'] is True and ev['status'] == 'ok'
    stamp = ev['as_of']; s._get_broker_open_orders()
    assert s._broker_open_orders_evidence['as_of'] == stamp, 'Cache read preserves original acquisition time'
    assert s._broker.fetch_orders.call_count == 2, 'One history and one current query, cached thereafter'
    html = js('renderPendingOrdersTable', {'args':[[],ev]})
    assert '未約定注文なし' in html and '有無は未確認' not in html


@pytest.mark.parametrize('bad', [RuntimeError('PRIVATE_TOKEN'), None, {}, [None], [{}],
    [{'id':True}], [{'id':'a'}, {'id':'a'}], [{'id':'old','status':'filled'}]])
def test_ac_open_query_failure_or_bad_response_not_false_empty(tmp_path, bad):
    s = service(tmp_path, bad)
    out = s.get_reconciliation_status()
    assert out['current_orders']['open'] is None, 'Unusable acquisition is not measured zero'
    assert out['current_orders_evidence']['status'] == 'error'
    assert 'PRIVATE' not in json.dumps(out['current_orders_evidence'])


def test_ac_open_query_cap_still_partial(tmp_path):
    s = service(tmp_path, [{**order(), 'id':str(i)} for i in range(500)])
    out = s.get_reconciliation_status()
    assert out['current_orders_evidence']['complete'] is False
    assert out['current_orders']['pending_cancel'] is None
    p = pending_risk(s._broker_open_orders_cache, s._broker_open_orders_evidence, NOW + timedelta(seconds=10))
    assert p['reason_code'] == 'query_cap' and p['observed_active_orders'] is None


def test_ac_enrichment_never_starts_current_order_or_scheduler_acquisition(tmp_path):
    s = service(tmp_path, [])
    s._get_broker_account = lambda: {}
    s._get_broker_open_orders = Mock(side_effect=AssertionError('No acquisition in enrichment'))
    s.get_cron_jobs = Mock(side_effect=AssertionError('No scheduler acquisition in enrichment'))
    wire = s.get_operational_evidence()
    s._get_broker_open_orders.assert_not_called(); s.get_cron_jobs.assert_not_called()
    assert wire['followthrough']['pending_risk']['observed_active_orders'] is None


def snapshot(**kw):
    return {'evidence':{'status':'ok','complete':True,'as_of':NOW.isoformat(),'source':'gateway_cli'},
            'jobs':[dict(id='job',name='stock_swing_paper_demo_market_close',enabled=True,
                         last_run=(NOW-timedelta(hours=10)).isoformat(),
                         state={'lastRunStatus':'ok'}, **kw)]}


def test_ac_existing_scheduler_metadata_connected_not_execution_certification():
    out = live_scheduler_evidence(snapshot(), NOW)
    assert out['status'] == 'metadata_observed' and out['registered_job_observed'] is True
    assert out['last_scheduler_status'] == 'ok' and out['as_of'] == NOW.isoformat()
    assert out['scheduled_verified'] is False and out['effective_config_verified'] is False
    assert out['sell_monitor_verified'] is False and out['application_run_linked'] is False
    assert out['rows'][0]['last_run'] != out['as_of'], 'Acquisition time and execution time stay distinct'


@pytest.mark.parametrize('failure', ['absent','error','stale','future','partial','duplicate','bad_job','missing_status'])
def test_ac_unqualified_scheduler_metadata_not_success(failure):
    raw = snapshot()
    if failure == 'absent': raw = None
    elif failure == 'error': raw['evidence']['status'] = 'error'
    elif failure == 'partial': raw['evidence']['complete'] = False
    elif failure in ('stale','future'):
        raw['evidence']['as_of'] = (NOW + timedelta(seconds=-121 if failure=='stale' else 1)).isoformat()
    elif failure == 'duplicate': raw['jobs'] *= 2
    elif failure == 'bad_job': raw['jobs'][0] = None
    elif failure == 'missing_status': raw['jobs'][0]['state'] = {}
    out = live_scheduler_evidence(raw,NOW)
    assert out['status'] != 'metadata_observed', 'Invalid or incomplete metadata is not healthy'
    assert not out['scheduled_verified']


def test_ac_missing_receipts_and_unconnected_fields_have_distinct_reasons(tmp_path):
    wire = json.loads(json.dumps(get_operational_evidence(tmp_path,now=NOW), allow_nan=False))
    rows = {r['key']:r for r in wire['data_availability']}
    assert rows['reserved_cash']['state'] == 'not_connected'
    assert rows['effective_config']['state'] == 'not_recorded'
    assert rows['formal_performance']['state'] == 'not_qualified'
    assert rows['pending_orders']['state'] == 'not_acquired'
    html = js('renderDataAvailability', {'data':{'operational_evidence':wire}})
    for label in ('未接続','未記録','評価条件未充足','未取得'):
        assert label in html, 'Distinct unavailable states reach real renderer'
    wire['data_availability'][0]['reason'] = '<img src=x onerror=alert(1)>'
    html = js('renderDataAvailability', {'data':{'operational_evidence':wire}})
    assert '<img' not in html and '&lt;img' in html, 'Evidence text is escaped'


@pytest.mark.parametrize('evidence,state', [({},'not_acquired'),({'status':'error'},'failed'),
    ({'status':'unknown'},'not_acquired'),
    ({'status':'ok','as_of':(NOW-timedelta(seconds=121)).isoformat()},'stale'),
    ({'status':'ok','as_of':NOW.isoformat()},'available')])
def test_ac_funds_availability_preserves_true_zero(tmp_path,evidence,state):
    out = get_operational_evidence(tmp_path,account={'cash':0,'buying_power':0},account_evidence=evidence,now=NOW)
    row = next(r for r in out['data_availability'] if r['key']=='broker_funds')
    assert row['state'] == state
    assert (out['funds']['cash'] == 0) is (state=='available'), 'Unknown never becomes false zero'


def test_ac_live_scheduler_snapshot_reaches_operational_renderer(tmp_path):
    s = service(tmp_path,[]); s._get_broker_account = lambda: {}
    s._cron_jobs_snapshot = snapshot()
    wire = s.get_operational_evidence()
    scheduler = wire['followthrough']['scheduler']
    assert scheduler['source'] == 'gateway_cli' and scheduler['registered_job_observed']
    html = js('renderFollowthroughEvidence', {'data':{'operational_evidence':wire}})
    assert 'gateway_cli' in html and 'metadata取得済み' in html
