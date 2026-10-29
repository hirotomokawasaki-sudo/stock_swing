"""Actual CLI on a disposable copy; only external HTTP transports substituted."""
from pathlib import Path
import contextlib,io,json,sys,os,re
from datetime import datetime,timedelta,timezone
import httpx,urllib3
calls=[]
posts=[]
scenario=json.loads((Path(__file__).parent/"scenario.json").read_text())
from stock_swing.research.pf_execution_adapter import ExecutionArm,ResearchPFFilter
from stock_swing.research.comparison_book import Instrument
from datetime import timedelta
NOW=datetime(2026,11,2,14,35,tzinfo=timezone.utc)
price=scenario.get('price',130)
bridge=ExecutionArm(scenario.get('arm','PF-A'),[Instrument('NVDA','stock','fixture',1)],slippage_bps=5)
def bridge_quote(at,px,eid):
    end=at.replace(second=0,microsecond=0)
    return dict(kind='quote',event_id=eid,at=at.isoformat(),quote=dict(symbol='NVDA',bid=px,ask=px,executed_at=at.isoformat(),available_at=at.isoformat(),basis='raw'),prior_bar=dict(symbol='NVDA',start=(end-timedelta(minutes=1)).isoformat(),end=end.isoformat(),available_at=end.isoformat(),volume=1000000,basis='raw'))
if scenario.get('owned'):
    at=NOW-timedelta(days=3)
    # Oct30 is still DST: 14:35 UTC is a regular-session clock.
    bridge.apply(dict(kind='submit',event_id='opening',at=at.isoformat(),order=dict(id='opening',symbol='NVDA',qty=10,side='buy',type='market',time_in_force='gtc',max_fill_price=101),quotes={'NVDA':dict(price=100,as_of=at.isoformat())}))
    bridge.apply(bridge_quote(at+timedelta(seconds=1),100,'opening-fill'))
bridge.apply(bridge_quote(NOW,price,'initial-mark'))
bridge_before=bridge.dumps()

def transport(request):
    calls.append([request.method,request.url.path])
    if request.url.path.endswith('/account'):
        snap=bridge.snapshot();return httpx.Response(200,json=dict(id='account-fixture',status='ACTIVE',equity='bad' if scenario.get('bad_account') or not snap['valuation_qualified'] else str(snap['equity']),cash=str(snap['available_cash']),buying_power=str(snap['available_cash'])))
    if request.url.path.endswith('/positions'):return httpx.Response(200,json=bridge.positions())
    if request.url.path.endswith('/bars'):
        bars=[dict(t=(NOW-timedelta(minutes=5*(20-i))).isoformat(),o=129,h=131,l=128,c=130,v=2000000) for i in range(20)]
        return httpx.Response(200,json=dict(bars=bars))
    if 'quotes' in request.url.path:return httpx.Response(200,json={'quote':{'bp':price,'ap':price,'t':NOW.isoformat()}})
    if 'orders' in request.url.path:
        if request.method=='POST':
            body=json.loads(request.content);posts.append(body)
            native=dict(id='fixture-order-'+str(len(posts)),symbol=body['symbol'],qty=int(body['qty']),side=body['side'],type=body['type'],time_in_force=body['time_in_force'],max_fill_price=price+1)
            if body.get('limit_price') is not None:native['limit_price']=float(body['limit_price'])
            bridge.apply(dict(kind='submit',event_id='native:'+native['id'],at=NOW.isoformat(),order=native,quotes={'NVDA':dict(price=price,as_of=NOW.isoformat())}))
            if scenario.get('submit_timeout'):
                raise httpx.ReadTimeout('fixture response lost after acceptance', request=request)
            return httpx.Response(200,json=dict(id='fixture-order-'+str(len(posts)),status='new',filled_qty='0',created_at='2026-10-28T15:00:00Z',**body))
        if request.url.path.endswith('/orders:by_client_order_id'):
            if scenario.get('lookup_found') and posts:
                body=next((b for b in posts if b.get('client_order_id')==request.url.params.get('client_order_id')),None)
                if body:return httpx.Response(200,json=dict(id='fixture-order-'+str(posts.index(body)+1),status='new',filled_qty='0',**body))
            return httpx.Response(404,json={})
        if request.url.path.endswith('/orders'):return httpx.Response(200,json=scenario.get('orders',[]))
        return httpx.Response(200,json=dict(id=request.url.path.rsplit('/',1)[-1],symbol='NVDA',side='buy',qty='1',status='new',filled_qty='0',created_at='2026-10-28T15:00:00Z'))
    raise AssertionError('unexpected fixture request '+request.url.path)
original=httpx.Client
httpx.Client=lambda **kw:original(transport=httpx.MockTransport(transport),**kw)
def massive_http(self,method,url,**kw):
    from urllib.parse import urlsplit
    path=urlsplit(url).path;calls.append([method,path])
    if '/aggs/' in path:
        rows=[]
        for i in range(20):
            dt=NOW-timedelta(days=20-i)
            close=price*(.7+.3*i/19)
            rows.append(dict(t=int(dt.timestamp()*1000),o=close-1,h=close+2,l=close-2,c=close,v=scenario.get('volume',2000000),vw=close,n=10))
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
        fixed=NOW
        return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
paper_demo.datetime=FixtureClock
# External clock boundary only: native policies and precedence are untouched.
for name,module in list(sys.modules.items()):
    if name.startswith('stock_swing.') and getattr(module,'datetime',None) is datetime:
        module.datetime=FixtureClock
filters=[]
if scenario.get('wrapped',True):
    def pf_factory(config):
        f=ResearchPFFilter(config,scenario.get('arm','PF-A'));filters.append(f);return f
    paper_demo.EntryFilterEngine=pf_factory
import stock_swing.feature_engine.earnings_event_feature as earnings_clock
earnings_clock.datetime=FixtureClock
# Financial fixture is produced by the real tracker, then dated before the scenario.
if scenario.get('pf_seed'):
    from stock_swing.tracking.pnl_tracker import PnLTracker
    t=PnLTracker(root)
    for i in range(5):
        t.record_submission(symbol='NVDA',strategy_id='breakout_momentum_v1',side='buy',qty=1,price=100,broker_order_id='seed-buy-'+str(i),decision_id='seed-decision-'+str(i),account_id='account-fixture')
        t.record_exit(symbol='NVDA',exit_price=90,broker_order_id='seed-sell-'+str(i))
    statepath=root/'data/tracking/pnl_state.json';seed=json.loads(statepath.read_text())
    for row in seed['trades']:
        row.update(entry_time='2026-10-20T15:00:00+00:00',exit_time='2026-10-21T15:00:00+00:00',holding_days=1)
    statepath.write_text(json.dumps(seed))
financial_before=json.loads((root/'data/tracking/pnl_state.json').read_text())['trades']
legacy_before=(root/'data/analysis/entry_restriction_review_v1.json').read_bytes()
buf=io.StringIO()
with contextlib.redirect_stdout(buf),contextlib.redirect_stderr(buf):
    sys.argv=['paper_demo','--symbols',scenario.get('symbols','NVDA'),'--min-momentum','0.05','--min-signal-strength','0.6','--cron-summary-json']

    if scenario.get('dry_run'):sys.argv.append('--dry-run')
    if scenario.get('capture'):sys.argv.append('--capture-provider-contracts')
    if scenario.get('pf_capture'):sys.argv.append('--capture-pf-history')
    if scenario.get('config_capture'):sys.argv.append('--capture-config-instances')
    try:result=paper_demo.main()
    except BaseException as exc:print(type(exc).__name__,str(exc));result=99
indices=list((root/'data/audits/measurement_inputs/run_manifests').glob('*.json'))
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

output['config_events']=[json.loads(line) for p in (root/'reports/config_instances').glob('*.jsonl') for line in p.read_text().splitlines()]
output['posts']=posts
output['orders']={k:summary.get('decision_funnel',{}).get(k) for k in ('submitted','rejected','unknown','held')}
output['alerts']=summary.get('alerts',[])
output['effective_config']=summary.get('effective_config',[])
output['journal']=[p.read_text() for p in (root/'data/tracking/submission_intents').glob('*.jsonl')]
output['preflight']=[json.loads(p.read_text()) for p in (root/'reports/order_preflight').glob('*.json')]
output['submission_lines']=[line.strip() for line in text_output.splitlines() if 'Submitting' in line or 'SKIP BUY' in line]
output['full_stdout']=text_output
import gzip,hashlib
output['decisions']=[json.loads(p.read_text()) for p in (root/'data/decisions').rglob('*.json')]
output['snapshots']={str(p.relative_to(root)):dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),payload=json.loads(gzip.decompress(p.read_bytes()))) for p in (root/'data/feature_snapshots').rglob('*.json.gz')} if (root/'data/feature_snapshots').is_dir() else {}
pending=root/'data/tracking/pending_exit_reasons.json'
output['pending']=json.loads(pending.read_text()) if pending.exists() else {}
events=root/'data/tracking/trade_events.jsonl'
output['events']=[json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []

output['legacy_bytes_unchanged']=(root/'data/analysis/entry_restriction_review_v1.json').read_bytes()==legacy_before
output['financial_trades_unchanged']=json.loads((root/'data/tracking/pnl_state.json').read_text())['trades']==financial_before
output['pf_receipts']=[str(p.relative_to(root)) for p in (root/'data/audits/pf_history').glob('*.json')] if (root/'data/audits/pf_history').is_dir() else []
if output['pf_receipts']:
    from stock_swing.risk.pf_history_receipt import load_pf_history,replay_pf_history
    ref=output['funnel']['pf_history_receipt']
    doc=load_pf_history(root,ref)
    for decision in output['decisions']:
        if 'pf_history_receipt' in decision['evidence']:
            assert decision['run_id']==ref['run_id']
            load_pf_history(root,decision['evidence']['pf_history_receipt'],decision_id=decision['decision_id'])
    output['pf_replay']=replay_pf_history(doc)
bridge_result=bridge.apply(bridge_quote(NOW+timedelta(seconds=1),price,'after-intent'))
output['research_filter_receipts']=[r for f in filters for r in f.receipts]
output['bridge_snapshot']=bridge.book.snapshot()
output['bridge_legs']=bridge.legs
output['bridge_after_intent']=bridge_result
output['bridge_serialized']=bridge.dumps()
output['native_config_untouched']=True
print(json.dumps(output,sort_keys=True,indent=2))
