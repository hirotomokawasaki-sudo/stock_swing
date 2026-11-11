"""Pure evidence-based row proposals, NOT a ledger migration or apply command.

Whole BUY lots sharing a SELL use that order's raw-fill VWAP. Partial SELL
observations use proven cumulative-quantity boundaries, never final VWAP as
incremental price. BUY cost is pooled within each completed BUY order.
CRWD-style corporate reconstruction is a separate scoped, post-hoc proposal.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal as D, ROUND_HALF_EVEN

from stock_swing.tracking.execution_cost import decimal_value, whole_quantity
from stock_swing.tracking.execution_fifo import utc_time, day_time, match_order_completion_fifo


def cents(value):
    return value.quantize(D('.01'), rounding=ROUND_HALF_EVEN)


class Evidence:
    def __init__(self, orders, activities):
        ids = [o.get('id') for o in orders]
        if not all(ids) or len(ids) != len(set(ids)):
            raise ValueError('missing/duplicate order identity')
        ids = [a.get('id') for a in activities]
        if not all(ids) or len(ids) != len(set(ids)):
            raise ValueError('missing/duplicate activity identity')
        self.orders = {o['id']: o for o in orders}
        self.activities = activities

    def order(self, oid, side, symbol):
        row = self.orders.get(oid)
        if not row or (row.get('side'), row.get('symbol'), row.get('status')) != (side, symbol, 'filled'):
            raise ValueError('missing/conflicting completed order')
        qty = whole_quantity(row.get('filled_qty'), 'order quantity')
        parts = [a for a in self.activities if a.get('order_id') == oid and a.get('activity_type') == 'FILL']
        if not parts:
            raise ValueError('missing raw fill evidence')
        parts = sorted(parts, key=lambda a: (utc_time(a.get('transaction_time')), a['id']))
        amount, cumulative, prefixes = D(0), 0, {0: D(0)}
        for part in parts:
            if (part.get('side'), part.get('symbol')) != (side, symbol):
                raise ValueError('fill identity conflict')
            n = whole_quantity(part.get('qty'), 'fill quantity')
            amount += n * decimal_value(part.get('price'), 'fill price')
            cumulative += n
            if whole_quantity(part.get('cum_qty'), 'cumulative fill quantity') != cumulative:
                raise ValueError('raw cumulative fill sequence mismatch')
            if whole_quantity(part.get('leaves_qty'), 'leaves quantity', positive=False) != qty-cumulative:
                raise ValueError('raw leaves quantity mismatch')
            prefixes[cumulative] = amount
        if cumulative != qty or abs(amount-qty*decimal_value(row.get('filled_avg_price'), 'order VWAP')) >= D('.01'):
            raise ValueError('order/raw fill quantity or notional mismatch')
        if utc_time(parts[-1]['transaction_time']) != utc_time(row.get('filled_at')):
            raise ValueError('order/raw final execution time mismatch')
        return dict(order=row, qty=qty, notional=amount, price=amount/qty, parts=parts, prefixes=prefixes,
                    first=utc_time(parts[0]['transaction_time']), last=utc_time(parts[-1]['transaction_time']))

    def no_split(self, symbol, buy, sell, row):
        if row.get('corporate_action_adjustments'):
            raise ValueError('corporate adjustment requires separate plan')
        if buy['last'] > sell['first']:
            raise ValueError('interleaved/future BUY evidence')
        if utc_time(row.get('entry_time')) > utc_time(row.get('exit_time')):
            raise ValueError('invalid ledger chronology')
        for action in self.activities:
            if action.get('symbol') == symbol and action.get('activity_type') == 'SPLIT':
                action_date = day_time(action.get('date')).date()
                if buy['first'].date() <= action_date <= sell['last'].date():
                    raise ValueError('split affected; separate reconstruction required')


def _records(state):
    return [(collection, i, row) for collection in ('trades', 'quarantined_trades')
            for i, row in enumerate(state.get(collection, []))]


def _sell_rows(state, order_id):
    records = [(collection, index, row) for collection, index, row in _records(state)
               if row.get('exit_broker_order_id') == order_id]
    if not records or any(c != 'trades' or r.get('status') != 'closed' for c, _, r in records):
        raise ValueError('missing/ambiguous/quarantined sell rows')
    return [(i, r) for _, i, r in records]


def _change(index, before, after, kind, evidence):
    return dict(row_index=index, kind=kind, before=deepcopy(before), after=after,
                pnl_delta=str(cents(D(str(after['pnl']))-D(str(before['pnl'])))), evidence=evidence)


def group_precision(state, orders, activities, order_ids):
    """Propose atomic group precision restoration; recorded row PnL must agree."""
    evidence = Evidence(orders, activities)
    counts = Counter(row.get('broker_order_id') for _, _, row in _records(state))
    if len(order_ids) != len(set(order_ids)):
        raise ValueError('duplicate requested order')
    changes = []
    for oid in order_ids:
        rows = _sell_rows(state, oid)
        symbol = rows[0][1]['symbol']
        sell = evidence.order(oid, 'sell', symbol)
        if sum(whole_quantity(r.get('qty'), 'row quantity') for _, r in rows) != sell['qty']:
            raise ValueError('sell group quantity mismatch')
        group = []
        for index, row in rows:
            if row['symbol'] != symbol or counts[row.get('broker_order_id')] != 1:
                raise ValueError('shared/partial/quarantined BUY linkage')
            buy = evidence.order(row.get('broker_order_id'), 'buy', symbol)
            qty = whole_quantity(row['qty'], 'row quantity')
            if qty != buy['qty']:
                raise ValueError('partial BUY not eligible for precision-only')
            evidence.no_split(symbol, buy, sell, row)
            if utc_time(row['exit_time']) < sell['last']:
                raise ValueError('whole-order row predates final execution')
            pnl = cents(qty*sell['price']-buy['notional'])
            if pnl != D(str(row['pnl'])):
                raise ValueError('raw cash PnL differs; not precision-only')
            if any(abs(decimal_value(row[field], field)-price) > D('.005')
                   for field, price in [('entry_price', buy['price']), ('exit_price', sell['price'])]):
                raise ValueError('outside half-cent precision interval')
            after = deepcopy(row)
            after.update(entry_price=float(buy['price']), exit_price=float(sell['price']))
            if after != row:
                group.append(_change(index,row,after,'precision_only',dict(
                    buy_notional=str(buy['notional']), sell_order_notional=str(sell['notional']),
                    allocated_proceeds=str(qty*sell['price']),
                    activity_ids=[a['id'] for a in buy['parts']+sell['parts']])))
        changes.extend(group)
    return changes


def _check_revisions(sell, revisions, boundaries):
    prior_qty, prior_consumed = 0, 0
    consumed_points = set()
    selected = [r for r in revisions if r.get('order_id') == sell['order']['id']]
    for row in selected:
        if (row.get('side'), row.get('symbol')) != ('sell',sell['order']['symbol']):
            raise ValueError('revision identity mismatch')
        qty = whole_quantity(row.get('qty'), 'revision quantity')
        consumed = whole_quantity(row.get('consumed_qty',0), 'consumed quantity', positive=False)
        if qty < prior_qty or consumed < prior_consumed or consumed > qty or qty not in sell['prefixes']:
            raise ValueError('revision quantity/consumption conflict')
        if abs(qty*decimal_value(row.get('price'),'revision price')-sell['prefixes'][qty]) >= D('.01'):
            raise ValueError('revision notional does not match raw fill prefix')
        prefix_end=next(a['transaction_time'] for a in sell['parts'] if int(a['cum_qty'])==qty)
        if utc_time(row.get('filled_at')) < utc_time(prefix_end):
            raise ValueError('revision predates matching raw prefix')
        if consumed == qty:
            consumed_points.add(qty)
        prior_qty, prior_consumed = qty, consumed
    if not selected or prior_qty != sell['qty'] or prior_consumed != sell['qty'] or not set(boundaries) <= consumed_points:
        raise ValueError('missing consumed prefix boundary evidence')


def partial_economics(state, orders, activities, revisions, order_ids):
    """Propose numeric corrections for fully evidenced partial-exit rows.

Does not update global summaries, observation timestamps, events or watermarks.
Those are explicit migration dependencies, not repaired by a numerical plan.
"""
    evidence = Evidence(orders, activities)
    if len(order_ids) != len(set(order_ids)):
        raise ValueError('duplicate requested order')
    changes = []
    for oid in order_ids:
        rows = _sell_rows(state, oid)
        buyids = {r.get('broker_order_id') for _, r in rows}
        if len(buyids) != 1:
            raise ValueError('partial-exit allocation across BUY lots not supported')
        symbol = rows[0][1]['symbol']
        buy = evidence.order(next(iter(buyids)), 'buy', symbol)
        sell = evidence.order(oid, 'sell', symbol)
        related = [(c, i, r) for c, i, r in _records(state) if r.get('broker_order_id') in buyids]
        if any(c != 'trades' or r.get('status') != 'closed' for c, _, r in related):
            raise ValueError('open/quarantined BUY lifecycle')
        if sum(whole_quantity(r.get('qty'),'lifecycle quantity') for _, _, r in related) != buy['qty']:
            raise ValueError('incomplete/duplicated BUY lifecycle')
        # Outside this proposal, the remaining exits of the same BUY must already
        # reconcile economically; do not silently leave related cost errors.
        for other in {r.get('exit_broker_order_id') for _,_,r in related}-{oid}:
            other_rows = _sell_rows(state,other)
            if any(r.get('broker_order_id') not in buyids for _,r in other_rows):
                raise ValueError('other exit shares unsupported BUY lots')
            proof = evidence.order(other,'sell',symbol)
            if sum(r['qty'] for _,r in other_rows) != proof['qty']:
                raise ValueError('other exit quantity mismatch')
            if sum(D(str(r['pnl'])) for _,r in other_rows) != cents(proof['notional']-buy['price']*proof['qty']):
                raise ValueError('other exit cash PnL mismatch')
            if any(abs(decimal_value(r['entry_price'],'other entry')-buy['price']) > D('.00000001') for _,r in other_rows):
                raise ValueError('other exit BUY basis differs')
            for _,r in other_rows: evidence.no_split(symbol,buy,proof,r)
        rows = sorted(rows,key=lambda item:utc_time(item[1].get('exit_time')))
        if len({utc_time(r.get('exit_time')) for _,r in rows}) != len(rows):
            raise ValueError('ambiguous partial-row ordering')
        total, boundaries = 0, []
        for _, row in rows:
            total += whole_quantity(row.get('qty'),'row quantity')
            boundaries.append(total)
        if total != sell['qty'] or not set(boundaries) <= set(sell['prefixes']):
            raise ValueError('row boundary does not match complete raw fills')
        _check_revisions(sell,revisions,boundaries)
        lower = 0
        for (index,row),upper in zip(rows,boundaries):
            if row['symbol'] != symbol:
                raise ValueError('row symbol mismatch')
            evidence.no_split(symbol,buy,sell,row)
            qty = upper-lower
            proceeds = sell['prefixes'][upper]-sell['prefixes'][lower]
            cost = qty*buy['price']
            parts = [a for a in sell['parts'] if lower < int(a['cum_qty']) <= upper]
            if utc_time(row['exit_time']) < utc_time(parts[-1]['transaction_time']):
                raise ValueError('partial row predates matching execution interval')
            after=deepcopy(row)
            after.update(entry_price=float(buy['price']),exit_price=float(proceeds/qty),
                         pnl=float(cents(proceeds-cost)),return_pct=float((proceeds-cost)/cost))
            if after != row:
                changes.append(_change(index,row,after,'economic_correction',dict(
                    cumulative_qty_before=lower,cumulative_qty_after=upper,
                    allocated_buy_cost=str(cost),raw_proceeds=str(proceeds),
                    actual_execution_start=parts[0]['transaction_time'],actual_execution_end=parts[-1]['transaction_time'],
                    activity_ids=[a['id'] for a in buy['parts']+parts])))
            lower=upper
    return changes


def project_rows(state, changes):
    """In-memory row projection only; no complete/consistent ledger claim."""
    out=deepcopy(state['trades'])
    indices=[c['row_index'] for c in changes]
    if len(indices)!=len(set(indices)):
        raise ValueError('overlapping repair proposals')
    for change in changes:
        index=change['row_index']
        if not isinstance(index,int) or index<0 or index>=len(out):
            raise ValueError('invalid target row index')
        if out[index]==change['after']:
            continue
        if out[index]!=change['before']:
            raise ValueError('stale repair base')
        out[index]=deepcopy(change['after'])
    return out


def corporate_plan(state, orders, activities, symbol, cutoff):
    """Scoped full-history FIFO proposal; never guesses a split target lot."""
    end=day_time(cutoff)
    selected=[o for o in orders if o.get('symbol')==symbol and o.get('status')=='filled' and utc_time(o.get('filled_at'))<end]
    actions=[a for a in activities if a.get('symbol')==symbol and a.get('activity_type')=='SPLIT' and day_time(a.get('date'))<end]
    evidence=Evidence(orders,activities)
    normalized=[]
    for order in selected:
        proof=evidence.order(order['id'],order['side'],symbol)
        normalized.append(dict(order,filled_avg_price=str(proof['price'])))
    closed,opened=match_order_completion_fifo(normalized,split_activities=actions)
    if not selected or opened:
        raise ValueError('corporate scope incomplete or remaining inventory')
    # Opposite-side order executions may not overlap when using completion FIFO.
    proofs=[evidence.order(o['id'],o['side'],symbol) for o in selected]
    for a in proofs:
        for b in proofs:
            if a['order']['side']!=b['order']['side'] and max(a['first'],b['first'])<=min(a['last'],b['last']):
                raise ValueError('interleaved executions require execution-level allocation')
    records=[(c,i,r) for c,i,r in _records(state) if r.get('symbol')==symbol and r.get('exit_time') and utc_time(r['exit_time'])<end]
    if any(r.get('broker_order_id') not in evidence.orders or r.get('exit_broker_order_id') not in evidence.orders for _,_,r in records):
        raise ValueError('unknown historical row order')
    active=[r for c,_,r in records if c=='trades' and r.get('status')=='closed']
    old=sum((D(str(r['pnl'])) for r in active),D(0));new=sum((D(str(r['pnl'])) for r in closed),D(0))
    cash=sum((p['notional']*(1 if p['order']['side']=='sell' else -1) for p in proofs),D(0))
    if cents(cash)!=new:
        raise ValueError('leg rounding residual requires explicit treatment')
    for row in closed:
        row['holding_days']=round((utc_time(row['exit_time'])-utc_time(row['entry_time'])).total_seconds()/86400,4)
    mapping=[dict(collection=c,row_index=i,
                  candidate_leg_ids=[t['execution_leg_id'] for t in closed if t['exit_broker_order_id']==r.get('exit_broker_order_id')],
                  link_basis='same SELL order; corrected BUY identity must come from FIFO evidence') for c,i,r in records]
    return dict(kind='corporate_reconstruction',symbol=symbol,cutoff=cutoff,apply_ready=False,
                old_active_pnl=str(cents(old)),new_active_pnl=str(cents(new)),pnl_delta=str(cents(new-old)),
                cash_pnl=str(cents(cash)),retire_records=[dict(collection=c,row_index=i,before=deepcopy(r)) for c,i,r in records],
                candidate_rows=closed,replacement_links=mapping,
                new_exit_orders_without_old_rows=[t['exit_broker_order_id'] for t in closed if not any(r.get('exit_broker_order_id')==t['exit_broker_order_id'] for _,_,r in records)],
                unchanged_original_quarantine=True,
                remaining_requirements=['explicit supersession/tombstones across active and quarantine copies',
                    'correction events with legacy references; no duplicate consumption',
                    'global summaries and drawdown/snapshot lineage; atomic migration and recovery'],
                time_basis='broker date-only split ordered before UTC day orders; availability retained; not PIT evidence')
