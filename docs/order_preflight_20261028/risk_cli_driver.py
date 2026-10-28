"""Actual CLI on a disposable copy; only external HTTP transports substituted."""
from pathlib import Path
import contextlib,io,json,sys,os,re
from datetime import datetime,timedelta,timezone
import httpx,urllib3
calls=[]
def transport(request):
    calls.append([request.method,request.url.path])
    if request.url.path.endswith('/account'):
        return httpx.Response(200,json=dict(status='ACTIVE',equity='100000',cash='100000',buying_power='100000'))
    if request.url.path.endswith('/positions'):return httpx.Response(200,json=[])
    if request.url.path.endswith('/bars'):
        bars=[dict(t=(datetime.now(timezone.utc)-timedelta(minutes=5*(20-i))).isoformat(),o=129,h=131,l=128,c=130,v=2000000) for i in range(20)]
        return httpx.Response(200,json=dict(bars=bars))
    if 'quotes' in request.url.path:return httpx.Response(200,json={'quote':{'bp':129,'ap':131}})
    if 'orders' in request.url.path:return httpx.Response(200,json=[])
    raise AssertionError('unexpected fixture request '+request.url.path)
original=httpx.Client
httpx.Client=lambda **kw:original(transport=httpx.MockTransport(transport),**kw)
def massive_http(self,method,url,**kw):
    from urllib.parse import urlsplit
    path=urlsplit(url).path;calls.append([method,path])
    if '/aggs/' in path:
        rows=[]
        for i in range(20):
            dt=datetime.now(timezone.utc)-timedelta(days=20-i)
            close=100+i*1.6
            rows.append(dict(t=int(dt.timestamp()*1000),o=close-1,h=close+2,l=close-2,c=close,v=2000000,vw=close,n=10))
        data=dict(results=rows,adjusted=True,request_id='controlled-request')
    elif 'rsi' in path:data=dict(results=dict(values=[]))
    elif 'reference/tickers' in path:data=dict(results=dict(ticker='NVDA',name='Fixture',market='stocks',currency_name='usd'))
    else:raise AssertionError('unexpected Massive fixture request '+path)
    return urllib3.response.HTTPResponse(body=json.dumps(data).encode(),status=200,preload_content=True)
urllib3.PoolManager.request=massive_http
from stock_swing.cli import paper_demo
root=paper_demo.project_root
# The clock is an external test input; no strategy/filter/executor is replaced.
class FixtureClock(datetime):
    @classmethod
    def now(cls, tz=None):
        fixed=datetime(2026,10,28,15,tzinfo=timezone.utc)
        return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
paper_demo.datetime=FixtureClock
buf=io.StringIO()
with contextlib.redirect_stdout(buf),contextlib.redirect_stderr(buf):
    sys.argv=['paper_demo','--symbols','NVDA','--dry-run','--min-momentum','0.01','--min-signal-strength','0.1','--cron-summary-json']

    try:result=paper_demo.main()
    except BaseException as exc:print(type(exc).__name__,str(exc));result=99
indices=[]
summary_path=root/'reports/console/latest_console_summary.json'
summary=json.loads(summary_path.read_text()) if summary_path.exists() else {}
text_output=buf.getvalue()
output=dict(main_exit=result,http_calls=calls,store_exists=(root/'data/audits/measurement_inputs').exists(),
    indices=len(indices),origin_is_copy=Path(paper_demo.__file__).resolve().is_relative_to(root.resolve()),
    business_decision_lines=re.findall(r'\[(?:PASS|SKIP)\] [^\n]+',buf.getvalue()))
if indices:
    from stock_swing.experiments.decision_input_capture import load_input_run
    run=load_input_run(root,str(indices[0].relative_to(root)))
    output['capture_complete']=run['capture_complete'];output['declared_exit_success']=run['declared_exit_success']
    output['stage_counts']={stage:sum(o['manifest']['stage']==stage for o in run['observations']) for stage in {o['manifest']['stage'] for o in run['observations']}}
    output['full_replay_ready']=run['full_replay_ready']
output['summary_risk']=summary.get('risk',{})
output['run_status']=summary.get('run',{}).get('status')
output['funnel']=summary.get('decision_funnel',{})
output['would_buy_lines']=re.findall(r'^    BUY [^\n]+',text_output,re.M)
output['audit_block_recorded']=any('risk_budget_blocked_buys' in p.read_text() for p in (root/'data/audits').glob('paper_demo_*.log'))
output['risk_lines']=[line.strip() for line in text_output.splitlines() if 'Risk budget' in line]
output['diagnostic_tail']=text_output[-2500:] if result else ''

print(json.dumps(output,sort_keys=True,indent=2))
