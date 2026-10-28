"""Acceptance CMP-C01/K15, regression 2026-10-28 HEAD8909e79 ACK-lost rerun.
External HTTP/human input only replaced; actual scripts and durable helper run.
"""
from pathlib import Path
import contextlib,io,json,runpy,shutil
import httpx,pytest

@pytest.mark.parametrize('script,symbols,side',[('emergency_sell.py',['NOW','IBM'],'sell'),('close_hpe_short.py',['HPE'],'buy')])
def test_ac_ack_loss_restart_never_resends_same_reduction(monkeypatch,tmp_path,script,symbols,side):
 root=Path(__file__).resolve().parents[2]
 (tmp_path/'scripts').mkdir();shutil.copy2(root/'scripts'/script,tmp_path/'scripts'/script)
 (tmp_path/'config/runtime').mkdir(parents=True);(tmp_path/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
 posts=[]
 def transport(req):
  if req.url.path.endswith('/account'):return httpx.Response(200,json=dict(id='fixture-account',status='ACTIVE'))
  if req.url.path.endswith('/positions'):return httpx.Response(200,json=[dict(symbol=s,qty='-13' if side=='buy' else '3') for s in symbols])
  if req.url.path.endswith('/orders:by_client_order_id'):return httpx.Response(404,json={})
  if req.method=='GET' and req.url.path.endswith('/orders'):return httpx.Response(200,json=[])
  if req.method=='POST':
   posts.append(json.loads(req.content));raise httpx.ReadTimeout('fixture accepted then ACK lost',request=req)
  raise AssertionError(req.url.path)
 original=httpx.Client;monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(transport),**kw))
 for k,v in dict(BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture',BROKER_BASE_URL='https://paper-fixture.invalid').items():monkeypatch.setenv(k,v)
 monkeypatch.setattr('builtins.input',lambda prompt='':'yes')
 codes=[];stdout=io.StringIO()
 for n in range(2):
  with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stdout):
   try:runpy.run_path(str(tmp_path/'scripts'/script),run_name='__main__');code=0
   except SystemExit as exc:code=exc.code
   except Exception:code=99
  codes.append(code)
 assert len(posts)==len(symbols),'same stable reduction intent must never resend on next process/run'
 assert all(p.get('client_order_id') for p in posts),'persisted stable broker IDs required'
 assert all(code!=0 for code in codes),'unknown or held must not exit successfully'
 assert 'Emergency sell complete' not in stdout.getvalue(),'failure cannot print complete'
