"""Acceptance: late-available daily valuation must never backdate execution."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json

import pytest
import closing_port as p
import path_driver as base

DAY='2026-11-25'
ANALYSIS='2026-11-26T01:15:00+00:00'
EVALUATION='2026-11-27T14:30:00+00:00'


def session(day=DAY, early=False):
    return dict(session_date=day,open_at=day+'T14:30:00+00:00',
        close_at=day+('T18:00:00+00:00' if early else 'T21:00:00+00:00'),
        calendar_source_ref='synthetic-calendar-fixture',calendar_known_at='2026-11-25T12:00:00+00:00')


def journals(empty=False):
    c=base.core();out={};at=DAY+'T20:55:00+00:00'
    for arm in base.ARMS:
        b=c.ComparisonBook(c.BookPolicy(arm,1_000_000.,quantity_scale=1. if arm=='C11' else int(arm[-3:])/100,
            atr_sizing=arm=='C11',semiconductor_cap=.3 if arm=='C11' else None,fee_bps=5.),
            [c.Instrument('IBM','stock','breakout_momentum_v1',0.)])
        b.apply(dict(kind='mark',event_id='mark',at=at,quotes={'IBM':dict(price=100.,as_of=at)}))
        if not empty:
            r=b.apply(dict(kind='reserve',event_id='reserve',at=at,order_id='order',symbol='IBM',qty=100,max_fill_price=100.,atr=2.,atr_available_at=at))
            b.apply(dict(kind='fill',event_id='fill',at=at,order_id='order',qty=r['qty'],raw_price=100.))
        out[arm]=b.dumps()
    return out


def raw(day=DAY):
    fetched=day+'T23:05:00+00:00'
    return dict(source='broker',endpoint='marketdata/bars',fetched_at=fetched,event_time=fetched,
        available_at=fetched,ingested_at=fetched,source_id='synthetic',revision_id=None,
        quality_status='ok',is_synthetic=False,request_params=dict(symbol='IBM',timeframe='1Day'),
        payload=dict(symbol='IBM',next_page_token=None,
            bars=[dict(t=day+'T05:00:00Z',o=100.,h=110.,l=90.,c=103.,v=1000,n=10,vw=102.)]))


def write_price(tmp_path, value=None, *, day=DAY, analysis=ANALYSIS):
    f=tmp_path/(day+'.json');f.write_text(json.dumps(raw(day) if value is None else value))
    return p.read_daily(f,expected_sha256=hashlib.sha256(f.read_bytes()).hexdigest(),session=session(day,early=day=='2026-11-27'),analysis_at=analysis)


def close(tmp_path, *, empty=False):
    books=journals(empty);prices={} if empty else {'IBM':write_price(tmp_path)}
    return p.project(books,prices,session=session(),analysis_at=ANALYSIS,assumptions=deepcopy(p.ASSUMPTIONS))


def test_ac_post_close_valuation_has_separate_bar_session_and_knowledge_clocks(tmp_path):
    books=journals();before=deepcopy(books);price=write_price(tmp_path)
    r=p.project(books,{'IBM':price},session=session(),analysis_at=ANALYSIS,assumptions=deepcopy(p.ASSUMPTIONS))
    a=r['closing_books']['C11']
    assert Decimal(a['cash'])==Decimal('989995') and Decimal(a['NAV'])==Decimal('1000295')
    assert Decimal(a['fees_already_paid'])==5,'daily mark must not charge a second transaction fee'
    assert r['known_at']=='2026-11-25T23:05:00+00:00' and price['bar_label']=='2026-11-25T05:00:00Z'
    assert r['session']['close_at']=='2026-11-25T21:00:00+00:00' and books==before
    assert a['source_book_as_of']=='2026-11-25T20:55:00+00:00'
    assert r['backdated_events_created'] is False and r['trading_journals_mutated'] is False
    assert price['original_request_feed'] is None and price['price_basis_qualified'] is False


def test_ac_real_closing_exposures_only_reach_unchanged_selector(tmp_path):
    r=close(tmp_path);v=p.calibrate([r],evaluation_start_at=EVALUATION,source_ref='synthetic')
    assert v['conditional_daily_sessions']==1 and v['qualified_daily_sessions']==0
    assert v['formal_U'] is None and v['market_PnL'] is None and not v['economic_qualified']
    assert set(v['exposure_inputs'])=={'dates','C11','U_grid','source_role'}
    assert Decimal(v['engineering_calibration']['engineering_selected_scale'])==1
    assert v['engineering_calibration']['exposure_mse']=='0.00000000000000000000000000' or Decimal(v['engineering_calibration']['exposure_mse'])==0


def test_ac_no_assumptions_returns_unavailable_not_fabricated_zero(tmp_path):
    v=p.project(journals(),{'IBM':write_price(tmp_path)},session=session(),analysis_at=ANALYSIS,assumptions=None)
    assert v['closing_books'] is None and v['market_PnL'] is None and v['status']=='UNQUALIFIED_DAILY_BASIS'


@pytest.mark.parametrize('case',['before_close','future_available','wrong_day','duplicate','bad_OHLC','NaN','non_daily','synthetic','wrong_symbol','pagination','naive','wrong_hash','bad_json','missing'])
def test_ac_invalid_daily_input_fails_without_price_fallback(tmp_path,case):
    r=raw();f=tmp_path/'bad.json'
    if case=='before_close':
        for key in ['fetched_at','available_at','ingested_at']:r[key]=DAY+'T20:59:00+00:00'
    elif case=='future_available':r['available_at']='2026-11-28T00:00:00+00:00'
    elif case=='wrong_day':r['payload']['bars'][0]['t']='2026-11-24T05:00:00Z'
    elif case=='duplicate':r['payload']['bars']*=2
    elif case=='bad_OHLC':r['payload']['bars'][0]['c']=1000.
    elif case=='NaN':r['payload']['bars'][0]['c']=float('nan')
    elif case=='non_daily':r['request_params']['timeframe']='1Min'
    elif case=='synthetic':r['is_synthetic']=True
    elif case=='wrong_symbol':r['payload']['symbol']='OTHER'
    elif case=='pagination':r['payload']['next_page_token']='more'
    elif case=='naive':r['available_at']='2026-11-25T23:05:00'
    f.write_text('{' if case=='bad_json' else json.dumps(r));sha=hashlib.sha256(f.read_bytes()).hexdigest()
    if case=='wrong_hash':sha='0'*64
    if case=='missing':f=tmp_path/'absent.json'
    with pytest.raises((ValueError,KeyError,OSError)):
        p.read_daily(f,expected_sha256=sha,session=session(),analysis_at=ANALYSIS)


@pytest.mark.parametrize('case',['missing_arm','missing_held','modified_price','adjusted_assumption','future_journal','pending','implicit_policy'])
def test_ac_projection_rejects_incomplete_or_changed_paths(tmp_path,case):
    books=journals();prices={'IBM':write_price(tmp_path)};assumptions=deepcopy(p.ASSUMPTIONS)
    if case=='missing_arm':books.pop('U_grid_001')
    elif case=='missing_held':prices={}
    elif case=='modified_price':prices['IBM']['close']='104'
    elif case=='adjusted_assumption':assumptions['adjustment']='all'
    elif case in {'future_journal','pending'}:
        b=base.core().ComparisonBook.loads(books['C11'])
        if case=='future_journal':
            at=DAY+'T21:01:00+00:00';b.apply(dict(kind='mark',event_id='future',at=at,quotes={'IBM':dict(price=100.,as_of=at)}))
        else:
            at=DAY+'T20:55:00+00:00';b.apply(dict(kind='reserve',event_id='new',order_id='new',at=at,symbol='IBM',qty=10,max_fill_price=100.,atr=2.,atr_available_at=at))
        books['C11']=b.dumps()
    elif case=='implicit_policy':
        v=json.loads(books['C11']);v['payload']['policy'].pop('max_atr_age_seconds');books['C11']=json.dumps(v)
    with pytest.raises((ValueError,KeyError)):
        p.project(books,prices,session=session(),analysis_at=ANALYSIS,assumptions=assumptions)


def test_ac_availability_not_only_session_date_is_before_evaluation(tmp_path):
    r=close(tmp_path)
    with pytest.raises(ValueError,match='precede evaluation'):
        p.calibrate([r],evaluation_start_at='2026-11-26T00:30:00+00:00',source_ref='too-early')
    bad=deepcopy(r);bad['closing_books']['C11']['exposure']=0
    with pytest.raises(ValueError,match='corrupt'):
        p.calibrate([bad],evaluation_start_at=EVALUATION,source_ref='mutated')


def test_ac_empty_books_are_inactive_not_a_treatment_result(tmp_path):
    r=close(tmp_path,empty=True);v=p.calibrate([r],evaluation_start_at=EVALUATION,source_ref='empty')
    assert v['all_zero_exposure'] and Decimal(v['engineering_calibration']['engineering_selected_scale'])==Decimal('.01')
    assert base.aware(r['known_at'])>=base.aware(r['session']['close_at']),'even cash-only projection cannot claim a completed close early'


def test_explicit_early_close_is_not_silently_replaced_with_16_ET(tmp_path):
    d='2026-11-27';v=write_price(tmp_path,day=d,analysis='2026-11-28T01:00:00+00:00')
    assert v['session_date']==d and session(d,early=True)['close_at']==d+'T18:00:00+00:00'


def test_malformed_receipt_cannot_claim_qualified_daily_data(tmp_path):
    r=close(tmp_path);r['economic_qualified']=0
    body={k:v for k,v in r.items() if k!='receipt_sha256'};r['receipt_sha256']=p.digest(body)
    with pytest.raises(ValueError):p.calibrate([r],evaluation_start_at=EVALUATION,source_ref='false-is-not-zero')


def test_next_session_keeps_independent_append_only_journals_and_rejects_reset(tmp_path):
    first=close(tmp_path);day='2026-11-27';analysis='2026-11-28T01:00:00+00:00';at=day+'T17:55:00+00:00'
    prices={'IBM':write_price(tmp_path,day=day,analysis=analysis)};c=base.core();next_books={};reset_books={}
    for arm,text in journals().items():
        b=c.ComparisonBook.loads(text);e=dict(kind='mark',event_id='next-day',at=at,quotes={'IBM':dict(price=100.,as_of=at)})
        b.apply(e);next_books[arm]=b.dumps()
        reset=c.ComparisonBook(b.policy,list(b.instruments.values()));reset.apply(e);reset_books[arm]=reset.dumps()
    second=p.project(next_books,prices,session=session(day,early=True),analysis_at=analysis,assumptions=deepcopy(p.ASSUMPTIONS))
    result=p.calibrate([first,second],evaluation_start_at='2026-11-30T14:30:00+00:00',source_ref='two-synthetic-sessions')
    assert result['conditional_daily_sessions']==2 and result['formal_U'] is None
    reset=p.project(reset_books,{},session=session(day,early=True),analysis_at=analysis,assumptions=deepcopy(p.ASSUMPTIONS))
    with pytest.raises(ValueError,match='reset/rewrite'):
        p.calibrate([first,reset],evaluation_start_at='2026-11-30T14:30:00+00:00',source_ref='reset')


def test_price_symlink_is_not_accepted_as_a_pinned_snapshot(tmp_path):
    actual=tmp_path/'real.json';actual.write_text(json.dumps(raw()));linked=tmp_path/'link.json';linked.symlink_to(actual)
    with pytest.raises(ValueError,match='symlink'):
        p.read_daily(linked,expected_sha256=hashlib.sha256(actual.read_bytes()).hexdigest(),session=session(),analysis_at=ANALYSIS)


def test_new_event_cannot_be_backfilled_before_an_exported_close(tmp_path):
    first=close(tmp_path);day='2026-11-27';analysis='2026-11-28T01:00:00+00:00';prices={'IBM':write_price(tmp_path,day=day,analysis=analysis)}
    books={};c=base.core()
    for arm,text in journals().items():
        b=c.ComparisonBook.loads(text)
        for key,at in [('late',DAY+'T20:58:00+00:00'),('next',day+'T17:55:00+00:00')]:
            b.apply(dict(kind='mark',event_id=key,at=at,quotes={'IBM':dict(price=100.,as_of=at)}))
        books[arm]=b.dumps()
    second=p.project(books,prices,session=session(day,early=True),analysis_at=analysis,assumptions=deepcopy(p.ASSUMPTIONS))
    with pytest.raises(ValueError,match='backdated'):
        p.calibrate([first,second],evaluation_start_at='2026-11-30T14:30:00+00:00',source_ref='late-event')


@pytest.mark.parametrize('field,value',[('feed','sip'),('adjustment','all')])
def test_current_writer_assumption_cannot_override_conflicting_recorded_contract(tmp_path,field,value):
    source=raw();source['request_params'][field]=value;price=write_price(tmp_path,source)
    with pytest.raises(ValueError,match='conflicts'):
        p.project(journals(),{'IBM':price},session=session(),analysis_at=ANALYSIS,assumptions=deepcopy(p.ASSUMPTIONS))
