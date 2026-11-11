"""Acceptance: CONSOLE-OPERATIONS-20261028, base 8909e79.

Regression: missing/corrupt latch suppressed alerts; display time replaced
evaluation time. External broker I/O only is replaced. No trading actions.
"""
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from console.services.dashboard_service import DashboardService
from console.services.operational_evidence_service import (
    CONSOLE_FILES, console_fingerprints, get_control_evidence, get_operational_evidence,
)
from tests.unit.test_console_evidence_20261028 import js

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


def write(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def svc(root, *, baseline=False):
    cls = DashboardService
    if baseline and os.environ.get('CONSOLE_REGRESSION_BASELINE'):
        path = Path(os.environ['CONSOLE_REGRESSION_BASELINE']).resolve()
        spec = importlib.util.spec_from_file_location('old_console_operations', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert Path(mod.__file__).resolve() == path, 'Exercise actual baseline source'
        cls = mod.DashboardService
    service = object.__new__(cls)
    service.project_root = root
    return service


@pytest.mark.parametrize('corrupt', [False, True])
def test_regression_missing_corrupt_latch_is_warning(tmp_path, corrupt):
    if corrupt:
        path = write(tmp_path, 'data/guardrails/circuit_breaker.json', {})
        path.write_text('{PRIVATE_BROKEN_TOKEN')
    alert = svc(tmp_path, baseline=True)._check_circuit_breaker_alert()
    assert alert is not None, 'Missing/corrupt latch must not suppress operational warning'
    assert alert['code'] == 'guardrail_evidence_unknown', 'The state is unknown, not a fabricated HALT'
    assert alert['severity'] == 'critical' and alert['updated_at'] is None, 'No current evaluation invented'
    assert 'PRIVATE' not in json.dumps(alert), 'No raw parse error/content leakage'


def test_regression_alert_uses_evaluation_not_display_time(tmp_path):
    write(tmp_path, 'data/guardrails/circuit_breaker.json', {'status':'halted', 'last_evaluated_at':'2026-10-20T02:00:00Z'})
    alert = svc(tmp_path, baseline=True)._check_circuit_breaker_alert()
    assert datetime.fromisoformat(alert['updated_at']) == datetime(2026,10,20,2,tzinfo=timezone.utc), 'Page refresh cannot refresh guardrail evaluation'


@pytest.mark.parametrize('value', [None, [], {}, {'status':'garbage'}, {'status':False}])
def test_ac_invalid_latch_shape_unknown(tmp_path, value):
    write(tmp_path, 'data/guardrails/circuit_breaker.json', value)
    result = get_control_evidence(tmp_path, now=NOW)
    assert result['state'] == 'unknown' and result['status'] == 'invalid', 'Unsupported control data must remain unknown'
    assert result['sell_monitor'] == 'unconfirmed', 'Unknown BUY state is not evidence SELL is monitored'


@pytest.mark.parametrize('state', ['ok','halted','recovery_pending','degraded'])
def test_ac_control_states_preserve_latch_and_eval(tmp_path, state):
    path = write(tmp_path, 'data/guardrails/circuit_breaker.json', {'status':state,'last_evaluated_at':STAMP,'triggered_at':'2026-10-20T02:00:00Z','triggered_rules':[None,{'name':'mismatch'}]})
    before = path.read_bytes()
    e = get_control_evidence(tmp_path, now=NOW)
    assert e['state'] == state and e['as_of'] == STAMP and e['age_seconds'] == 0, 'Recorded state/evaluation travel independently'
    assert e['sell_monitor'] == 'unconfirmed' and path.read_bytes() == before, 'No producer writes or SELL inference'
    html = js('renderOperationalEvidence', {'data':{'operational_evidence':{'control':e}}})
    assert 'SELL監視の実行証拠：未確認' in html and '2026' in html, 'Real renderer preserves monitoring uncertainty and source time'


@pytest.mark.parametrize('stamp', [None,'broken','2026-10-28T12:00:00','2026-10-29T12:00:00Z'])
def test_ac_bad_control_clock_not_mtime(tmp_path, stamp):
    write(tmp_path, 'data/guardrails/circuit_breaker.json', {'status':'halted','last_evaluated_at':stamp})
    result = get_control_evidence(tmp_path, now=NOW)
    assert result['as_of'] is None and result['age_seconds'] is None, 'Never replace invalid/future/naive evaluation with file mtime'
    assert result['buy'] == 'blocked_recorded', 'Bad clock does not remove a recorded HALT'


def summary(root, review=None, **override):
    run = {'mode':'paper','dry_run':False,'invocation_source':'paper_demo_scheduled','run_id':'fixture-run','timestamp':STAMP,'status':'DEGRADED','data_quality':{'status':'INVALID'}}
    run.update(override)
    return write(root,'reports/console/latest_console_summary.json',{'run':run,'decision_funnel':{'entry_restriction_review':review} if review is not None else {}})


@pytest.mark.parametrize('override', [{'dry_run':True},{'mode':'live'},{'invocation_source':'unknown'},{'run_id':''},{'timestamp':'bad'},{'timestamp':'2026-10-29T00:00:00Z'},{'timestamp':'2026-10-28T12:00:00'}])
def test_ac_summary_provenance_refuses_unqualified(tmp_path, override):
    summary(tmp_path, **override)
    e = get_operational_evidence(tmp_path, now=NOW)
    assert e['run']['status'] == 'invalid' and e['run']['scheduled_verified'] is False, 'Not a verified real scheduled run'
    assert e['research']['observations'] is None, 'Unqualified summary cannot create observation counts'


def test_ac_summary_completion_and_effective_config_unconfirmed(tmp_path):
    summary(tmp_path)
    e = get_operational_evidence(tmp_path, now=NOW)
    assert e['run']['status'] == 'ok' and e['run']['result'] == 'DEGRADED', 'Acquisition success is not business success'
    assert e['run']['scheduled_verified'] is False and e['run']['effective_config_verified'] is False, 'Self-declared scheduled source not independently verified'
    html = js('renderRunEvidence', {'data':{'operational_evidence':e}})
    assert 'DEGRADED' in html and '独立照合：未確認' in html and '未照合' in html, 'Uncertainty reaches rendered UI'
    assert e['qualification']['reported_ledger_status'] == 'INVALID', 'Recorded invalid ledger not masked by HTTP/parse success'


def test_ac_old_summary_not_current_research(tmp_path):
    summary(tmp_path, timestamp=(NOW-timedelta(days=2)).isoformat())
    e = get_operational_evidence(tmp_path, now=NOW)
    assert e['run']['status'] == 'stale' and e['research']['observations'] is None, 'Stale records do not become current observation progress'


def review():
    return {'status':'observing','protocol':'pf-review-v1-20261028','eligible_to_trade':False,'automatic_release':False,'observations':3,'rows':[
        {'symbol':'A','strategy_id':'s','cohort':'cfg1','status':'collecting','completed':1,'pending':1,'required':30,'eligible_to_trade':False},
        {'symbol':'A','strategy_id':'s','cohort':'cfg2','status':'deferred','completed':1,'pending':0,'required':30,'eligible_to_trade':False}]}


def test_ac_research_real_summary_cohorts_not_combined(tmp_path):
    summary(tmp_path, review())
    e = get_operational_evidence(tmp_path, now=NOW)
    r = e['research']
    assert r['observations'] == 3 and len(r['rows']) == 2, 'Preserve producer observation total and two distinct cohorts'
    assert r['rows'][0]['completed'] == 1 and r['rows'][1]['completed'] == 1, 'Never merge config cohorts into a qualification sample'
    html = js('renderResearchEvidence', {'data':{'operational_evidence':e}})
    assert 'cfg1' in html and 'cfg2' in html and '1 / 1 / 30' in html and '自動解除なし' in html, 'Per-cohort maturity and no release policy rendered'


@pytest.mark.parametrize('bad', [True,-1,None,'1'])
def test_ac_invalid_research_count_unknown(tmp_path,bad):
    r=review();r['rows'][0]['completed']=bad;summary(tmp_path,r)
    e=get_operational_evidence(tmp_path,now=NOW)
    assert e['research']['status']=='invalid' and e['research']['observations'] is None, 'Bad count must not become zero or mature evidence'


@pytest.mark.parametrize('value', [0,'0','12.5',None,False,'','Infinity','NaN'])
def test_ac_account_values_not_spendable_cash(tmp_path,value):
    e=get_operational_evidence(tmp_path,account={'cash':value,'buying_power':'200'},account_evidence={'status':'ok','as_of':STAMP},pending_evidence={'status':'partial'},now=NOW)
    f=e['funds'];expected=0 if value in (0,'0') and value is not False else 12.5 if value=='12.5' else None
    assert f['cash']==expected and f['buying_power']==200, 'Finite real values including zero only'
    assert f['reserved_cash'] is None and f['projected_concentration'] is None, 'Partial orders/missing intent cannot establish reservations or post-order risk'
    html=js('renderOperationalEvidence',{'data':{'operational_evidence':e}})
    assert 'broker報告' in html and '分類coverage：未確認' in html, 'Reported buying power is not labelled free funds'


@pytest.mark.parametrize('evidence',[{}, {'status':'error'}, {'status':'ok','as_of':'2026-10-20T00:00:00Z'}, {'status':'ok','as_of':'2026-10-29T00:00:00Z'}])
def test_ac_account_unqualified_no_numbers(tmp_path,evidence):
    e=get_operational_evidence(tmp_path,account={'cash':99},account_evidence=evidence,now=NOW)
    assert e['funds']['cash'] is None and e['funds']['status']=='unknown', 'Unverified acquisition cannot show a current balance'


def test_ac_account_real_acquisition_cache_timestamp(tmp_path):
    class Broker:
        calls=0
        def fetch_account(self):
            self.calls+=1
            return SimpleNamespace(payload={'cash':'0','buying_power':'10'})
    service=svc(tmp_path);service._broker=Broker();service._broker_account_cache=None;service._broker_account_cache_ts=0;service._BROKER_CACHE_TTL=120
    first=service._get_broker_account();stamp=service._broker_account_evidence['as_of'];second=service._get_broker_account()
    assert first==second and service._broker.calls==1 and stamp==service._broker_account_evidence['as_of'], 'Cached reads do not fabricate a new acquisition timestamp'
    e=service.get_operational_evidence()
    assert e['funds']['cash']==0 and e['funds']['buying_power']==10, 'Real account service contract reaches read-only operational summary'


def test_ac_account_failure_not_success(tmp_path):
    class Broker:
        def fetch_account(self):raise RuntimeError('PRIVATE_ERROR')
    service=svc(tmp_path);service._broker=Broker();service._broker_account_cache=None;service._broker_account_cache_ts=0;service._BROKER_CACHE_TTL=120
    e=service.get_operational_evidence()
    assert e['funds']['cash'] is None and service._broker_account_evidence['status']=='error', 'Failure cannot create zero balance'
    assert 'PRIVATE' not in json.dumps(e), 'No external free-text errors exposed'


def test_ac_console_startup_hash_does_not_certify_trading(tmp_path):
    for relative in CONSOLE_FILES:
        path=tmp_path/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
    loaded=console_fingerprints(tmp_path);e=get_operational_evidence(tmp_path,loaded_fingerprints=loaded,now=NOW)
    assert e['versions']['console_startup_match'] is True and e['versions']['trading_loaded_version']=='unconfirmed', 'Console byte match not evidence of trading deployment'
    (tmp_path/CONSOLE_FILES[0]).write_text('changed')
    assert get_operational_evidence(tmp_path,loaded_fingerprints=loaded,now=NOW)['versions']['console_startup_match'] is False, 'Changed source cannot stay startup-matched'


def test_ac_missing_and_corrupt_summary_graceful_no_writes(tmp_path):
    e=get_operational_evidence(tmp_path,now=NOW)
    assert e['run']['status']=='missing' and e['research']['observations'] is None, 'Missing producer remains explicit'
    path=summary(tmp_path);path.write_text('[PRIVATE');before=path.read_bytes()
    e=get_operational_evidence(tmp_path,now=NOW)
    assert e['run']['status']=='invalid' and e['qualification']['net_return']=='unconfirmed', 'Corruption cannot qualify returns'
    assert path.read_bytes()==before, 'Read-only evidence must never repair/overwrite producer'


def test_ac_renderer_escapes_and_no_trade_data_still_has_evidence(tmp_path):
    e=get_operational_evidence(tmp_path,now=NOW);e['run']['reason']='<script>PRIVATE</script>'
    html=js('renderTrading',{'data':{'operational_evidence':e,'trading':{'available':False}}})
    assert '<script>PRIVATE' not in html and '&lt;script&gt;' in html, 'Escape all producer text'
    assert 'research-evidence' in html and 'run-evidence' in html and '成績・費用の評価資格' in html, 'Missing trade data does not hide operational uncertainty'


def pending(root, details, baseline=False):
    service=svc(root,baseline=baseline)
    class Broker:
        def fetch_orders(self,**kwargs):raise RuntimeError('external fixture')
    service._broker=Broker();service._broker_orders_cache=None;service._broker_orders_cache_ts=0;service._BROKER_CACHE_TTL=120
    rows=service._fetch_broker_pending_orders([{'subject':'fixture-order','details':details}],[])
    return rows[0]


def test_regression_audit_fractional_quantity_not_zero(tmp_path):
    assert pending(tmp_path,'buy 3.7 A',baseline=True)['qty']=='3.7', 'Audit-only display must not turn fractional quantity into zero'


@pytest.mark.parametrize('details',['','buy NaN A','buy Infinity A','buy -1 A','buy private A'])
def test_ac_invalid_audit_quantity_unknown(tmp_path,details):
    assert pending(tmp_path,details)['qty'] is None, 'Unknown quantity is not numeric zero'


def test_ac_real_summary_producer_json_service_and_renderer(tmp_path):
    from stock_swing.reporting.console_summary import ConsoleSummary
    producer=ConsoleSummary(run_id='actual-producer',timestamp=STAMP,equity=100,
        open_position_count=0,realized_pnl=0,unrealized_pnl=0,signals_total=0,
        signals_buy=0,signals_sell=0,signals_deny=0,orders_submitted=0,orders_rejected=0,
        dry_run=False,invocation_source='paper_demo_scheduled',run_status='DEGRADED',
        entry_filter_stats={'entry_restriction_review':review()})
    write(tmp_path,'reports/console/latest_console_summary.json',producer.to_dict())
    e=get_operational_evidence(tmp_path,now=NOW)
    assert e['research']['status']=='observing' and e['research']['observations']==3, 'Actual producer schema survives serialized file and service'
    html=js('renderTrading',{'data':{'trading':{'available':False},'operational_evidence':e}})
    assert 'cfg1' in html and 'cfg2' in html and 'DEGRADED' in html and '自動解除なし' in html, 'Real renderer preserves producer state, cohorts and no-release boundary'


def test_ac_failed_broker_audit_fractional_quantity_reaches_real_renderer(tmp_path):
    from tests.unit.test_console_evidence_20261028 import service
    s=service(tmp_path,error=True)
    rows=s._fetch_broker_pending_orders([{'subject':'fractional','details':'buy 3.7 A'}],[])
    assert rows[0]['qty']=='3.7' and rows[0]['status']=='unconfirmed', 'Quantity preserved without falsely claiming an accepted order'
    html=js('renderPendingOrdersTable',{'args':[rows,s._broker_orders_evidence]})
    assert '3.7' in html and '取得未確認' in html and '注文ID対応未確認' in html, 'Fraction and acquisition uncertainty both survive rendered fallback'


@pytest.mark.parametrize('field',['status','invocation_source','data_quality'])
def test_ac_malformed_summary_scalars_do_not_crash(tmp_path,field):
    summary(tmp_path,**{field:[]})
    e=get_operational_evidence(tmp_path,now=NOW)
    assert e['run']['scheduled_verified'] is False and e['qualification']['net_return']=='unconfirmed', 'Malformed fields never certify operations'


def test_ac_config_receipt_states_and_no_value_leakage(tmp_path):
    path=summary(tmp_path);data=json.loads(path.read_text());data['effective_config']=[
        {'kind':'instance:EntryFilterConfig','status':'observed','recorded':True,'source_sha256':'a'*64,'effective':{'PRIVATE_SECRET':'NEVER_DISPLAY'}},
        {'kind':'instance:EntryFilterConfig','status':'changed_since_capture','recorded':False,'effective':None},
        {'kind':'instance:LosingPositionAddGuardConfig','status':'not_reached','recorded':True,'effective':None}]
    path.write_text(json.dumps(data));e=get_operational_evidence(tmp_path,now=NOW);c=e['config_instances']
    assert len(c['rows'])==3 and c['all_effective_verified'] is False, 'An endpoint change must not be erased by an earlier observed receipt'
    html=js('renderRunEvidence',{'data':{'operational_evidence':e}})
    assert '取得後の変更あり' in html and '未到達' in html and 'EntryFilterConfig' in html, 'Separate lifecycle statuses reach real UI'
    assert 'NEVER_DISPLAY' not in json.dumps(e) and 'PRIVATE_SECRET' not in html, 'Do not reflect raw config fields, values or environment'


@pytest.mark.parametrize('receipt',[{}, {'kind':'instance:SecretConfig','status':'observed','recorded':True}, {'kind':'instance:EntryFilterConfig','status':[],'recorded':True}, {'kind':'instance:EntryFilterConfig','status':'observed','recorded':'true'}])
def test_ac_unqualified_config_receipt_invalid(tmp_path,receipt):
    path=summary(tmp_path);data=json.loads(path.read_text());data['effective_config']=[receipt];path.write_text(json.dumps(data))
    c=get_operational_evidence(tmp_path,now=NOW)['config_instances']
    assert c['status']=='invalid' and c['rows']==[], 'Unrecognized config contract cannot become verified effective settings'
