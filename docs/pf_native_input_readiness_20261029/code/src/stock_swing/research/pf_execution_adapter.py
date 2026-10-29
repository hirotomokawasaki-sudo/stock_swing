"""Offline PF-AB execution plumbing, not economic qualification or a broker.

Caller supplies frozen inputs. No filesystem defaults, network, signal generator,
stop reset, or production hooks. Native CLI policies remain the policy owner.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json
import math

from stock_swing.execution.cancellation_timing import ET, regular_hours, session_bounds
from stock_swing.research.comparison_book import BookPolicy, ComparisonBook, Instrument
from stock_swing.risk.entry_filter import EntryFilterConfig, EntryFilterEngine


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("aware timestamp required")
    return result.astimezone(timezone.utc)


def positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("positive finite numeric input required")
    return value


def shares(value):
    if type(value) is not int or value < 1:
        raise ValueError("positive integer shares required")
    return value


class ResearchPFFilter(EntryFilterEngine):
    """Deliberate B treatment: withhold only the input used by PF Gates 3/4.

    Native filter source uses closed_trades only to compute pf_stats for Gates
    3/4. A receives its exact full arm history. B retains that same history in
    its book but supplies [] to this one PF calculation; its config (including
    disabled=False), decisions, bars, ETF set and Gates 0/1/2 are unchanged.
    This is explicit ablation, not a claim that B has an empty trading history.
    """
    def __init__(self, config: EntryFilterConfig, arm: str):
        if arm not in {"PF-A", "PF-B"} or config.disabled:
            raise ValueError("explicit A/B and all non-PF gates enabled required")
        super().__init__(deepcopy(config))
        self.arm = arm
        self.receipts = []

    def filter(self, decisions, records_by_symbol, closed_trades, etf_symbols=None):
        consumed = deepcopy(closed_trades)
        result = super().filter(decisions, records_by_symbol,
                                consumed if self.arm == "PF-A" else [], etf_symbols)
        self.receipts.append(dict(arm=self.arm, history_rows=len(consumed),
            history_sha256=sha256(encode(consumed).encode()).hexdigest(),
            config=asdict(self.config), ablated_gates=[] if self.arm == "PF-A" else [3, 4],
            passed=[d.symbol for d in result.passed], blocked=result.blocked))
        return result


class ExecutionArm:
    """Independent transactional cash/lot/pending/history synthetic execution.

    apply() is the sole mutation API. At each quote, execution happens at the
    event clock but becomes visible only at known_at. Arrival clocks must be
    ordered; economic execution clocks may be delayed. Closed legs are added to
    PF policy memory only at known_at. SELL reservations prevent overselling.
    The upstream native CLI still owns all decision/risk/allocation policies.
    """
    def __init__(self, arm, instruments, *, cash=1_000_000, seed=None, slippage_bps=5):
        if arm not in {"PF-A", "PF-B"}:
            raise ValueError("unknown arm")
        if seed is not None and (not isinstance(seed,list) or any(not isinstance(row,dict) for row in seed)):
            raise ValueError('explicit ordered seed rows required')
        self.initial = dict(arm=arm, instruments=[asdict(x) for x in instruments],
                            cash=cash, seed=deepcopy(seed or []), slippage_bps=slippage_bps)
        encode(self.initial)
        self.book = ComparisonBook(BookPolicy(arm, cash, slippage_bps=slippage_bps), instruments)
        self.history = deepcopy(seed or [])
        self.orders = {}
        self.legs = []
        self.lot_executed = {}
        self.peaks = {}
        self.latest_quotes = {}
        self.volume_used = {}
        self.volume_sources = {}
        self.last_at = None
        self.events = []
        self.receipts = {}

    def apply(self, event):
        data = encode(event)
        if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not event['event_id']:
            raise ValueError("event identity required")
        digest = sha256(data.encode()).hexdigest()
        old = self.receipts.get(event['event_id'])
        if old:
            if old['digest'] != digest:
                raise ValueError("conflicting retry")
            return deepcopy(old['result'])
        now = stamp(event['at'])
        if self.last_at and now < stamp(self.last_at):
            raise ValueError("arrival clock regressed")
        work = deepcopy(self)
        result = work._execute(json.loads(data), now)
        work.last_at = now.isoformat()
        work.events.append(json.loads(data))
        work.receipts[event['event_id']] = dict(digest=digest, result=deepcopy(result))
        self.__dict__.clear()
        self.__dict__.update(work.__dict__)
        return deepcopy(result)

    def _book_event(self, event, kind, suffix, **fields):
        return self.book.apply(dict(event_id=event['event_id']+':'+suffix,
            at=event['at'], kind=kind, **fields))

    def _expire(self, event, now):
        for oid, order in self.orders.items():
            if order['status'] not in {'new', 'partially_filled'} or order['time_in_force'] != 'day':
                continue
            day = stamp(order['submitted_at']).astimezone(ET).date()
            bounds = session_bounds(day)
            if bounds is None or now >= bounds[1]:
                if oid in self.book.pending:
                    self._book_event(event, 'cancel', 'expire:'+oid, order_id=oid)
                order['status'] = 'expired'

    def _execute(self, event, now):
        kind = event.get('kind')
        if kind == 'submit':
            order = deepcopy(event['order'])
            oid, symbol = order['id'], order['symbol']
            if not isinstance(oid, str) or not oid or oid in self.orders or symbol not in self.book.instruments:
                raise ValueError("unique order and known symbol required")
            qty = shares(order['qty'])
            if order['side'] not in {'buy','sell'} or order['type'] not in {'market','limit'} or order['time_in_force'] not in {'day','gtc'}:
                raise ValueError('unsupported order shape')
            if not regular_hours(now):
                raise ValueError('intent outside regular session')
            if order['type'] == 'limit':
                positive(order['limit_price'])
            if order['side'] == 'buy':
                bound = positive(order['max_fill_price'])
                result = self._book_event(event,'reserve','reserve',order_id=oid,
                    symbol=symbol,qty=qty,max_fill_price=bound,quotes=event['quotes'])
                if result['qty'] != qty:
                    raise ValueError('native quantity unaffordable; never silently resize')
            else:
                available = sum(x['qty'] for x in self.book.lots.values() if x['symbol']==symbol)
                reserved = sum(x['qty']-x['filled_qty'] for x in self.orders.values()
                    if x['symbol']==symbol and x['side']=='sell' and x['status'] in {'new','partially_filled'})
                if qty > available-reserved:
                    raise ValueError('SELL exceeds unreserved owned quantity')
            order.update(status='new',filled_qty=0,submitted_at=event['at'])
            self.orders[oid] = order
            return dict(order_id=oid,status='new',qty=qty)
        if kind == 'cancel':
            order = self.orders[event['order_id']]
            if order['status'] not in {'new','partially_filled'}:
                raise ValueError('terminal order cannot be cancelled')
            if order['id'] in self.book.pending:
                self._book_event(event,'cancel','cancel',order_id=order['id'])
            order['status']='canceled'
            return dict(status='canceled')
        if kind == 'clock':
            self._expire(event,now)
            return dict(status='clock_advanced')
        if kind != 'quote':
            raise ValueError('unknown event kind')
        q = event['quote']
        executed, available = stamp(q['executed_at']),stamp(q['available_at'])
        if available != now or available < executed or (available-executed).total_seconds()>300:
            raise ValueError('unqualified quote availability')
        symbol=q['symbol']; bid=positive(q['bid']); ask=positive(q['ask'])
        if symbol not in self.book.instruments or bid>ask or q.get('basis')!='raw':
            raise ValueError('invalid quote or adjustment basis')
        # Mark only on arrival. Do not regress the execution clock of a mark.
        prior=self.latest_quotes.get(symbol)
        if prior and executed<stamp(prior['as_of']):
            raise ValueError('late quote regresses usable mark')
        self.latest_quotes[symbol]=dict(price=(bid+ask)/2,as_of=q['executed_at'])
        marks={s:deepcopy(x) for s,x in self.latest_quotes.items()
               if 0 <= (now-stamp(x['as_of'])).total_seconds() <= 300}
        for order in self.orders.values():
            if order['symbol']==symbol and order['status']=='expired' and order['time_in_force']=='day':
                bounds=session_bounds(stamp(order['submitted_at']).astimezone(ET).date())
                if bounds and stamp(order['submitted_at'])<executed<bounds[1]:
                    raise ValueError('late execution crosses explicit expiry; event watermark unqualified')
        # Eligibility is execution-time, cash/PF visibility is arrival-time.
        # Do not expire a pre-close execution merely because it arrives late.
        self._expire(event,executed)
        mark_qualified=True
        try:
            self._book_event(event,'mark','mark',quotes=marks)
        except ValueError as exc:
            if str(exc) not in {'missing mark','unusable mark'}:raise
            mark_qualified=False  # Missing other marks hold BUY, never SELL.
        self.peaks[symbol]=max(self.peaks.get(symbol,0),(bid+ask)/2)
        bar=event.get('prior_bar')
        if bar is None:
            self._expire(event,now)
            return dict(status='pending_missing_prior_volume',fills=[])
        start,end,known=stamp(bar['start']),stamp(bar['end']),stamp(bar['available_at'])
        if (bar.get('symbol')!=symbol or (end-start).total_seconds()!=60 or start.second or start.microsecond
                or end>executed.replace(second=0,microsecond=0) or known<end or known>executed
                or end != executed.replace(second=0,microsecond=0) or bar.get('basis')!='raw'):
            raise ValueError('only immediately prior completed known minute volume eligible')
        volume=bar['volume']
        if isinstance(volume,bool) or not isinstance(volume,(int,float)) or not math.isfinite(volume) or volume<0:
            raise ValueError('invalid prior volume')
        key=encode([symbol,end.isoformat()])
        source=sha256(encode(bar).encode()).hexdigest()
        if key in self.volume_sources and self.volume_sources[key]!=source:
            raise ValueError('volume revision within consumed minute')
        self.volume_sources[key]=source
        capacity=int((Decimal(str(volume))*Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR))
        capacity-=self.volume_used.get(key,0)
        fills=[]
        if not regular_hours(executed):
            self._expire(event,now)
            return dict(status='outside_regular_session',fills=[])
        for oid, order in self.orders.items():
            if capacity<=0:break
            if order['status'] not in {'new','partially_filled'} or order['symbol']!=symbol or executed<=stamp(order['submitted_at']):continue
            if order['side']=='buy' and not mark_qualified:continue
            raw=ask if order['side']=='buy' else bid
            execution=raw*(1+self.book.policy.slippage_bps/10000*(1 if order['side']=='buy' else -1))
            if order['type']=='limit' and ((order['side']=='buy' and execution>order['limit_price']) or (order['side']=='sell' and execution<order['limit_price'])):continue
            if order['side']=='buy' and raw>order['max_fill_price']:continue
            qty=min(capacity,order['qty']-order['filled_qty'])
            leg=dict(order_id=oid,qty=qty,raw_price=raw,executed_at=q['executed_at'],known_at=event['at'],side=order['side'])
            if order['side']=='buy':
                r=self._book_event(event,'fill','fill:'+oid,order_id=oid,qty=qty,raw_price=raw,quotes=marks)
                leg['lot_id']=r['lot_id']
                self.lot_executed[r['lot_id']]=q['executed_at']
            else:
                remaining=qty
                for lot_id,lot in list(self.book.lots.items()):
                    if lot['symbol']!=symbol or not remaining:continue
                    n=min(remaining,lot['qty'])
                    r=self._book_event(event,'sell','sell:'+oid+':'+lot_id,lot_id=lot_id,qty=n,raw_price=raw,quotes=marks)
                    self.history.append(dict(status='closed',symbol=symbol,pnl=r['realized_pnl'],qty=n,
                        entry_time=self.lot_executed[lot_id],exit_time=q['executed_at'],known_at=event['at'],
                        execution_leg_id=event['event_id']+':'+oid+':'+lot_id))
                    remaining-=n
                if remaining:raise ValueError('SELL inventory changed')
            order['filled_qty']+=qty
            order['status']='filled' if order['filled_qty']==order['qty'] else 'partially_filled'
            capacity-=qty;self.volume_used[key]=self.volume_used.get(key,0)+qty
            self.legs.append(leg);fills.append(leg)
        self._expire(event,now)
        return dict(status='processed',fills=fills)

    def positions(self):
        """Broker-shaped arm view; no proceeds from unfilled SELLs credited."""
        groups={}
        for lot_id,lot in self.book.lots.items():
            entry=self.lot_executed[lot_id]
            row=groups.setdefault(lot['symbol'],dict(qty=0,basis=0,entry_time=entry))
            row['qty']+=lot['qty'];row['basis']+=lot['qty']*lot['unit_basis']
            row['entry_time']=min(row['entry_time'],entry)
        return [dict(symbol=symbol,qty=str(x['qty']),avg_entry_price=str(x['basis']/x['qty']),
            current_price=str(self.book.quotes[symbol]['price']),market_value=str(x['qty']*self.book.quotes[symbol]['price']),
            peak_price=self.peaks.get(symbol,self.book.quotes[symbol]['price']),created_at=x['entry_time'],
            unrealized_pl=str(x['qty']*self.book.quotes[symbol]['price']-x['basis']),
            unrealized_plpc=str((x['qty']*self.book.quotes[symbol]['price']-x['basis'])/x['basis']),
            asset_class='us_equity') for symbol,x in groups.items()]

    def snapshot(self):
        """Observed book values with current-arrival freshness, never zero NAV."""
        result=self.book.snapshot()
        now=stamp(self.last_at) if self.last_at else None
        result['valuation_qualified']=all(
            now is not None and lot['symbol'] in self.book.quotes
            and 0 <= (now-stamp(self.book.quotes[lot['symbol']]['as_of'])).total_seconds() <= 300
            for lot in self.book.lots.values())
        result['observed_at']=self.last_at
        return result

    def dumps(self):
        payload=dict(version=1,initial=self.initial,events=self.events)
        return encode(dict(payload=payload,sha256=sha256(encode(payload).encode()).hexdigest()))

    @classmethod
    def loads(cls,text):
        try:
            outer=json.loads(text);p=outer['payload']
            if (set(outer)!={'payload','sha256'} or set(p)!={'version','initial','events'}
                    or type(p['version']) is not int or p['version']!=1
                    or not isinstance(p['events'],list)
                    or sha256(encode(p).encode()).hexdigest()!=outer['sha256']):
                raise ValueError('invalid arm envelope')
            settings=deepcopy(p['initial']);settings['instruments']=[Instrument(**x) for x in settings['instruments']]
            result=cls(**settings)
            for event in p['events']:
                if event.get('event_id') in result.receipts:raise ValueError('duplicate persisted event')
                result.apply(event)
            return result
        except (KeyError,TypeError,json.JSONDecodeError) as exc:
            raise ValueError('invalid arm source') from exc
