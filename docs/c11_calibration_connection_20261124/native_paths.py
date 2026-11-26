"""Independent C11/U native-component paths; no clients or production state.

Reuses the sealed book, pinned native source and accepted pure guard adapter.
Observed bid/ask execution is an explicit zero-latency/full-fill engineering
model, not a historical fill, capacity certification or selected formal U.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
import hashlib
import inspect

import path_driver as base
from native_entries import NativeEntries

MODEL = 'observed_bid_ask_zero_latency_full_fill_engineering_v1'


def run(initial, frames, *, native_source_root, native_pins, entry_policy, exit_policy,
        guard_source, guard_sha256, source_ref, execution_model):
    base.encode(frames); base.encode(entry_policy); base.encode(exit_policy)
    if execution_model != MODEL or not isinstance(source_ref,str) or not source_ref.strip():
        raise ValueError('explicit supported execution model and source required')
    if set(initial) != set(base.ARMS) or not isinstance(frames,list) or not frames:
        raise ValueError('101 independent initial books and nonempty frames required')
    c = base.core(); exits, Feature = base.native(native_source_root,native_pins)
    entries = NativeEntries(entry_policy,guard_source=guard_source,guard_sha256=guard_sha256)
    base.native(native_source_root,native_pins)  # Includes the newly imported native entry closure.
    if set(exit_policy) != set(inspect.signature(exits.SimpleExitV2Strategy).parameters):
        raise ValueError('complete explicit native Exit policy required')
    for k,v in exit_policy.items():
        if k.endswith('_enabled') and type(v) is not bool:
            raise ValueError('explicit boolean Exit policy required')
    states={}; first=None
    for arm in base.ARMS:
        b=c.ComparisonBook.loads(initial[arm]); raw=__import__('json').loads(initial[arm])['payload']
        k=1. if arm=='C11' else float(Decimal(int(arm[-3:]))/100)
        if (raw['events'] or b.lots or b.pending or b.policy.arm_id!=arm
                or base.encode(raw['policy'])!=base.encode(asdict(b.policy))
                or b.policy.quantity_scale!=k or b.policy.atr_sizing is not (arm=='C11')
                or b.policy.semiconductor_cap!=(.3 if arm=='C11' else None) or b.policy.slippage_bps!=0):
            raise ValueError('explicit cash-only C11/U policy required')
        common=asdict(b.policy)
        for key in ('arm_id','quantity_scale','atr_sizing','semiconductor_cap'):common.pop(key)
        identity=(common,b.instruments)
        if first is not None and identity!=first:raise ValueError('different seed/cost/universe')
        first=identity
        states[arm]=dict(book=b,history=[],metadata={},guard_halt_latched=False,day_anchor=None)
    checkpoints={a:[] for a in base.ARMS};sessions=[];audit=[];previous=None
    original=exits.datetime
    try:
        for i,frame in enumerate(frames):
            if set(frame)!={'at','quotes','features','bars','close','day_start','operational','exit_only','source_ref','filter_policy'}:
                raise ValueError('explicit native frame schema required')
            now=base.aware(frame['at'])
            if previous is not None and now<=previous:raise ValueError('strictly ordered frames required')
            previous=now
            if type(frame['day_start']) is not bool or type(frame['exit_only']) is not bool or not frame['source_ref']:
                raise ValueError('explicit day reference/EXIT_ONLY/source required')
            if not isinstance(frame['operational'],dict) or set(frame['operational'])-set(base.ARMS):
                raise ValueError('unknown operational arm')
            universe=states['C11']['book'].instruments
            if set(frame['quotes'])-set(universe):raise ValueError('quote outside fixed universe')
            marks={}
            for symbol,q in frame['quotes'].items():
                if set(q)!={'bid','ask','as_of','available_at'} or not base.aware(q['as_of'])<=base.aware(q['available_at'])<=now:
                    raise ValueError('causally available bid/ask receipt required')
                if not 0<=float(base.number(q['bid']))<=float(base.number(q['ask'])) or (now-base.aware(q['as_of'])).total_seconds()>5:
                    raise ValueError('invalid/stale bid/ask')
                marks[symbol]=dict(price=float((Decimal(str(q['bid']))+Decimal(str(q['ask'])))/2),as_of=q['as_of'])
            generated=entries.candidates(frame,universe)
            feature_map={f['symbol']:f for f in frame['features'] if f['feature_name']=='price_momentum'}
            native_features=[Feature(f['feature_name'],f['symbol'],base.aware(f['computed_at']),
                deepcopy(f['values']),deepcopy(f['metadata']),deepcopy(f['quality_flags'])) for f in frame['features']]
            class Clock(datetime):
                @classmethod
                def now(cls,tz=None):return now.astimezone(tz) if tz else now.replace(tzinfo=None)
            # The external clock boundary only; no internal decision logic is replaced.
            exits.datetime=Clock
            for arm,state in states.items():
                b=state['book']
                if any(x['symbol'] not in marks for x in b.lots.values()):
                    raise ValueError('missing held-symbol mark; cannot discard an arm path')
                b.apply(dict(kind='mark',event_id=f'{i}:mark',at=frame['at'],quotes=marks))
                if frame['day_start']:
                    if state['day_anchor'] and state['day_anchor']['date']==now.date().isoformat():
                        raise ValueError('day reference cannot reset within a UTC day')
                    state['day_anchor']=dict(date=now.date().isoformat(),at=frame['at'],
                        unrealized=sum(x['qty']*(b._mark(x['symbol'],now,fresh=True)-x['unit_basis']) for x in b.lots.values()),
                        journal_sha256=hashlib.sha256(b.dumps().encode()).hexdigest(),
                        role='caller-marked first observation reference, not certified session open')
                strategy=exits.SimpleExitV2Strategy(**deepcopy(exit_policy))
                for lot_id,lot in list(b.lots.items()):
                    meta=state['metadata'][lot_id];symbol=lot['symbol'];mid=marks[symbol]['price']
                    if symbol in entry_policy['quarantined_symbols']:continue
                    if meta['entry_price']>mid*3 or (meta['peak_price']>meta['entry_price']*2.5 and meta['peak_price']>mid*2.5):
                        raise ValueError('corporate-action ambiguity outside model')
                    position=dict(qty=lot['qty'],avg_entry_price=meta['entry_price'],current_price=mid,
                        peak_price=meta['peak_price'],created_at=lot['bought_at'],entry_signal_strength=meta['strength'])
                    signals=strategy.generate(deepcopy(native_features),{symbol:position})
                    meta['peak_price']=max(meta['peak_price'],mid)
                    if signals:
                        if len(signals)!=1:raise ValueError('ambiguous native Exit')
                        receipt=b.apply(dict(kind='sell',event_id=f'{i}:sell:{lot_id}',at=frame['at'],lot_id=lot_id,
                                             qty=lot['qty'],raw_price=frame['quotes'][symbol]['bid']))
                        state['history'].append(dict(trade_id=f'{i}:{lot_id}',symbol=symbol,status='closed',
                            qty=receipt['qty'],pnl=receipt['realized_pnl'],entry_time=lot['bought_at'],exit_time=frame['at']))
                        del state['metadata'][lot_id]
                        audit.append(dict(frame=i,arm=arm,kind='native_exit',symbol=symbol,
                            decision_price=signals[0].metadata['current_price'],trigger=signals[0].metadata['exit_trigger'],
                            modeled_sell_bid=frame['quotes'][symbol]['bid'],realized_pnl=receipt['realized_pnl']))
                for n,candidate in enumerate(generated):
                    symbol=candidate.symbol
                    decision=entries.evaluate(state=state,frame=frame,candidate=candidate,quote=frame['quotes'].get(symbol))
                    audit.append(dict(frame=i,arm=arm,kind='entry_components',generator_ordinal=n,**deepcopy(decision)))
                    if decision['status']!='nominal_ready':continue
                    atr=feature_map[symbol]['values'].get('atr')
                    if atr is None or (arm=='C11' and base.number(atr,zero=True)==0):
                        audit.append(dict(frame=i,arm=arm,kind='blocked_ATR',symbol=symbol));continue
                    price=frame['quotes'][symbol]['ask'];nominal=decision['nominal_qty']
                    planned=int(Decimal(nominal)*Decimal(str(b.policy.quantity_scale)))
                    if arm=='C11':
                        width=max(2*Decimal(str(atr)),Decimal(str(price))*Decimal('.05'))
                        planned=min(planned,int((Decimal(str(b.policy.baseline_equity))*Decimal('.003')/width).to_integral_value(rounding=ROUND_FLOOR)))
                    unit=Decimal(str(price))*(1+Decimal(str(b.policy.fee_bps))/10000)
                    expected=min(planned,int((Decimal(str(b.cash-b._reserved_cash()))/unit).to_integral_value(rounding=ROUND_FLOOR)))
                    if expected<=0:
                        audit.append(dict(frame=i,arm=arm,kind='quantity_or_cash_zero',symbol=symbol));continue
                    order=f'{i}:{n}:{arm}'
                    try:
                        receipt=b.apply(dict(kind='reserve',event_id=order+':reserve',at=frame['at'],order_id=order,
                            symbol=symbol,qty=nominal,max_fill_price=price,atr=atr,
                            atr_available_at=feature_map[symbol]['available_at'],strategy_id=decision['strategy_id']))
                    except ValueError as exc:
                        if str(exc)!='projected semiconductor cap':raise
                        audit.append(dict(frame=i,arm=arm,kind='cap_rejected',symbol=symbol));continue
                    if receipt['qty']!=expected:raise ValueError('Decimal sizing contract differs from book')
                    filled=b.apply(dict(kind='fill',event_id=order+':fill',at=frame['at'],order_id=order,qty=receipt['qty'],raw_price=price))
                    state['metadata'][filled['lot_id']]=dict(entry_price=price,peak_price=price,strength=decision['signal_strength'])
                    audit.append(dict(frame=i,arm=arm,kind='modeled_fill',symbol=symbol,qty=receipt['qty'],nominal_qty=nominal,buy_ask=price))
            if frame['close'] is not None:
                close=frame['close']
                if set(close)!={'session_date','close_at','calendar_source_ref'} or base.aware(close['close_at'])!=now:
                    raise ValueError('explicit same-clock close receipt required')
                sessions.append(deepcopy(close))
                for arm,state in states.items():checkpoints[arm].append(state['book'].dumps())
    finally:exits.datetime=original
    return dict(checkpoints=checkpoints,sessions=sessions,audit=audit,
        ending_journals={a:s['book'].dumps() for a,s in states.items()},
        own_histories={a:s['history'] for a,s in states.items()},
        native_entry_components_connected=True,execution_model=MODEL,source_ref=source_ref,
        entry_policy_sha256=hashlib.sha256(base.encode(entry_policy).encode()).hexdigest(),
        exit_policy_sha256=hashlib.sha256(base.encode(exit_policy).encode()).hexdigest(),
        native_source_sha256=hashlib.sha256(base.encode(native_pins).encode()).hexdigest(),guard_sha256=guard_sha256,
        ranking_scope='native breakout generation order, not all-strategy CLI round-robin',
        history_scope='explicit fresh study PF history, own modeled closes; not actual account history',
        day_reference_scope='explicit caller-marked first observation, not certified session open',
        weekly_guard_scope='unchanged native rolling realized-loss implementation, not weekly mark-to-market',
        capacity_and_settlement_qualified=False,full_strategy_replay_qualified=False,
        formal_U=None,economic_qualified=False,market_PnL=None,real_orders_submitted=0)
