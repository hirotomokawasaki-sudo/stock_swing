"""Actual scripts; fresh interpreter on every invocation, external HTTP/input only."""
from pathlib import Path
import builtins,contextlib,io,json,os,runpy,sys
import httpx
root=Path(__file__).resolve().parent;s=json.loads((root/'scenario.json').read_text());run_number=int(sys.argv[1]);calls=[];posts=[];counts={'positions':0,'orders':0}
assert not (root/'.env').exists()
store=root/'fixture_broker.json';state=json.loads(store.read_text()) if store.exists() else dict(accepted={},posts=[])
def save():store.write_text(json.dumps(state,sort_keys=True))
def transport(req):
 calls.append([req.method,req.url.path])
 if req.url.path.endswith('/account'):return httpx.Response(200,json=s.get('account',dict(id='fixture-account',status='ACTIVE')))
 if req.url.path.endswith('/positions'):
  counts['positions']+=1;rows=s.get('positions_after',s.get('positions',[])) if counts['positions']>=2 else s.get('positions',[])
  return httpx.Response(s.get('get_status',200),json=rows)
 if req.method=='GET' and req.url.path.endswith('/orders'):
  counts['orders']+=1;rows=s.get('orders_after',s.get('orders',[])) if counts['orders']>=2 else s.get('orders',[])
  return httpx.Response(200,json=rows)
 if req.url.path.endswith('/orders:by_client_order_id'):
  key=req.url.params.get('client_order_id');row=state['accepted'].get(key)
  if s.get('lookup')=='missing' or not row:return httpx.Response(404,json={})
  if s.get('lookup')=='mismatch':row=dict(row,client_order_id='incorrect')
  return httpx.Response(200,json=row)
 if req.method=='POST' and req.url.path.endswith('/orders'):
  body=json.loads(req.content);posts.append(body);state['posts'].append(body)
  status=s.get('post_status',200)
  if status>=400:save();return httpx.Response(status,json={'message':'fixture rejection'})
  row=dict(body,id='fixture-'+str(len(state['posts'])),status=s.get('response_status','new'),filled_qty='0')
  state['accepted'][body.get('client_order_id','legacy-'+str(len(state['posts'])))] =row;save()
  if s.get('die_after_accept') and run_number==0:os._exit(73)
  if s.get('hold_after_accept') and run_number==0:
   os.write(1,b'ACCEPTED_WAITING\n');sys.stdin.readline()
  if s.get('ack_lost'):raise httpx.ReadTimeout('fixture accepted then lost ACK',request=req)
  if s.get('malformed_ack'):row=dict(row,qty='999')
  return httpx.Response(200,json=row)
 raise AssertionError(req.url.path)
original=httpx.Client;httpx.Client=lambda **kw:original(transport=httpx.MockTransport(transport),**kw)
builtins.input=lambda prompt='':s.get('confirm','yes')
from stock_swing.sources import broker_client
assert Path(broker_client.__file__).resolve().is_relative_to((root/'src').resolve())
if (root/'src/stock_swing/execution/reduction_orders.py').exists():
 import stock_swing.execution.reduction_orders as helper
 assert Path(helper.__file__).resolve().is_relative_to((root/'src').resolve())
# Fault injection is only the external fsync boundary, never guard/parser logic.
if s.get('fsync_failure'):
 fsync=os.fsync
 def controlled(fd):
  if s['fsync_failure']=='before' or state['posts']:raise OSError('fixture fsync failure')
  fsync(fd)
 os.fsync=controlled
buf=io.StringIO();error=None
with contextlib.redirect_stdout(buf),contextlib.redirect_stderr(buf):
 try:runpy.run_path(str(root/'scripts'/s['script']),run_name='__main__');code=0
 except SystemExit as exc:code=exc.code
 except BaseException as exc:error=type(exc).__name__;code=99
summary=None
for line in buf.getvalue().splitlines():
 if line.startswith('REDUCTION_SUMMARY_JSON='):summary=json.loads(line.split('=',1)[1])
print(json.dumps(dict(exit_code=code,error=error,summary=summary,posts=posts,http_calls=calls,stdout=buf.getvalue(),origin_is_copy=True),sort_keys=True))
