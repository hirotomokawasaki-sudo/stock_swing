"""Execute actual scripts in copies, substituting external HTTP and human input only."""
from pathlib import Path
import builtins,contextlib,io,json,runpy,sys
import httpx
root=Path(__file__).resolve().parent
assert not (root/'.env').exists()
s=json.loads((root/'scenario.json').read_text());calls=[];posts=[];outcomes=[]
def transport(req):
 calls.append([req.method,req.url.path])
 if req.method=='GET' and req.url.path.endswith('/positions'):
  return httpx.Response(s.get('get_status',200),json=s.get('positions',[]))
 if req.method=='POST' and req.url.path.endswith('/orders'):
  body=json.loads(req.content);posts.append(body)
  if s.get('ack_lost'):raise httpx.ReadTimeout('fixture ACK lost after acceptance',request=req)
  if s.get('reject'):return httpx.Response(400,json={'message':'fixture explicit rejection'})
  return httpx.Response(200,json=dict(id='fixture-'+str(len(posts)),status='new',**body))
 raise AssertionError('unexpected path '+req.url.path)
original=httpx.Client
httpx.Client=lambda **kw:original(transport=httpx.MockTransport(transport),**kw)
builtins.input=lambda prompt='':s.get('confirm','yes')
from stock_swing.sources import broker_client
assert Path(broker_client.__file__).resolve().is_relative_to((root/'src').resolve())
for iteration in range(s.get('repeat',1)):
 buf=io.StringIO();start=len(posts)
 with contextlib.redirect_stdout(buf),contextlib.redirect_stderr(buf):
  try:
   runpy.run_path(str(root/'scripts'/s['script']),run_name='__main__');error=None
  except BaseException as exc:error=type(exc).__name__
 outcomes.append(dict(error=error,posts_this_run=len(posts)-start,printed_complete='Emergency sell complete' in buf.getvalue(),stdout=buf.getvalue()))
print(json.dumps(dict(http_calls=calls,posts=posts,outcomes=outcomes,origin_is_copy=True),sort_keys=True,indent=2))
