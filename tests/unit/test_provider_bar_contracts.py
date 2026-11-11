"""Regression 2026-10-23 Massive 5Min -> daily, current base fa386d1.
Acceptance: same interval on every fallback, saved provider/price version lineage.
Only external HTTP/SDK transport is substituted; dispatch/decoding/storage are real.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys
from urllib.parse import urlparse

import httpx
import pytest
import urllib3
from stock_swing.sources.massive_client import MassiveClient
from stock_swing.sources.hybrid_data_fetcher import HybridDataFetcher
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.experiments.decision_input_capture import DecisionInputRecorder, load_input_run, load_decision_input

EPOCH = 1792526400000
BAR = dict(t=EPOCH,o=100,h=102,l=99,c=101,v=1000,vw=100.5,n=42)

def setup_fetcher(tmp_path, monkeypatch, *, enabled=True, massive_pages=None, yahoo=True):
    calls=[]
    pages=iter(massive_pages if massive_pages is not None else [dict(results=[BAR], adjusted=True,request_id='fixture-request')])
    def massive_http(self, method, url, **kw):
        calls.append(('massive',url,kw.get('fields',{})))
        page=next(pages)
        if isinstance(page,Exception): raise page
        return urllib3.response.HTTPResponse(body=json.dumps(page).encode(),status=200,preload_content=True)
    monkeypatch.setattr(urllib3.PoolManager,'request',massive_http)
    class YahooResponse:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self):
            return json.dumps(dict(chart=dict(result=[dict(timestamp=[EPOCH//1000] if yahoo else [],indicators=dict(quote=[dict(open=[100],high=[102],low=[99],close=[101],volume=[1000])]))]))).encode()
    def yahoo_http(*a,**kw):
        calls.append(('yahoo','chart',{}));return YahooResponse()
    monkeypatch.setattr('urllib.request.urlopen',yahoo_http)
    def broker_http(self,url,**kw):
        calls.append(('broker',url,kw.get('params',{})))
        b=dict(BAR,t='2026-10-20T20:00:00Z')
        return httpx.Response(200,content=json.dumps(dict(bars=[b])).encode(),headers={'x-request-id':'broker-request'})
    monkeypatch.setattr(httpx.Client,'get',broker_http)
    recorder=DecisionInputRecorder(tmp_path,enabled=enabled,run_id='provider-test')
    broker=BrokerClient(api_key='fixture',api_secret='fixture',paper_mode=True)
    broker.measurement_recorder=recorder
    fetcher=HybridDataFetcher(broker_client=broker,etf_symbols=set(),massive_api_key='fixture',measurement_recorder=recorder)
    return fetcher,recorder,calls

def seal(recorder):
    recorder.observe('run_end',dict(exit_code=0,observations_before_end=recorder.committed,capture_failures=recorder.failures))
    return recorder.seal()

@pytest.mark.parametrize('frame,timespan,mult,event',[('5Min','minute',5,'bar_5min'),('1Min','minute',1,'bar_1min'),('15min','minute',15,'bar_15min'),('1Hour','minute',60,'bar_1hour'),('daily','day',1,'bar_daily'),('1Day','day',1,'bar_daily')])
def test_ac_massive_dispatch_preserves_requested_interval(tmp_path,monkeypatch,frame,timespan,mult,event):
    f,r,calls=setup_fetcher(tmp_path,monkeypatch)
    records,source=f.fetch_bars('NVDA',timeframe=frame,limit=3)
    assert source=='massive',calls
    assert len(records)==1 and records[0].event_type==event
    assert f'/range/{mult}/{timespan}/' in calls[0][1]
    c=records[0].payload['bar_contract']
    assert c['response_adjusted'] is True and c['response_request_id']=='fixture-request'
    assert c['requested_adjustment'] is None and c['provider_final'] is None
    assert c['provider_first_publication_at'] is None and c['research_qualified'] is False
    run=load_input_run(tmp_path,seal(r))
    assert run['manifest']['full_replay_ready'] is False
    obs=load_decision_input(tmp_path,c['observation_ref'])
    assert obs['payload']['contract']['version_sha256']==c['version_sha256']
    assert obs['payload']['response']['results'][0]['c']==records[0].payload['close']

@pytest.mark.parametrize('enabled',[True,False])
def test_ac_minute_fallback_never_visits_yahoo_or_daily(tmp_path,monkeypatch,enabled):
    f,r,calls=setup_fetcher(tmp_path,monkeypatch,enabled=enabled,massive_pages=[dict(results=[])])
    records,source=f.fetch_bars('NVDA','5Min',3)
    assert source=='broker' and records[0].event_type=='bar_5min'
    assert [c[0] for c in calls]==['massive','broker']
    assert calls[-1][2]['timeframe']=='5Min'
    if enabled:
        c=records[0].payload['bar_contract']
        assert c['requested_feed']=='iex' and c['requested_adjustment']=='raw'
        assert c['response_adjusted'] is None and c['response_request_id']=='broker-request'
    else:
        assert not (tmp_path/'data/audits/measurement_inputs').exists()
        assert 'bar_contract' not in records[0].payload

def test_ac_yahoo_contract_retains_unknown_basis(tmp_path,monkeypatch):
    f,r,calls=setup_fetcher(tmp_path,monkeypatch,massive_pages=[dict(results=[])])
    records,source=f.fetch_bars('NVDA','1Day',3)
    c=records[0].payload['bar_contract']
    assert source=='yahoo' and c['requested_interval']=='1Day'
    assert c['requested_adjustment'] is None and c['response_adjusted'] is None
    assert c['response_request_id'] is None and len(c['raw_sha256'])==64
    assert [v[0] for v in calls]==['massive','yahoo']

def test_ac_daily_alpaca_fallback_retains_feed_and_raw_basis(tmp_path,monkeypatch):
    f,r,calls=setup_fetcher(tmp_path,monkeypatch,massive_pages=[dict(results=[])],yahoo=False)
    records,source=f.fetch_bars('NVDA','1Day',3)
    assert source=='broker' and records[0].payload['bar_contract']['requested_interval']=='1Day'
    assert [v[0] for v in calls]==['massive','yahoo','broker']

@pytest.mark.parametrize('frame',['0Min','60Min','5Day','oops','',None])
def test_ac_unsupported_interval_refuses_before_http(tmp_path,monkeypatch,frame):
    f,r,calls=setup_fetcher(tmp_path,monkeypatch)
    with pytest.raises(ValueError): f.fetch_bars('NVDA',frame,3)
    assert calls==[]

def test_ac_massive_pages_keep_distinct_response_versions(tmp_path,monkeypatch):
    pages=[dict(results=[BAR],adjusted=True,request_id='page-one',next_url='https://api.massive.com/v2/aggs/ticker/NVDA/range/5/minute/page?cursor=two'),dict(results=[dict(BAR,t=EPOCH+300000,c=102)],adjusted=False,request_id='page-two')]
    f,r,calls=setup_fetcher(tmp_path,monkeypatch,massive_pages=pages)
    records,source=f.fetch_bars('NVDA','5Min',3)
    assert source=='massive' and len(records)==2 and len(calls)==2
    contracts=[v.payload['bar_contract'] for v in records]
    assert [v['response_request_id'] for v in contracts]==['page-one','page-two']
    assert contracts[0]['raw_sha256']!=contracts[1]['raw_sha256']
    assert contracts[0]['version_sha256']!=contracts[1]['version_sha256']
    assert [v['response_adjusted'] for v in contracts]==[True,False]

@pytest.mark.parametrize('body',[b'{',b'[]',b'{"results":null}',b'{"results":[{"t":null}]}'])
def test_ac_bad_massive_response_falls_back_same_interval(tmp_path,monkeypatch,body):
    f,r,calls=setup_fetcher(tmp_path,monkeypatch)
    def bad(*args,**kw):return urllib3.response.HTTPResponse(body=body,status=200,preload_content=True)
    monkeypatch.setattr(urllib3.PoolManager,'request',bad)
    records,source=f.fetch_bars('NVDA','5Min',3)
    assert source=='broker' and records[0].event_type=='bar_5min'
    assert not any(v[0]=='yahoo' for v in calls)

@pytest.mark.parametrize('adjusted',[True,False,None])
def test_ac_response_flags_are_not_defaults(tmp_path,monkeypatch,adjusted):
    page=dict(results=[BAR],request_id='flag')
    if adjusted is not None:page['adjusted']=adjusted
    f,r,calls=setup_fetcher(tmp_path,monkeypatch,massive_pages=[page])
    records,_=f.fetch_bars('NVDA','1Day',3)
    assert records[0].payload['bar_contract']['response_adjusted'] is adjusted

def test_ac_recorder_failure_does_not_turn_capture_into_success(tmp_path,monkeypatch):
    f,r,calls=setup_fetcher(tmp_path,monkeypatch)
    folder=tmp_path/'data/audits/measurement_inputs';folder.parent.mkdir(parents=True);folder.write_text('blocked')
    records,source=f.fetch_bars('NVDA','5Min',3)
    assert source=='massive' and r.failures>0
    assert records[0].payload['bar_contract']['observation_ref'] is None

@pytest.mark.parametrize('tz',['UTC','Asia/Tokyo'])
def test_ac_epoch_is_utc_independent_of_host(tmp_path,monkeypatch,tz):
    script="from stock_swing.sources.massive_client import MassiveClient;from types import SimpleNamespace;c=object.__new__(MassiveClient);c.client=SimpleNamespace(list_aggs=lambda **kw:[SimpleNamespace(timestamp=1792526400000,open=1,high=2,low=1,close=2,volume=1)]);print(c.fetch_daily_bars('NVDA','2026-10-20','2026-10-21')[0].timestamp.isoformat())"
    env=dict(os.environ,TZ=tz,PYTHONPATH=str(Path(__file__).resolve().parents[2]/'src'),PYTHONDONTWRITEBYTECODE='1')
    out=subprocess.check_output([sys.executable,'-B','-c',script],env=env,text=True)
    assert out.strip()=='2026-10-20T20:00:00+00:00'

@pytest.mark.parametrize('frame,event,path_piece',[('5Min','bar_5min','/5/minute/'),('15Min','bar_15min','/15/minute/'),('1Hour','bar_1hour','/60/minute/'),('1Day','bar_daily','/1/day/')])
def test_regression_legacy_constructor_routes_requested_interval(tmp_path,monkeypatch,frame,event,path_piece):
    """Same real-transport test works on baseline; no new recorder API needed."""
    seen=[]
    def response(self,method,url,**kw):
        seen.append(url)
        return urllib3.response.HTTPResponse(body=json.dumps(dict(results=[BAR])).encode(),status=200,preload_content=True)
    monkeypatch.setattr(urllib3.PoolManager,'request',response)
    broker=BrokerClient(api_key='fixture',api_secret='fixture',paper_mode=True)
    f=HybridDataFetcher(broker_client=broker,etf_symbols=set(),massive_api_key='fixture')
    records,source=f.fetch_bars('NVDA',frame,3)
    assert source=='massive' and records[0].event_type==event
    assert len(seen)==1 and path_piece in seen[0]

@pytest.mark.parametrize('link',['missing','tampered'])
def test_ac_saved_response_dependencies_are_required(tmp_path,monkeypatch,link):
    f,r,calls=setup_fetcher(tmp_path,monkeypatch)
    records,_=f.fetch_bars('NVDA','1Day',3)
    ref=seal(r);receipt=load_decision_input(tmp_path,records[0].payload['bar_contract']['observation_ref'])
    blob=tmp_path/'data/audits/measurement_inputs/blobs'/receipt['manifest']['payload_sha256']
    if link=='missing':blob.unlink()
    else:blob.write_bytes(blob.read_bytes()+b' ')
    from stock_swing.experiments.measurement_capture import CaptureError
    with pytest.raises(CaptureError):load_input_run(tmp_path,ref)

@pytest.mark.parametrize('next_url',['https://evil.invalid/v2/aggs/ticker/NVDA/range/5/minute/x','https://api.massive.com/v2/aggs/ticker/NVDA/range/5/minute/x'])
def test_ac_unsafe_or_cyclic_pages_refuse_without_extra_provider_fetch(tmp_path,monkeypatch,next_url):
    page=dict(results=[BAR],next_url=next_url)
    f,r,calls=setup_fetcher(tmp_path,monkeypatch,massive_pages=[page,page])
    records,source=f.fetch_bars('NVDA','5Min',3)
    assert source=='broker' and records[0].event_type=='bar_5min'
    assert sum(c[0]=='massive' for c in calls)==(1 if 'evil' in next_url else 2)
    assert not any(c[0]=='yahoo' for c in calls)


def test_ac_secret_response_is_not_persisted(tmp_path,monkeypatch):
    page=dict(results=[BAR],apiKey='fixture-private-value')
    f,r,calls=setup_fetcher(tmp_path,monkeypatch,massive_pages=[page])
    records,source=f.fetch_bars('NVDA','5Min',3)
    assert source=='massive' and r.failures==1
    assert records[0].payload['bar_contract']['observation_ref'] is None
    assert all(b'fixture-private-value' not in p.read_bytes() for p in tmp_path.rglob('*') if p.is_file())


def test_ac_weekly_interval_bypasses_daily_providers(tmp_path,monkeypatch):
    f,r,calls=setup_fetcher(tmp_path,monkeypatch)
    records,source=f.fetch_bars('NVDA','1Week',3)
    assert source=='broker' and records[0].event_type=='bar_1week'
    assert [c[0] for c in calls]==['broker']
