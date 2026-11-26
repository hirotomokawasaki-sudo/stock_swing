"""Availability-aware *valuation* port, not a backdated trading mark.

Legacy daily snapshots omit the original feed/adjustment/wire receipt. Their
use here requires explicit current-writer assumptions and never qualifies a
formal U or an executable price. The accepted exposure-only selector is reused
in a clean child process; source trading journals remain byte-identical.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, time
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import path_driver as base

HERE=Path(__file__).resolve().parent
NY=ZoneInfo('America/New_York')
ASSUMPTIONS=dict(role='current_writer_inference_not_original_wire_proof',feed='iex',
                 adjustment='raw',currency='USD',no_additional_modeled_events_until_close=True)


def digest(value):
    return hashlib.sha256(base.encode(value).encode()).hexdigest()


def _session(session):
    if (set(session)!={'session_date','open_at','close_at','calendar_source_ref','calendar_known_at'}
            or not isinstance(session['calendar_source_ref'],str) or not session['calendar_source_ref']):
        raise ValueError('explicit session/calendar receipt required')
    day=date.fromisoformat(session['session_date'])
    start,end=base.aware(session['open_at']),base.aware(session['close_at'])
    if (day.isoformat()!=session['session_date'] or not start<end
            or start.astimezone(NY).date()!=day or end.astimezone(NY).date()!=day):
        raise ValueError('session date/clock mismatch')
    # The caller supplies the authoritative regular/early close, not this code.
    base.aware(session['calendar_known_at'])
    return day,start,end


def read_daily(path, *, expected_sha256, session, analysis_at):
    """Read an explicit pinned file; the wrapper clock is not the bar label."""
    path=Path(path)
    if path.is_symlink():raise ValueError('symlinked price source')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('daily source changed')
    r=json.loads(raw);day,_,close=_session(session);now=base.aware(analysis_at)
    symbol=r['request_params']['symbol']
    if (r['source']!='broker' or r['endpoint']!='marketdata/bars'
            or r['request_params']['timeframe']!='1Day'
            or r['quality_status']!='ok' or r['is_synthetic'] is not False
            or r['payload']['symbol']!=symbol or r['payload']['next_page_token'] is not None):
        raise ValueError('unsupported, partial or synthetic daily snapshot')
    fetched,available,ingested=(base.aware(r[k]) for k in ('fetched_at','available_at','ingested_at'))
    if not close<fetched<=available<=ingested<=now:
        raise ValueError('daily data was not acquired after close and before analysis')
    rows=r['payload']['bars']
    if not isinstance(rows,list) or not rows:raise ValueError('missing daily bars')
    times=[]
    for b in rows:
        at=base.aware(b['t']);times.append(at)
        if at.astimezone(NY).time()!=time(0):raise ValueError('not a New York daily bar label')
        op,hi,lo,cl=(base.number(b[k]) for k in ('o','h','l','c'))
        if not lo<=min(op,cl)<=max(op,cl)<=hi:raise ValueError('invalid daily OHLC')
        base.number(b['v'],zero=True)
    if times!=sorted(set(times)) or times[-1].astimezone(NY).date()!=day:
        raise ValueError('duplicate, stale or wrong-session daily series')
    b=rows[-1]
    return dict(symbol=symbol,session_date=day.isoformat(),bar_label=b['t'],close=str(base.number(b['c'])),
        snapshot_fetched_at=r['fetched_at'],available_at=r['available_at'],ingested_at=r['ingested_at'],
        source_ref=str(path),source_sha256=expected_sha256,revision_id=r.get('revision_id'),
        original_request_feed=r['request_params'].get('feed'),original_request_adjustment=r['request_params'].get('adjustment'),
        original_wire_receipt_present=False,first_provider_publication_at=None,price_basis_qualified=False)


def project(journals, prices, *, session, analysis_at, assumptions):
    """Project one closing NAV from independent books, with no appended event."""
    base.encode(prices);base.encode(assumptions)
    if set(journals)!=set(base.ARMS):raise ValueError('all 101 own journals required')
    day,start,close=_session(session);now=base.aware(analysis_at)
    calendar_known=base.aware(session['calendar_known_at'])
    if not close<=now or calendar_known>now:raise ValueError('future session/calendar evidence')
    if assumptions is None:
        return dict(status='UNQUALIFIED_DAILY_BASIS',closing_books=None,formal_U=None,
            economic_qualified=False,market_PnL=None,reason='legacy feed/adjustment and wire provenance not certified')
    if base.encode(assumptions)!=base.encode(ASSUMPTIONS):
        raise ValueError('explicit supported unqualified valuation assumptions required')
    c=base.core();books={a:c.ComparisonBook.loads(journals[a]) for a in base.ARMS}
    union={x['symbol'] for b in books.values() for x in b.lots.values()}
    if set(prices)!=union:raise ValueError('exact own-held union required, not a favorable subset')
    known=max(calendar_known,close)
    for s,p in prices.items():
        if (p['symbol']!=s or p['session_date']!=day.isoformat()
                or p['price_basis_qualified'] is not False or p['original_wire_receipt_present'] is not False
                or not close<base.aware(p['snapshot_fetched_at'])<=base.aware(p['available_at'])<=now):
            raise ValueError('unqualified daily receipt identity/availability differs')
        actual=read_daily(p['source_ref'],expected_sha256=p['source_sha256'],session=session,analysis_at=analysis_at)
        if base.encode(actual)!=base.encode(p):raise ValueError('daily receipt differs from pinned source')
        if (p['original_request_feed'] not in (None,assumptions['feed'])
                or p['original_request_adjustment'] not in (None,assumptions['adjustment'])):
            raise ValueError('recorded contract conflicts with assumption')
        known=max(known,base.aware(p['available_at']));base.number(float(p['close']))
    common=None;values={};hashes={};lineage={}
    for arm,b in books.items():
        if b.last_at is None or not start<=base.aware(b.last_at)<=close or b.pending:
            raise ValueError('book is outside session or has unresolved orders')
        raw=json.loads(journals[arm])['payload'];p=asdict(b.policy)
        if base.encode(raw['policy'])!=base.encode(p):raise ValueError('implicit book policy refused')
        scale=1. if arm=='C11' else float(Decimal(int(arm[-3:]))/100)
        if (p['arm_id']!=arm or p['quantity_scale']!=scale or p['atr_sizing'] is not (arm=='C11')
                or p['semiconductor_cap']!=(.3 if arm=='C11' else None)):
            raise ValueError('C11/U identity changed')
        shared={k:v for k,v in p.items() if k not in ('arm_id','quantity_scale','atr_sizing','semiconductor_cap')}
        identity=base.encode(dict(policy=shared,instruments=json.loads(journals[arm])['payload']['instruments']))
        if common is not None and identity!=common:raise ValueError('arm seed/cost/universe mismatch')
        common=identity
        with localcontext() as ctx:
            ctx.prec=50
            gross=sum((Decimal(lot['qty'])*Decimal(prices[lot['symbol']]['close']) for lot in b.lots.values()),Decimal(0))
            cash=Decimal(str(b.cash));nav=cash+gross
            if not nav.is_finite() or nav<=0:raise ValueError('unqualified closing NAV')
            unrealized=sum((Decimal(lot['qty'])*(Decimal(prices[lot['symbol']]['close'])-Decimal(str(lot['unit_basis']))) for lot in b.lots.values()),Decimal(0))
            if abs(nav-Decimal(str(b.policy.baseline_equity))-Decimal(str(b.realized_pnl))-unrealized)>Decimal('.000001'):
                raise ValueError('closing NAV accounting bridge differs')
            values[arm]=dict(cash=str(cash),gross_market_value=str(gross),NAV=str(nav),exposure=float(gross/nav),
                realized_pnl=str(b.realized_pnl),unrealized_pnl=str(unrealized),fees_already_paid=str(b.fees),
                source_book_as_of=b.last_at,source_events=len(json.loads(journals[arm])['payload']['events']))
        hashes[arm]=hashlib.sha256(journals[arm].encode()).hexdigest()
        lineage[arm]=[dict(event_id=e['event_id'],at=e['at'],sha256=digest(e)) for e in raw['events']]
    body=dict(schema='c11-conditional-closing-valuation-v1',status='CONDITIONAL_EOD_PROJECTION',
        session=deepcopy(session),known_at=known.isoformat(),analysis_at=analysis_at,
        assumptions=deepcopy(assumptions),prices=deepcopy(prices),closing_books=values,
        source_journal_sha256=hashes,source_policy_universe_sha256=hashlib.sha256(common.encode()).hexdigest(),
        source_event_lineage=lineage,
        trading_journals_mutated=False,backdated_events_created=False,execution_prices_replaced=False,
        formal_U=None,economic_qualified=False,market_PnL=None)
    return dict(body,receipt_sha256=digest(body))


def calibrate(closes, *, evaluation_start_at, source_ref):
    """Pass only dated exposures to the *unchanged* selector, never NAV/PnL."""
    if not isinstance(closes,list) or not closes or not isinstance(source_ref,str) or not source_ref:
        raise ValueError('explicit nonempty closing receipts/source required')
    evaluation=base.aware(evaluation_start_at);dates=[];previous=None;identity=None;lineage={}
    exposure=dict(dates=[],C11=[],U_grid={str(i):[] for i in range(1,101)},
                  source_role='conditional_closing_valuation_engineering:'+source_ref)
    for receipt in closes:
        body={k:v for k,v in receipt.items() if k!='receipt_sha256'}
        if (digest(body)!=receipt.get('receipt_sha256') or body['status']!='CONDITIONAL_EOD_PROJECTION'
                or body['economic_qualified'] is not False or body['formal_U'] is not None
                or body['backdated_events_created'] is not False or set(body['closing_books'])!=set(base.ARMS)):
            raise ValueError('closing receipt corrupt or qualification changed')
        day,_,close=_session(body['session'])
        if (day>=evaluation.astimezone(NY).date() or base.aware(body['known_at'])>=evaluation
                or base.aware(body['analysis_at'])>=evaluation or (previous is not None and close<=previous)):
            raise ValueError('calibration data/knowledge/analysis must precede evaluation')
        previous=close;dates.append(day.isoformat());exposure['C11'].append(body['closing_books']['C11']['exposure'])
        if identity is not None and body['source_policy_universe_sha256']!=identity:
            raise ValueError('closing path policy/universe changed')
        identity=body['source_policy_universe_sha256']
        for arm in base.ARMS:
            events=body['source_event_lineage'][arm];old=lineage.get(arm,[])
            if (base.encode(events[:len(old)])!=base.encode(old)
                    or len(events)!=body['closing_books'][arm]['source_events']):
                raise ValueError('closing path journal reset/rewrite')
            if len(closes)>1 and old:
                prior_close=base.aware(closes[len(dates)-2]['session']['close_at'])
                if any(base.aware(e['at'])<=prior_close for e in events[len(old):]):
                    raise ValueError('new event backdated into a projected close')
            lineage[arm]=deepcopy(events)
        for i in range(1,101):exposure['U_grid'][str(i)].append(body['closing_books'][f'U_grid_{i:03}']['exposure'])
    if dates!=sorted(set(dates)):raise ValueError('strict distinct closing sessions required')
    exposure['dates']=dates
    code='import sys,json;sys.path.insert(0,sys.argv[1]);import bridge;v=json.load(sys.stdin);print(json.dumps(bridge._prepare().calibration_port(v["exposure"],v["evaluation_date"]),sort_keys=True))'
    p=subprocess.run([sys.executable,'-B','-c',code,str(HERE)],
        input=json.dumps(dict(exposure=exposure,evaluation_date=evaluation.astimezone(NY).date().isoformat())),
        capture_output=True,text=True,timeout=20)
    if p.returncode:raise ValueError('accepted selector child failed: '+p.stderr[-600:])
    chosen=json.loads(p.stdout)
    if chosen['formal_selected_scale'] is not None or chosen['economic_qualification'] is not False:
        raise ValueError('selector qualification unexpectedly changed')
    return dict(exposure_inputs=exposure,engineering_calibration=chosen,formal_U=None,
        economic_qualified=False,market_PnL=None,qualified_daily_sessions=0,
        conditional_daily_sessions=len(dates),receipt_sha256=[r['receipt_sha256'] for r in closes],
        all_zero_exposure=all(v==0 for v in exposure['C11']) and all(v==0 for vs in exposure['U_grid'].values() for v in vs))
