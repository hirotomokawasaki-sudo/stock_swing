"""PF-AB-EXEC-20261029-v1 technical fixtures, never historical profit trials."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
from types import SimpleNamespace

import pytest

from stock_swing.research.pf_execution_adapter import ExecutionArm,ResearchPFFilter,stamp
from stock_swing.research.comparison_book import Instrument
from stock_swing.risk.entry_filter import EntryFilterConfig,EntryFilterEngine

T='2026-11-02T14:35:00+00:00'
def time(n=0):return (stamp(T)+timedelta(seconds=n)).isoformat()
def arm(name='PF-A',cash=1_000_000):return ExecutionArm(name,[Instrument('NVDA','stock','fixture',1)],cash=cash)
def submit(oid='o',qty=10,side='buy',at=T,**kw):
    return dict(kind='submit',event_id='submit:'+oid,at=at,
        order=dict(id=oid,symbol='NVDA',qty=qty,side=side,type='market',time_in_force='gtc',max_fill_price=101,**kw),
        quotes={'NVDA':dict(price=100,as_of=at)})
def quote(n=1,volume=1000,**kw):
    q=dict(symbol='NVDA',bid=99,ask=100,executed_at=time(n),available_at=time(n),basis='raw');q.update(kw)
    end=stamp(q['executed_at']).replace(second=0,microsecond=0)
    return dict(kind='quote',event_id='quote:'+str(n),at=q['available_at'],quote=q,
        prior_bar=dict(symbol='NVDA',start=(end-timedelta(minutes=1)).isoformat(),end=end.isoformat(),available_at=end.isoformat(),volume=volume,basis='raw'))
def bars(volume=1_000_000):return {'NVDA':[SimpleNamespace(payload=dict(volume=volume,high=102,low=98,close=100)) for _ in range(20)]}
def decision(action='buy'):return SimpleNamespace(symbol='NVDA',action=action)

@pytest.mark.parametrize('reduced',[False,True])
@pytest.mark.parametrize('pnl',[-10,10,0])
def test_A_is_native_and_B_only_removes_PF_gates(reduced,pnl):
    cfg=EntryFilterConfig(stock_reduced_mode=reduced)
    seed=[dict(status='closed',symbol='NVDA',pnl=pnl) for _ in range(5)]
    d=[decision()];native=EntryFilterEngine(cfg).filter(d,bars(),seed,set())
    a=ResearchPFFilter(cfg,'PF-A');b=ResearchPFFilter(cfg,'PF-B')
    ar=a.filter(d,bars(),seed,set());br=b.filter(d,bars(),seed,set())
    assert ar.blocked==native.blocked and ar.passed==native.passed,'A must be exact native filter'
    assert br.passed==d and not br.blocked,'B removes only performance gates'
    assert seed==[dict(status='closed',symbol='NVDA',pnl=pnl) for _ in range(5)],'arm history never erased'
    assert b.receipts[-1]['config']['disabled'] is False

@pytest.mark.parametrize('which',['volume','restricted','SELL','DENY','ETF','skip_gate4'])
def test_nonPF_and_skip_semantics_remain(which):
    cfg=EntryFilterConfig(stock_reduced_mode=True,pf_gate_skip_symbols=['NVDA'] if which=='skip_gate4' else [])
    if which=='restricted':cfg.purchase_restricted_symbols=['NVDA']
    ds=[decision('sell' if which=='SELL' else 'deny' if which=='DENY' else 'buy')]
    bs=bars(1 if which=='volume' else 1_000_000)
    seed=[dict(status='closed',symbol='NVDA',pnl=-1) for _ in range(5)]
    for name in ['PF-A','PF-B']:
        result=ResearchPFFilter(cfg,name).filter(ds,bs,seed,{'NVDA'} if which=='ETF' else set())
        if which in {'volume','restricted'}:assert result.blocked,'non-PF blocker must survive treatment'
        elif which in {'SELL','DENY'}:assert result.passed==ds,'risk-reducing/nonbuy path remains'
        elif which=='skip_gate4' and name=='PF-A':assert result.blocked[0][1].startswith('stock_reduced_mode'),'Gate4 does not use Gate3 skip'

def test_disabled_rejected():
    with pytest.raises(ValueError):ResearchPFFilter(EntryFilterConfig(disabled=True),'PF-B')

def test_partial_volume_shared_restart_late_retry_and_cash_oracle():
    x=arm();x.apply(submit(qty=15));first=quote(1,volume=600)
    assert x.apply(first)['fills'][0]['qty']==6
    assert x.apply(quote(2,volume=600))['fills']==[],'same minute quota must not reset'
    y=ExecutionArm.loads(x.dumps());assert y.dumps()==x.dumps(),'restart preserves accepted event source'
    second=quote(61,volume=1000);assert y.apply(second)['fills'][0]['qty']==9
    before=y.dumps();y.apply(first);assert y.dumps()==before,'late identical retry is no-op'
    snap=y.book.snapshot()
    assert snap['cash']==pytest.approx(1_000_000-15*100*1.0005),'independent direct cash arithmetic'
    assert snap['reserved_cash']==0 and sum(v['qty'] for v in snap['lots'].values())==15
    assert snap['bridge_residual']==pytest.approx(0,abs=1e-8)

def test_SELL_partial_FIFO_history_only_known_at_and_independent_arms():
    x=arm();y=arm('PF-B');x.apply(submit());x.apply(quote())
    before=deepcopy(x.history);x.apply(submit('sell',qty=10,side='sell',at=time(2)))
    q=quote(61,volume=400,bid=110,ask=111,available_at=time(63))
    assert x.history==before and not y.history,'intent is not a realized outcome'
    assert x.apply(q)['fills'][0]['qty']==4
    h=x.history[-1]
    assert h['known_at']==time(63) and h['exit_time']==time(61)
    assert h['pnl']==pytest.approx(4*(110*.9995-100*1.0005)),'independent net-PnL arithmetic'
    assert x.positions()[0]['qty']=='6' and y.positions()==[],'no shared holdings'
    assert x.book.snapshot()['cash']==pytest.approx(1_000_000-10*100*1.0005+4*110*.9995)
    with pytest.raises(ValueError):x.apply(submit('oversell',qty=1,side='sell',at=time(64)))

@pytest.mark.parametrize('change',[
    {'bid':True},{'ask':float('inf')},{'bid':101,'ask':100},{'basis':'adjusted'},
    {'available_at':'2026-11-02T14:34:59+00:00'}, {'executed_at':'2026-11-02T14:35:01'},
    {'available_at':'2026-11-02T14:41:01+00:00'},
])
def test_bad_quotes_transactionally_reject(change):
    x=arm();x.apply(submit());before=x.dumps()
    event=quote();event['quote'].update(change);event['at']=event['quote']['available_at']
    with pytest.raises((ValueError,TypeError)):x.apply(event)
    assert x.dumps()==before,'rejection leaves clock, cash, history, quotas and pending unchanged'

@pytest.mark.parametrize('field,value',[
    ('volume',-1),('volume',True),('volume',float('nan')),('basis','adjusted'),
    ('available_at','2026-11-02T14:35:02+00:00'),('end','2026-11-02T14:36:00+00:00'),
    ('start','2026-11-02T14:33:00+00:00'),('symbol','MSFT'),
])
def test_invalid_or_future_volume_is_not_a_fill(field,value):
    x=arm();x.apply(submit());event=quote();event['prior_bar'][field]=value;before=x.dumps()
    with pytest.raises(ValueError):x.apply(event)
    assert x.dumps()==before

def test_missing_volume_and_gap_defer_without_clipped_price():
    x=arm();x.apply(submit());event=quote();event['prior_bar']=None
    assert x.apply(event)['status']=='pending_missing_prior_volume'
    assert not x.legs
    assert not x.apply(quote(2,ask=103))['fills'],'gap beyond reservation not fabricated at bound'
    assert x.orders['o']['status']=='new'

@pytest.mark.parametrize('side,limit,expected', [('buy',100,False),('buy',100.05,True)])
def test_slippage_respects_original_limit(side,limit,expected):
    x=arm();e=submit(side=side);e['order'].update(type='limit',limit_price=limit);x.apply(e)
    assert bool(x.apply(quote())['fills']) is expected

def test_same_clock_and_before_intent_quote_not_fill():
    x=arm();x.apply(submit());assert x.apply(quote(0))['fills']==[]

@pytest.mark.parametrize('tif,expected',[('day','expired'),('gtc','new')])
def test_TIF_and_earlyclose(tif,expected):
    at='2026-11-27T17:59:00+00:00';x=arm();e=submit(at=at);e['order']['time_in_force']=tif;x.apply(e)
    x.apply(dict(kind='clock',event_id='close',at='2026-11-27T18:00:00+00:00'))
    assert x.orders['o']['status']==expected,'13:00 ET early close is honored'

def test_rejections_cancel_and_no_silent_resizing():
    x=arm(cash=1000);before=x.dumps()
    with pytest.raises(ValueError):x.apply(submit(qty=100))
    assert x.dumps()==before,'native qty not silently clipped by accounting layer'
    x.apply(submit(qty=5));x.apply(dict(kind='cancel',event_id='cancel',at=time(1),order_id='o'))
    assert x.book.snapshot()['available_cash']==1000
    with pytest.raises(ValueError):x.apply(dict(kind='cancel',event_id='cancel2',at=time(2),order_id='o'))

@pytest.mark.parametrize('bad',['{','{}','{"payload":{"version":999},"sha256":"x"}'])
def test_corrupt_persisted_source_refuses(bad):
    with pytest.raises(ValueError):ExecutionArm.loads(bad)

def test_conflicting_retry_and_minute_revision_refuse():
    x=arm();x.apply(submit());first=quote(volume=100);x.apply(first);before=x.dumps()
    changed=deepcopy(first);changed['quote']['ask']=99.5
    with pytest.raises(ValueError):x.apply(changed)
    revised=quote(2,volume=200)
    with pytest.raises(ValueError):x.apply(revised)
    assert x.dumps()==before

def test_other_stale_holding_does_not_prevent_risk_reducing_SELL():
    x=ExecutionArm('PF-A',[Instrument('NVDA','stock','fixture',1),Instrument('MSFT','stock','fixture',0)])
    x.apply(submit());x.apply(quote())
    e=submit('msft',at=time(2));e['order']['symbol']='MSFT';e['quotes']['MSFT']=e['quotes'].pop('NVDA');x.apply(e)
    q=quote(3);q['quote']['symbol']='MSFT';q['prior_bar']['symbol']='MSFT';x.apply(q)
    x.apply(submit('sell',side='sell',at=time(700)))
    assert x.apply(quote(701))['fills'][0]['side']=='sell','stale MSFT cannot suppress NVDA risk reduction'
    assert x.snapshot()['valuation_qualified'] is False,'stale other holding never makes qualified NAV'
    q=quote(702);q['quote']['symbol']='MSFT';q['prior_bar']['symbol']='MSFT';x.apply(q)
    assert x.snapshot()['valuation_qualified'] is True,'fresh marks restore qualification without invented values'

@pytest.mark.parametrize('kind',['boolean_version','duplicate_event'])
def test_semantically_corrupt_state_refuses_even_with_updated_checksum(kind):
    from hashlib import sha256
    from stock_swing.research.pf_execution_adapter import encode
    x=arm();x.apply(submit());doc=json.loads(x.dumps())
    if kind=='boolean_version':doc['payload']['version']=True
    else:doc['payload']['events'].append(deepcopy(doc['payload']['events'][0]))
    doc['sha256']=sha256(encode(doc['payload']).encode()).hexdigest()
    with pytest.raises(ValueError):ExecutionArm.loads(encode(doc))

def test_future_arrival_does_not_rewrite_previous_PF_receipt_or_seed():
    x=arm();x.apply(submit());x.apply(quote());cfg=EntryFilterConfig()
    f=ResearchPFFilter(cfg,'PF-A');f.filter([decision()],bars(),x.history,set())
    receipt=deepcopy(f.receipts[0]);x.apply(submit('sell',side='sell',at=time(2)))
    x.apply(quote(61,bid=50,ask=51,available_at=time(180)))
    assert f.receipts[0]==receipt and receipt['history_rows']==0,'later realized loss cannot enter earlier decision'
    assert x.history[0]['known_at']==time(180)

def late_close_fixture():
    x=arm();e=submit(qty=15,at='2026-11-02T20:59:58+00:00');e['order']['time_in_force']='day';x.apply(e)
    event=quote(23099,volume=1000,available_at=time(23101))
    return x,event

def test_TIF_uses_execution_clock_not_quote_arrival_clock():
    """Regression: PF-AB 10/29 adapter late pre-close quote must not lose fill."""
    x,event=late_close_fixture();r=x.apply(event)
    assert r['fills'][0]['qty']==10,'pre-close execution is known just after close'
    assert x.orders['o']['status']=='expired' and x.orders['o']['filled_qty']==10
    assert not x.book.pending,'only the unexecuted remainder expires'

def test_late_fill_after_explicit_expiry_is_unqualified_not_silently_zero():
    x,event=late_close_fixture();x.apply(dict(kind='clock',event_id='close',at='2026-11-02T21:00:00+00:00'));before=x.dumps()
    with pytest.raises(ValueError,match='late execution crosses'):
        x.apply(event)
    assert x.dumps()==before,'terminal ambiguity needs qualified event watermark, not retroactive cash'
