"""Acceptance / regression: FIX-CONSOLE-EVIDENCE-20261028, base 8909e79.

Missing DD, completed_at-only success and failed order fetch were normal-looking.
Real service and JS renderers; only external broker I/O is substituted.
"""
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from console.services.dashboard_service import DashboardService
from console.services.evidence_service import get_console_evidence, get_evidence_document

ROOT = Path(__file__).resolve().parents[2]


def service(tmp_path, response=None, error=False):
    class Broker:
        def fetch_orders(self, **kwargs):
            assert kwargs == {'status':'all','limit':500}, 'Preserve read-only existing query'
            if error:
                raise RuntimeError('PRIVATE_ERROR_DO_NOT_DISPLAY')
            return SimpleNamespace(payload=response)
    svc=object.__new__(DashboardService)
    svc.project_root=tmp_path
    svc._broker=Broker()
    svc._broker_orders_cache=None
    svc._broker_orders_cache_ts=0
    svc._BROKER_CACHE_TTL=60
    return svc


def js(method, payload):
    node=shutil.which('node')
    assert node, 'Actual JS renderer needs installed Node'
    program="""
const fs=require('fs'),vm=require('vm');
const ctx={console:{log(){},warn(){}},document:{addEventListener(){}}};vm.createContext(ctx);
vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]),'utils.js'),'utf8'),ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
ctx.p=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(vm.runInContext(`(()=>{const view=Object.create(Console.prototype);view.data=p.data||{};return view.${ctx.p.method}(...(p.args||[]));})()`,ctx));
"""
    result=subprocess.run([node,'-e',program,str(ROOT/'console/ui/app.js')],input=json.dumps({'method':method,**payload}),text=True,capture_output=True,timeout=10)
    assert result.returncode==0, result.stderr
    return result.stdout


def test_ac_pending_fetch_error_not_empty_success(tmp_path):
    svc=service(tmp_path,error=True)
    assert svc._fetch_broker_pending_orders([],[])==[], 'No invented order rows'
    evidence=svc._broker_orders_evidence
    assert evidence['status']=='error' and evidence['as_of'] is None, 'Failure remains unknown, not no pending orders'
    assert 'PRIVATE' not in json.dumps(evidence), 'No raw error leakage'
    html=js('renderPendingOrdersTable',{'args':[[],evidence]})
    assert '有無は未確認' in html and '対象注文なし' not in html, 'Failure must not render absence'


@pytest.mark.parametrize('payload',[None,{},[None],[{}],[{'symbol':'A'}]])
def test_ac_bad_broker_response_unknown(tmp_path,payload):
    svc=service(tmp_path,response=payload)
    assert svc._get_broker_orders()==[], 'Invalid broker response is not usable'
    assert svc._broker_orders_evidence['status']=='error', 'Malformed response must be explicit'


def test_ac_verified_empty_and_cache_preserves_acquisition_time(tmp_path):
    svc=service(tmp_path,response=[])
    svc._fetch_broker_pending_orders([],[])
    stamp=svc._broker_orders_evidence['as_of']
    svc._get_broker_orders()
    assert svc._broker_orders_evidence['status']=='ok' and svc._broker_orders_evidence['as_of']==stamp, 'Cache reads cannot refresh acquisition time'
    html=js('renderPendingOrdersTable',{'args':[[],svc._broker_orders_evidence]})
    assert '取得範囲内に対象注文なし' in html and '網羅確認ではありません' in html, 'Verified empty is scoped, not system-wide absence'


@pytest.mark.parametrize('evidence',[{}, {'status':'error'}, {'status':'ok','as_of':'bad'}, {'status':'ok','as_of':'2026-01-01T00:00:00Z'}])
def test_ac_missing_failed_stale_evidence_never_none(evidence):
    html=js('renderPendingOrdersTable',{'args':[[],evidence]})
    assert '有無は未確認' in html, 'Unknown/stale must not claim absence'


def test_ac_same_symbol_different_id_no_false_fill(tmp_path):
    svc=service(tmp_path,response=[{'id':'other','symbol':'A','side':'buy','qty':'3.7','status':'filled','filled_qty':'3.7'}])
    rows=svc._fetch_broker_pending_orders([{'subject':'wanted','details':'buy 3 A'}],[])
    assert rows[0]['status']=='unconfirmed' and rows[0]['broker_status'] is None, 'Symbol-side equality is not order identity'


@pytest.mark.parametrize('status',['accepted','pending_cancel','partially_filled','filled','canceled','rejected','unknown'])
def test_ac_order_lifecycle_exact_id_preserved(tmp_path,status):
    svc=service(tmp_path,response=[{'id':'wanted','symbol':'A','side':'sell','qty':'3.7','status':status,'filled_qty':'1.2'}])
    rows=svc._fetch_broker_pending_orders([{'subject':'wanted','details':'sell 3 A'}],[])
    assert rows[0]['status']==status and rows[0]['qty']=='3.7', 'No acceptance/fill/cancel conflation or truncation'
    html=js('renderPendingOrdersTable',{'args':[rows,svc._broker_orders_evidence]})
    assert '3.7' in html and 'wanted' in html, 'Actual row identity and quantity reach UI'
    if status=='pending_cancel':
        assert '取消依頼中（未確定）' in html and '取消確認済' not in html, 'Cancel request is not confirmation'


def test_ac_limit_is_partial(tmp_path):
    svc=service(tmp_path,response=[{'id':str(i),'status':'accepted'} for i in range(500)])
    svc._get_broker_orders()
    assert svc._broker_orders_evidence['status']=='partial', 'Limit hit cannot establish completeness'


def audits(result=None):
    end={'category':'system','action':'paper_demo_complete','ts':'2026-10-28T02:05:00Z','details':'decisions=1 submitted=0'}
    if result:end['status']=result
    return [end,{'category':'system','action':'paper_demo_start','ts':'2026-10-28T02:00:00Z'}]


def test_ac_completed_timestamp_not_success(tmp_path):
    svc=service(tmp_path)
    runs=svc._summarize_paper_runs(audits())
    assert runs[0]['completed_at'] and runs[0]['result_status']=='completed_unverified', 'Completion alone cannot prove normal operation'
    html=js('_renderPaperRuns',{'args':[{'runs':runs}]})
    assert '終了記録のみ・正常性未確認' in html and '✅' not in html, 'No success icon from completion alone'


@pytest.mark.parametrize('result',['ok','error','degraded'])
def test_ac_explicit_run_result_reaches_renderer(tmp_path,result):
    runs=service(tmp_path)._summarize_paper_runs(audits(result))
    assert runs[0]['result_status']==result, 'Explicit result is preserved'
    html=js('_renderPaperRuns',{'args':[{'runs':runs}]})
    assert {'ok':'約定・利益の証明ではない','error':'失敗記録あり','degraded':'縮退・要確認'}[result] in html, 'Result must propagate to actual renderer'


def test_ac_error_not_overwritten_by_later_success(tmp_path):
    events=audits('ok');events.insert(1,{'category':'error','action':'failed','ts':'2026-10-28T02:03:00Z'})
    runs=service(tmp_path)._summarize_paper_runs(events)
    assert runs[0]['result_status']=='error', 'Late completion must not mask failure'


def test_ac_missing_dd_not_zero():
    html=js('renderOverviewKpis',{'data':{}})
    assert '未計測' in html and '評価資格未確認' in html, 'Missing DD is not measured zero'
    assert '$1,000,000.00' not in html and 'NaN' not in html, 'No invented capital or invalid numerical output'


@pytest.mark.parametrize('value',[0,None,'',False,'NaN','Infinity'])
def test_ac_numeric_boundaries(value):
    html=js('renderOverviewKpis',{'data':{'overview':{'trading_summary':{'max_drawdown_pct':value}}}})
    if value is not None and type(value) is int and value==0:
        assert '0.00%' in html, 'True measured numeric zero remains zero'
    else:
        assert '未計測' in html, 'Invalid DD remains unknown'


def write_evidence(tmp_path):
    path=tmp_path/'docs/console_improvement_tasks.md';path.parent.mkdir();path.write_text('R22')
    data={'schema_version':1,'reviewed_at':'2026-10-28T05:00:00Z','items':[{'title':'<img src=x>','state':'隔離検証済み／稼働未反映','detail':'結果未確認','source':'roadmap','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}
    snapshot=tmp_path/'docs/console_evidence_20261028/status.json';snapshot.parent.mkdir();snapshot.write_text(json.dumps(data))
    return snapshot,path


def test_ac_evidence_hash_invalidation_and_safe_links(tmp_path):
    _,source=write_evidence(tmp_path)
    result=get_console_evidence(tmp_path)
    assert result['status']=='current', 'Matching source hash verifies documentary currency only'
    html=js('renderEvidenceStatus',{'data':{'console_evidence':result}})
    assert '稼働未反映' in html and '&lt;img' in html and '<img' not in html, 'Escape content and do not label deployed'
    assert 'name=roadmap' in html, 'Allowlisted evidence is reachable'
    source.write_text('new plan')
    assert get_console_evidence(tmp_path)['status']=='stale', 'New plan must invalidate old snapshot currency'
    source.unlink()
    assert get_console_evidence(tmp_path)['status']=='stale', 'Missing source remains unverified'


@pytest.mark.parametrize('body',[None,'bad','[]','{}','{"schema_version":1,"reviewed_at":null}'])
def test_ac_evidence_missing_corrupt_fails_unknown(tmp_path,body):
    if body is not None:
        path=tmp_path/'docs/console_evidence_20261028/status.json';path.parent.mkdir(parents=True);path.write_text(body)
    assert get_console_evidence(tmp_path)['status']=='unknown', 'Missing/corrupt evidence never implies completed'


@pytest.mark.parametrize('name',['../../.env','.env','',None,'/etc/passwd','plan/../roadmap'])
def test_ac_document_allowlist(tmp_path,name):
    assert get_evidence_document(tmp_path,name) is None, 'Never expose arbitrary local files'


def test_ac_document_missing_and_outside_symlink(tmp_path):
    assert get_evidence_document(tmp_path,'roadmap') is None, 'Missing allowlisted file is not fabricated'
    (tmp_path/'docs').mkdir();(tmp_path/'docs/console_improvement_tasks.md').symlink_to('/etc/hosts')
    assert get_evidence_document(tmp_path,'roadmap') is None, 'Symlink cannot escape repository'


def test_ac_reconciliation_contract_includes_fetch_evidence(tmp_path):
    svc=service(tmp_path,response=[{'id':'live','symbol':'A','side':'buy','qty':'1','status':'accepted'}])
    payload=svc.get_reconciliation_status()
    assert payload['pending_orders_evidence']['status']=='ok', 'Acquisition status must reach API payload'
    assert payload['pending_orders'][0]['order_id']=='live', 'Live open order without a local audit must not disappear'


def test_ac_conflicting_duplicate_order_id_not_arbitrary_truth(tmp_path):
    svc=service(tmp_path,response=[{'id':'same','status':'accepted'},{'id':'same','status':'filled'}])
    assert svc._get_broker_orders()==[], 'Conflicting observations cannot choose arbitrary last status'
    assert svc._broker_orders_evidence['status']=='error', 'Conflicting duplicate IDs require reconciliation'
