"""Acceptance CONSOLE-RELIABILITY-20261029, base8909e79 + Console12:09.
Actual adapters/service/JSON/JS; only transport, clock and browser storage inputs substituted.
"""
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 29, 14, tzinfo=timezone.utc)
RUN = subprocess.run


def javascript(expression, payload=None):
    program = r'''
const fs=require('fs'),vm=require('vm'),path=require('path');
const input=JSON.parse(fs.readFileSync(0,'utf8')),delays=[];
const ctx={console:{log(){},warn(){},error(){}},document:{addEventListener(){},visibilityState:'visible'},setTimeout:(fn,ms)=>{delays.push(ms);return 1},clearTimeout(){},delays};
if(input?._now){const instant=Date.parse(input._now);ctx.Date=class extends Date{constructor(...args){super(...(args.length?args:[instant]))}static now(){return instant}};}
vm.createContext(ctx);
for(const name of ['utils.js','validators.js','api-client.js','health-monitor.js','app.js'])vm.runInContext(fs.readFileSync(path.join(process.argv[1],name),'utf8'),ctx);
ctx.payload=input;
Promise.resolve(vm.runInContext(process.argv[2],ctx)).then(v=>process.stdout.write(JSON.stringify(v))).catch(e=>{console.error(e);process.exitCode=1});
'''
    r = RUN(['node', '-e', program, str(ROOT/'console/ui'), expression],
                       input=json.dumps(payload), text=True, capture_output=True, timeout=15)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def render(method, data):
    return javascript(f'(()=>{{const c=Object.create(Console.prototype);c.data=payload;return c.{method}()}})()', data)


def test_regression_explicit_api_failure_never_healthy():
    result = javascript('(async()=>{const h=new HealthMonitor();h.registerCheck("api",async()=>({success:false,dataAge:0,errorRate:0}));return await h.runCheck("api")})()')
    assert result['status'] == 'error', 'Explicit acquisition failure must not become healthy'


def test_regression_missing_cron_not_green_zero():
    html = render('renderCronJobs', {})
    assert 'value success">0' not in html and '未確認' in html, 'Missing scheduler acquisition is not no jobs / green zero'


@pytest.mark.parametrize('result,expected', [
    ({'success':True,'dataAge':0,'errorRate':0}, 'healthy'),
    ({'success':True,'source':'cache','dataAge':0,'errorRate':0}, 'warning'),
    ({'success':True,'dataAge':300001,'errorRate':0}, 'warning'),
    ({'success':True,'dataAge':0,'errorRate':.11}, 'warning'),
    ({'success':True,'dataAge':-1,'errorRate':0}, 'unknown'),
    ({'success':True,'dataAge':None,'errorRate':0}, 'unknown'),
    ({}, 'unknown'),
])
def test_ac_health_true_zero_cache_unknown_and_stale(result, expected):
    out = javascript('(async()=>{const h=new HealthMonitor();h.registerCheck("api",async()=>payload);return await h.runCheck("api")})()', result)
    assert out['status'] == expected, 'Supplemental acquisition qualification preserved'


def test_ac_no_health_checks_not_healthy():
    assert javascript('new HealthMonitor().calculateOverallStatus({})') == 'unknown', 'Empty check set is not healthy'


def response(body):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self):return json.dumps(body).encode()
    return Response()


@pytest.mark.parametrize('rows', [[], [{'id':'a','name':'one','enabled':True,'state':{}}]])
def test_ac_cron_http_to_service_to_renderer(monkeypatch,tmp_path,rows):
    from console.adapters.cron_adapter import CronAdapter
    from console.services.dashboard_service import DashboardService
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:response({'jobs':rows}))
    adapter=CronAdapter(tmp_path);service=object.__new__(DashboardService);service.cron_adapter=adapter
    out=service.get_cron_jobs();wire=json.loads(json.dumps(out))
    assert wire['evidence']['status']=='ok' and wire['evidence']['source']=='gateway_http', 'Adapter→service acquisition provenance'
    assert wire['total']==len(rows) and wire['evidence']['as_of'], 'Verified scoped empty/observed rows'
    html=render('renderCronJobs',{'cron_jobs':wire})
    assert 'gateway_http' in html and '取得' in html, 'Real renderer retains original source/clock'
    if not rows:assert '取得範囲内にジョブなし' in html, 'Verified empty remains distinct from missing'


def failed_transport(*args,**kwargs):raise OSError('PRIVATE_DO_NOT_LEAK')


@pytest.mark.parametrize('backup', [None,'corrupt',{'jobs':[]},{'jobs':[{'id':'a','name':'saved','enabled':True}]}])
def test_ac_cron_backup_or_failure_not_current(monkeypatch,tmp_path,backup):
    from console.adapters.cron_adapter import CronAdapter
    from console.services.dashboard_service import DashboardService
    monkeypatch.setattr('urllib.request.urlopen',failed_transport)
    monkeypatch.setattr('console.adapters.cron_adapter.subprocess.run',failed_transport)
    if backup is not None:
        f=tmp_path/'cron_backup/jobs.json';f.parent.mkdir();f.write_text('{' if backup=='corrupt' else json.dumps(backup))
    s=object.__new__(DashboardService);s.cron_adapter=CronAdapter(tmp_path);out=s.get_cron_jobs()
    assert out['total'] is None and out['active'] is None, 'Historical/missing acquisition cannot certify current zero'
    assert out['evidence']['status'] in ('unknown','substitute'), 'Saved snapshot has explicit qualification'
    assert 'PRIVATE' not in json.dumps(out), 'Transport error text not exposed'
    html=render('renderCronJobs',{'cron_jobs':out})
    assert '未確認' in html and 'value success">0' not in html, 'No false green statistics from backup'


@pytest.mark.parametrize('bad',[{}, {'jobs':None},{'jobs':[None]},{'jobs':[],'hasMore':True}, {'jobs':[{'schedule':None}]}, {'jobs':[{'schedule':[]}]}, {'jobs':[{'schedule':{'kind':'every','everyMs':'bad'}}]}])
def test_ac_cron_invalid_or_partial_primary_no_current_total(monkeypatch,tmp_path,bad):
    from console.adapters.cron_adapter import CronAdapter
    from console.services.dashboard_service import DashboardService
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:response(bad))
    monkeypatch.setattr('console.adapters.cron_adapter.subprocess.run',failed_transport)
    s=object.__new__(DashboardService);s.cron_adapter=CronAdapter(tmp_path)
    assert s.get_cron_jobs()['total'] is None, 'Invalid/partial list not a certified complete scoped response'


def test_ac_cron_cli_preserves_provenance(monkeypatch,tmp_path):
    from console.adapters.cron_adapter import CronAdapter
    monkeypatch.setattr('urllib.request.urlopen',failed_transport)
    monkeypatch.setattr('console.adapters.cron_adapter.subprocess.run',lambda *a,**k:SimpleNamespace(returncode=0,stdout='{"jobs":[]}',stderr=''))
    a=CronAdapter(tmp_path);assert a.get_jobs()==[]
    assert a.last_evidence['source']=='gateway_cli' and a.last_evidence['status']=='ok', 'Existing fallback is qualified separately'


def test_ac_missing_next_run_not_zero_lag_or_fake_execution():
    from console.services.dashboard_service import DashboardService
    s=object.__new__(DashboardService)
    row=s._enrich_cron_job({'id':'a','enabled':True,'updatedAtMs':1000},NOW)
    assert row['last_run'] is None and row['lag_seconds'] is None and row['success_rate_7d'] is None, 'Config update is not execution / missing schedule not zero lag / no invented history success'


@pytest.mark.parametrize('stamp,session,interval',[
    ('2026-10-29T14:00:00+00:00','regular',300000),
    ('2026-11-02T15:00:00+00:00','regular',300000),
    ('2026-10-29T03:00:00+00:00','closed',3600000),
    ('2026-10-30T23:00:00+00:00','extended',1800000),
    ('2026-11-26T15:00:00+00:00','closed',3600000),
    ('2026-11-27T17:59:00+00:00','regular',300000),
    ('2026-11-27T18:00:00+00:00','extended',1800000),
])
def test_ac_market_clock_dst_us_friday_holiday_early_close(stamp,session,interval):
    from console.services.market_clock_service import get_market_clock
    out=get_market_clock(datetime.fromisoformat(stamp))
    assert out['session']==session and out['refresh_interval_ms']==interval, 'UTC instant drives NYSE display polling, not browser local hour'
    assert out['timezone']=='America/New_York' and out['next_transition_at'], 'Source and next boundary explicit'


def test_ac_market_unknown_year_or_naive_time_not_qualified():
    from console.services.market_clock_service import get_market_clock
    for dt in [datetime(2026,10,29),datetime(2028,1,4,tzinfo=timezone.utc)]:
        assert get_market_clock(dt)['session']=='unknown', 'Unqualified calendar not a trading-session assertion'


@pytest.mark.parametrize('orders,evidence,code',[
    (None,{},'not_acquired'),
    ([],{'status':'error'},'acquisition_failed'),
    ([],{'status':'ok','as_of':'2020-01-01T00:00:00Z'},'stale_input'),
    ([{}]*500,{'status':'ok','as_of':NOW.isoformat()},'query_cap'),
    ([{}],{'status':'ok','as_of':NOW.isoformat()},'invalid_order'),
])
def test_ac_pending_specific_unknown_reason(orders,evidence,code):
    from console.services.followthrough_service import pending_risk
    out=pending_risk(orders,evidence,NOW)
    assert out['reason_code']==code and out['next_action'], 'Distinct uncertainty reasons and read-only action'
    assert out['observed_active_orders'] is None and out['reserved_cash'] is None, 'No fabricated partial totals'


def test_ac_acceptance_names_units_owner_and_safe_document_link(tmp_path):
    from console.services.followthrough_service import acceptance_evidence,VALUES
    f=tmp_path/VALUES;f.parent.mkdir(parents=True);f.write_text('{}')
    out=acceptance_evidence(tmp_path)
    assert len(out['missing_details'])==16 and all(r['label'] and r['unit'] and r['owner'] for r in out['missing_details']), 'Selected missing fields map to canonical worksheet labels'
    html=render('renderFollowthroughEvidence',{'operational_evidence':{'followthrough':{'acceptance':out}}})
    assert 'capital_B' in html and '本人' in html and 'Agent' in html and '/api/console-evidence/document?name=worksheet' in html, 'Safe canonical worksheet link, no invented values'


def test_ac_worksheet_allowlist_and_missing_fallback(tmp_path):
    from console.services.evidence_service import get_evidence_document
    f=tmp_path/'docs/p4_s1_readiness_20261029/DECISION_WORKSHEET.md';f.parent.mkdir(parents=True);f.write_text('canonical')
    assert get_evidence_document(tmp_path,'worksheet')==f, 'Only canonical worksheet is allowed'
    assert get_evidence_document(tmp_path,'../secret') is None, 'No arbitrary path'


def test_regression_actual_polling_follows_market_not_browser_hour():
    from console.services.market_clock_service import get_market_clock
    clock=get_market_clock(datetime.fromisoformat('2026-10-29T14:00:00+00:00'))
    result=javascript('(async()=>{const c=Object.create(Console.prototype);c.data={market_clock:payload.clock};c.loadData=async()=>{};c.render=()=>{};c.currentTab="overview";c.startAutoRefresh();await Promise.resolve();return delays[0]})()',{'clock':clock,'_now':'2026-10-29T14:00:00+00:00'})
    assert result==300000, 'Actual polling uses regular US session at JST23, not one-hour local nighttime branch'


@pytest.mark.parametrize('change',[
    {}, {'session':'unknown'}, {'timezone':'Asia/Tokyo'}, {'refresh_interval_ms':True},
    {'as_of':'2020-01-01T00:00:00Z'}, {'as_of':'2026-10-29T14:00:01Z'},
    {'as_of':'2026-10-29T14:00:00'}, {'next_transition_at':'2026-10-29T20:00:00'},
    {'next_transition_at':None}, {'next_transition_at':'2026-10-29T13:00:00Z'},
])
def test_ac_polling_unqualified_clock_safe_fallback(change):
    clock={'session':'closed','timezone':'America/New_York','refresh_interval_ms':3600000,
           'as_of':NOW.isoformat(),'next_transition_at':'2026-10-29T20:00:00Z'}
    clock={} if not change else {**clock,**change}
    result=javascript('Console.pollingDelay(payload.clock,Date.now())',{'clock':clock,'_now':NOW.isoformat()})
    assert result==300000, 'Invalid server clock does not switch to browser-hours or slow polling'


def test_ac_polling_next_market_boundary_wakes_early():
    from console.services.market_clock_service import get_market_clock
    stamp='2026-10-29T13:29:30+00:00';clock=get_market_clock(datetime.fromisoformat(stamp))
    result=javascript('Console.pollingDelay(payload.clock,Date.now())',{'clock':clock,'_now':stamp})
    assert result==30000, 'Pre-market polling wakes at regular-open boundary instead of waiting30minutes'


@pytest.mark.parametrize('backup', [None,'{', '{"jobs":[null]}'])
def test_ac_cron_invalid_backup_read_only(monkeypatch,tmp_path,backup):
    from console.adapters.cron_adapter import CronAdapter
    monkeypatch.setattr('urllib.request.urlopen',failed_transport);monkeypatch.setattr('console.adapters.cron_adapter.subprocess.run',failed_transport)
    f=tmp_path/'cron_backup/jobs.json'
    if backup is not None:f.parent.mkdir();f.write_text(backup)
    adapter=CronAdapter(tmp_path);adapter.get_jobs()
    assert adapter.last_evidence['status']=='unknown', 'Missing/corrupt backup does not acquire current data'
    assert (f.read_text() if f.exists() else None)==backup, 'Read does not manufacture/repair backup'


@pytest.mark.parametrize('mode,expected', [('fresh','healthy'),('cached','warning'),('stale','warning'),('failed','error')])
def test_ac_real_api_normalization_cache_to_supplemental_health(mode,expected):
    out=javascript(r"""(async()=>{
      let cached=null;
      globalThis.recoveryManager={cacheData:(k,v)=>{cached=v},getCachedData:()=>cached};
      globalThis.window={};healthMonitor.startMonitoring=()=>{};
      const acquisition=payload.mode==='stale'?'2026-10-29T13:50:00Z':'2026-10-29T14:00:00Z';
      apiClient.fetchWithRetry=async()=>({success:true,data:{time:acquisition,market_clock:payload.clock}});
      await apiClient.getDashboard();
      if(['cached','failed'].includes(payload.mode))apiClient.fetchWithRetry=async()=>({success:false,error:'offline'});
      if(payload.mode==='failed')cached=null;
      initializeMonitoring();const result=await healthMonitor.runCheck('dashboard_api');
      return {status:result.status,dataAge:result.data.dataAge,clock:consoleMarketClock,cachedTime:cached?.time};
    })()""",{'mode':mode,'_now':NOW.isoformat(),'clock':{'timezone':'America/New_York','session':'regular','as_of':NOW.isoformat(),'refresh_interval_ms':300000,'next_transition_at':'2026-10-29T20:00:00Z'}})
    assert out['status']==expected, 'Real validator/API cache cannot erase or renew original acquisition clock'
    if mode!='failed':
        assert out['dataAge']==(600000 if mode=='stale' else 0) and out['clock']['session']=='regular', 'Evidence survives API normalization and reaches monitoring'


def test_ac_pagehide_saves_current_disclosures_before_reload():
    out=javascript(r"""(()=>{
      const store={},events={};
      globalThis.sessionStorage={getItem:()=>null,setItem:(k,v)=>{store[k]=v}};
      globalThis.localStorage={getItem:()=>null};
      const content={querySelectorAll:s=>s==='details'?[{id:'acceptance-missing-fields',open:true}]:[]};
      globalThis.window={addEventListener:(k,v)=>{events[k]=v},scrollY:321};
      document.getElementById=()=>content;Console.prototype.init=()=>{};
      const c=new Console();c._renderedTab='overview';events.pagehide();
      return JSON.parse(store.consoleReadingStateV1).overview;
    })()""")
    assert out['details'][0]['open'] is True and out['scroll']==321, 'Most recent state is saved even without an intervening render'
