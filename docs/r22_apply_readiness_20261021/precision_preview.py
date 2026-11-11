"""Pure, opt-in preview of legacy price precision restoration; never deploys.

A row is eligible only if a unique whole BUY/SELL pair and individual broker
fills reproduce its already-recorded cent PnL. Prices change in the returned
copy, but quantity, cash PnL, chronology, identity and quarantine do not.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from datetime import date, datetime, timezone


def number(value):
    try:
        result=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise ValueError('invalid numeric evidence') from exc
    if not result.is_finite():raise ValueError('non-finite evidence')
    return result


def instant(value):
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:raise ValueError('timezone required')
        return result.astimezone(timezone.utc)
    except (ValueError,TypeError,AttributeError) as exc:
        raise ValueError('invalid/naive chronology') from exc


def preview(state, orders, activities):
    out=deepcopy(state); changes=[]; rejected=[]
    ids=[o.get('id') for o in orders]
    if not all(ids) or len(set(ids))!=len(ids):raise ValueError('missing/duplicate order identity')
    byid={o['id']:o for o in orders}
    fills=[a for a in activities if a.get('activity_type')=='FILL']
    fillids=[a.get('id') for a in fills]
    if not all(fillids) or len(set(fillids))!=len(fillids):raise ValueError('missing/duplicate activity identity')
    allrows=state['trades']+state.get('quarantined_trades',[])
    entries=Counter(t.get('broker_order_id') for t in allrows)
    exits=Counter(t.get('exit_broker_order_id') for t in allrows if t.get('status') in {'closed','quarantined'})
    for index,row in enumerate(out['trades']):
        if row.get('status')!='closed':continue
        try:
            buy=byid.get(row.get('broker_order_id'));sell=byid.get(row.get('exit_broker_order_id'))
            if not buy or not sell:raise ValueError('missing paired orders')
            if entries[buy['id']]!=1 or exits[sell['id']]!=1:raise ValueError('partial/multiple/quarantined lot linkage')
            qty=number(row['qty'])
            if qty<=0 or qty!=int(qty):raise ValueError('invalid integer quantity')
            start,end=instant(buy.get('filled_at')),instant(sell.get('filled_at'))
            if start>end or instant(row.get('entry_time'))>instant(row.get('exit_time')):raise ValueError('invalid order/ledger chronology')
            if row.get('corporate_action_adjustments'):raise ValueError('split adjusted row; separate evidence needed')
            for action in activities:
                if action.get('symbol')==row['symbol'] and action.get('activity_type')=='SPLIT':
                    action_date=date.fromisoformat(action.get('date',''))
                    if start.date()<=action_date<=end.date():raise ValueError('split affected; separate evidence needed')
            amounts=[]
            for order,side in [(buy,'buy'),(sell,'sell')]:
                if (order.get('symbol'),order.get('side'),order.get('status'))!=(row['symbol'],side,'filled') or number(order.get('filled_qty'))!=qty:raise ValueError('order identity/status/quantity mismatch')
                parts=[a for a in fills if a.get('order_id')==order['id']]
                if not parts or any((a.get('symbol'),a.get('side'))!=(row['symbol'],side) or number(a.get('qty'))<=0 or number(a.get('price'))<=0 for a in parts):raise ValueError('missing/conflicting fill evidence')
                if sum(number(a['qty']) for a in parts)!=qty:raise ValueError('activity quantity mismatch')
                amount=sum(number(a['qty'])*number(a['price']) for a in parts)
                if abs(amount-qty*number(order.get('filled_avg_price')))>=Decimal('.01'):raise ValueError('order/activity notional mismatch')
                amounts.append(amount)
            cents=(amounts[1]-amounts[0]).quantize(Decimal('.01'),rounding=ROUND_HALF_EVEN)
            if cents!=number(row['pnl']):raise ValueError('raw cash PnL differs; not precision-only')
            old_entry=number(row['entry_price']);old_exit=number(row['exit_price'])
            entry,exit=amounts[0]/qty,amounts[1]/qty
            # This preview restores only cent-rounded representation, not an
            # unexplained price correction even when net errors cancel.
            if abs(old_entry-entry)>Decimal('.005') or abs(old_exit-exit)>Decimal('.005'):raise ValueError('outside half-cent representation interval')
            if float(old_entry)==float(entry) and float(old_exit)==float(exit):continue
            changes.append(dict(row_index=index,symbol=row['symbol'],entry_order=buy['id'],exit_order=sell['id'],
                qty=int(qty),pnl=row['pnl'],entry_before=str(old_entry),entry_after=str(entry),exit_before=str(old_exit),exit_after=str(exit),
                raw_buy_cost=str(amounts[0]),raw_sell_proceeds=str(amounts[1]),
                activity_ids=[a['id'] for a in fills if a.get('order_id') in {buy['id'],sell['id']}]))
            row['entry_price']=float(entry);row['exit_price']=float(exit)
        except (ValueError,KeyError,TypeError) as exc:
            rejected.append(dict(row_index=index,symbol=row.get('symbol'),reason=str(exc)))
    return out,changes,rejected
