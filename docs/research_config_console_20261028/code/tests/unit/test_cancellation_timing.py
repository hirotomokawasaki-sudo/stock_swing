"""Regression 2026-10-28/8909e79: fixed UTC windows select valid RTH orders."""
from datetime import datetime, timezone
import json
import httpx
import pytest
from stock_swing.cli import reconcile_orders as module
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.exit_reason_store import write_exit_reason, read_exit_reason

# Explicit ET instants, not derived from the candidate's selection helper.
CASES = [
 ('buy','2026-07-08T15:45:00-04:00','2026-07-08T15:00:00-04:00',False),
 ('buy','2026-01-08T15:45:00-05:00','2026-01-08T14:00:00-05:00',False),
 ('buy','2026-01-08T09:15:00-05:00','2026-01-08T08:00:00-05:00',False),
 ('buy','2026-07-08T09:29:59-04:00','2026-07-07T10:00:00-04:00',False),
 ('buy','2026-07-08T09:30:00-04:00','2026-07-07T10:00:00-04:00',True),
 ('buy','2026-01-08T09:30:00-05:00','2026-01-07T10:00:00-05:00',True),
 ('buy','2026-07-11T12:00:00-04:00','2026-07-10T10:00:00-04:00',False),
 ('buy','2026-07-13T09:29:59-04:00','2026-07-10T10:00:00-04:00',False),
 ('buy','2026-07-13T09:30:00-04:00','2026-07-10T10:00:00-04:00',True),
 ('buy','2026-09-07T12:00:00-04:00','2026-09-04T10:00:00-04:00',False),
 ('buy','2026-09-08T09:30:00-04:00','2026-09-04T10:00:00-04:00',True),
 ('buy','2026-03-09T09:29:59-04:00','2026-03-06T10:00:00-05:00',False),
 ('buy','2026-03-09T09:30:00-04:00','2026-03-06T10:00:00-05:00',True),
 ('buy','2026-11-02T09:29:59-05:00','2026-10-30T10:00:00-04:00',False),
 ('buy','2026-11-02T09:30:00-05:00','2026-10-30T10:00:00-04:00',True),
 ('buy','2026-07-08T16:29:59-04:00','2026-07-08T16:00:00-04:00',False),
 ('buy','2026-07-08T16:30:00-04:00','2026-07-08T16:00:00-04:00',True),
 ('buy','2026-01-08T16:30:00-05:00','2026-01-08T16:00:00-05:00',True),
 ('buy','2026-07-08T21:00:00-04:00','2026-07-08T20:00:00-04:00',False),
 ('buy','2026-07-11T18:00:00-04:00','2026-07-11T16:00:00-04:00',False),
 ('buy','2026-11-27T13:30:00-05:00','2026-11-27T13:00:00-05:00',True),
 ('buy','2026-12-24T13:30:00-05:00','2026-12-24T13:00:00-05:00',True),
 ('sell','2026-11-27T13:30:00-05:00','2026-11-27T13:00:00-05:00',True),
 ('sell','2026-07-08T16:15:00-04:00','2026-07-08T15:00:00-04:00',False),
 ('sell','2026-07-11T16:30:00-04:00','2026-07-11T16:00:00-04:00',True),
 ('sell','2026-01-08T16:29:59-05:00','2026-01-08T16:00:00-05:00',False),
 ('sell','2026-01-08T16:30:00-05:00','2026-01-08T16:00:00-05:00',True),
]

def exercise(tmp_path,monkeypatch,side,now,submitted,**changes):
 fixed=datetime.fromisoformat(now)
 class Clock(datetime):
  @classmethod
  def now(cls,tz=None):return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
 monkeypatch.setattr(module,'datetime',Clock);monkeypatch.setattr(module,'project_root',tmp_path)
 (tmp_path/'config/runtime').mkdir(parents=True);(tmp_path/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
 order=dict(id='fixture-order',symbol='AMD',side=side,type='market',time_in_force='day',qty='5',filled_qty='0',status='new',submitted_at=submitted,extended_hours=False)
 order.update(changes)
 calls=[]
 def transport(request):
  calls.append(request.method+' '+request.url.path)
  if request.url.path.endswith('/account'):return httpx.Response(200,json=dict(id='account-fixture',status='ACTIVE'))
  if request.url.path.endswith('/orders'):return httpx.Response(200,json=[order])
  if request.method=='DELETE':return httpx.Response(204)
  if request.url.path.endswith('/fixture-order'):return httpx.Response(200,json=dict(order,status='canceled') if any(x.startswith('DELETE') for x in calls) else order)
  raise AssertionError(str(request.url))
 original=httpx.Client;monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(transport),**kw))
 broker=BrokerClient(api_key='fixture',api_secret='fixture',paper_mode=True)
 write_exit_reason(tmp_path,'fixture-order','AMD','fixture','stop_loss',{'return_pct':-.07})
 result=module.cancel_stale_buy_orders(broker) if side=='buy' else module.cancel_stale_sell_orders(broker,tmp_path)
 return result,calls

@pytest.mark.parametrize('side,now,submitted,expected',CASES+[(s,n,datetime.fromisoformat(t).astimezone(timezone.utc).isoformat(),e) for s,n,t,e in CASES])
def test_ac_real_selector_time_boundaries(tmp_path,monkeypatch,side,now,submitted,expected):
 result,calls=exercise(tmp_path,monkeypatch,side,now,submitted)
 assert sum(c.startswith('DELETE') for c in calls)==int(expected),(side,now,submitted,result,calls)
 assert not any(c.startswith('POST') for c in calls),calls
 assert (read_exit_reason(tmp_path,'fixture-order') is None)==expected,result

@pytest.mark.parametrize('submitted',['2026-07-08T16:00:00','broken','2026-07-09T16:00:00Z'])
@pytest.mark.parametrize('side',['buy','sell'])
def test_ac_unqualified_time_is_held_not_delete_or_crash(tmp_path,monkeypatch,submitted,side):
 result,calls=exercise(tmp_path,monkeypatch,side,'2026-07-08T17:00:00Z',submitted)
 assert not any(c.startswith('DELETE') for c in calls),calls
 assert any(r.get('state')=='held' for r in result),result

@pytest.mark.parametrize('zone',['UTC','Asia/Tokyo','America/Los_Angeles'])
def test_ac_offset_equivalent_and_host_zone(tmp_path,monkeypatch,zone):
 import os,time
 prior=os.environ.get('TZ');os.environ['TZ']=zone;time.tzset()
 try:
  result,calls=exercise(tmp_path,monkeypatch,'buy','2026-01-08T21:30:00Z','2026-01-09T06:00:00+09:00')
  assert sum(c.startswith('DELETE') for c in calls)==1,(result,calls)
 finally:
  if prior is None:os.environ.pop('TZ',None)
  else:os.environ['TZ']=prior
  time.tzset()

@pytest.mark.parametrize('side',['buy','sell'])
@pytest.mark.parametrize('now,submitted',[
 ('2029-01-08T17:00:00Z','2029-01-08T16:00:00Z'),
 ('2026-01-01T17:00:00Z','2025-12-31T20:00:00Z')])
def test_ac_unsupported_calendar_is_explicitly_held(tmp_path,monkeypatch,side,now,submitted):
 result,calls=exercise(tmp_path,monkeypatch,side,now,submitted)
 assert not any(c.startswith('DELETE') for c in calls),calls
 assert any(x.get('state')=='held' for x in result),result

@pytest.mark.parametrize('side',['buy','sell'])
def test_ac_partial_fill_selection_does_not_expand(tmp_path,monkeypatch,side):
 result,calls=exercise(tmp_path,monkeypatch,side,'2026-07-08T21:00:00Z','2026-07-08T20:00:00Z',filled_qty='1')
 assert not any(c.startswith('DELETE') for c in calls),calls

def test_ac_extended_hours_order_is_not_after_hours_candidate(tmp_path,monkeypatch):
 result,calls=exercise(tmp_path,monkeypatch,'buy','2026-07-08T21:00:00Z','2026-07-08T20:00:00Z',extended_hours=True)
 assert not any(c.startswith('DELETE') for c in calls),calls
