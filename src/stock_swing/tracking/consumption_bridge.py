"""Explicit reviewed consumption bridge; never called automatically by settlement.

Append fill revisions with labelled post-hoc accounting evidence, not fictitious
broker executions or historical consumer timestamps. State/events are read-only
dependencies. Caller must separately verify source order/account evidence.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from .execution_cost import whole_quantity, incremental_sell_fill
from .execution_fifo import utc_time
from .fill_ledger import FillLedger
from .history_migration import parse_events, active_events, validate_history_pair, _validate_closed
from .ledger_transaction import FILES, LedgerConflict, digest, json_revision, ledger_transaction


def _canonical(raw):
    result={}
    for line in raw.decode().splitlines():
        if not line.strip():continue
        row=json.loads(line)
        if not isinstance(row,dict) or not isinstance(row.get('fill_id'),str) or not row['fill_id']:
            raise LedgerConflict('invalid fill observation identity')
        key=row['fill_id']
        if key in result and any(result[key].get(k)!=row.get(k) for k in ['order_id','symbol','side']):
            raise LedgerConflict('fill identity changed across revisions')
        result[key]=row
    return result


def _check_snapshot(raw, canonical):
    saved=json.loads(raw)
    if not isinstance(saved,dict) or not isinstance(saved.get('fills'),list):
        raise LedgerConflict('invalid consumed snapshot')
    snap={r['fill_id']:r for r in saved['fills']}
    if len(snap)!=len(saved['fills']) or set(snap)!=set(canonical):
        raise LedgerConflict('consumed snapshot/canonical fill set mismatch')
    for key,fill in canonical.items():
        # Compare-and-swap alone cannot make two equally corrupt copies valid.
        # Validate raw observations before FillLedger normalizes legacy fields,
        # and on retry as well as while preparing a new bridge.
        qty=whole_quantity(fill.get('qty'),'observed qty',positive=False)
        consumed=whole_quantity(fill.get('consumed_qty',qty if fill.get('consumed') else 0),
                                'consumed qty',positive=False)
        if consumed>qty:
            raise LedgerConflict('consumed quantity exceeds observed quantity')
        expected=bool(qty>0 and consumed==qty and not fill.get('quarantine_reason'))
        if not isinstance(fill.get('consumed'),bool) or fill['consumed']!=expected:
            raise LedgerConflict('consumed flag contradicts quantities')
        history=fill.get('consumption_events',[])
        if not isinstance(history,list):raise LedgerConflict('invalid consumption history')
        total=0
        for event in history:
            if not isinstance(event,dict) or not isinstance(event.get('trade_id'),str) or not event['trade_id']:
                raise LedgerConflict('invalid consumption event identity')
            total+=whole_quantity(event.get('qty'),'consumption event qty')
            utc_time(event.get('consumed_at'))
        if total!=consumed:
            raise LedgerConflict('consumption events disagree with watermark')
        if history and (fill.get('consumed_by')!=history[-1]['trade_id']
                        or utc_time(fill.get('consumed_at'))!=utc_time(history[-1]['consumed_at'])):
            raise LedgerConflict('latest consumer contradicts event history')
        if any(snap[key].get(k)!=fill.get(k) for k in ['order_id','symbol','side','qty','consumed_qty','consumed','consumed_by','quarantine_reason']):
            raise LedgerConflict('consumed snapshot differs from canonical fill')
        if snap[key].get('consumption_events',[])!=fill.get('consumption_events',[]):
            raise LedgerConflict('consumed snapshot loses consumption events')
    return snap


def _event(entry, intent, bridge_id):
    return dict(trade_id='historical-bridge:'+bridge_id+':'+entry['order']['id'],
                qty=entry['target_qty']-entry['prior_consumed'],
                consumed_at=intent['recorded_at'],kind='historical_accounting_bridge',
                not_broker_execution=True,bridge_id=bridge_id,
                ledger_revision=intent['ledger_revision'],
                evidence_sha256=intent['evidence_sha256'],
                reviewed_rows_sha256=entry['rows_sha256'],
                reviewed_events_sha256=entry['events_sha256'],
                source_order_sha256=json_revision(entry['order']))


def prepare_bridge(inputs, orders, *, evidence_sha256, recorded_at):
    """Pure four-file CAS plan; only exact active closed/order/event matches qualify."""
    try:
        if set(inputs)!=FILES or any(not isinstance(b,bytes) for b in inputs.values()):
            raise LedgerConflict('four frozen financial files required')
        utc_time(recorded_at)
        if (not isinstance(evidence_sha256,str) or len(evidence_sha256)!=64
                or any(c not in '0123456789abcdef' for c in evidence_sha256)):
            raise LedgerConflict('review evidence digest required')
        state=json.loads(inputs['pnl_state.json']);events=parse_events(inputs['trade_events.jsonl'])
        validate_history_pair(state,events)
        revision=state.get('measurement_lineage',{}).get('ledger_revision')
        if not revision or not state.get('history_migrations'):
            raise LedgerConflict('reviewed corrected history required before consumption bridge')
        canonical=_canonical(inputs['fill_ledger.jsonl'])
        snap=_check_snapshot(inputs['fill_consumed_ledger.json'],canonical)
        economic=[e for e in active_events(events) if e['event_type']=='trade_closed']
        if not isinstance(orders,list):raise LedgerConflict('orders must be an explicit list')
        seen=set();entries=[];counts=Counter();normalized=[]
        for raw in orders:
            order={k:raw[k] for k in ['id','symbol','side','filled_qty','filled_avg_price','filled_at','status'] if k in raw}
            oid=order.get('id')
            if not isinstance(oid,str) or not oid or oid in seen:raise LedgerConflict('duplicate/missing order identity')
            seen.add(oid);normalized.append(order);utc_time(order.get('filled_at'))
            if any(r.get('exit_broker_order_id')==oid for r in state.get('quarantined_trades',[])):
                raise LedgerConflict('unresolved quarantined execution in order scope')
            rows=[r for r in state['trades'] if r.get('exit_broker_order_id')==oid]
            if not rows:raise LedgerConflict('order has no active closed legs')
            for row in rows:_validate_closed(row)
            # Validate the immutable cumulative order quantity/notional against
            # all active legs, including the existing precision tolerance.
            delta=incremental_sell_fill(order,rows)
            if delta.qty:raise LedgerConflict('order has unrecorded economic quantity')
            matches=[e for e in economic if e.get('broker_order_id')==oid]
            def row_key(row):
                return (row['trade_id'],row.get('execution_leg_id'),row['broker_order_id'],
                        whole_quantity(row['qty'],'leg qty'),Decimal(str(row['pnl'])),Decimal(str(row['exit_price'])))
            def event_key(event):
                p=event['payload']
                if event['symbol']!=order['symbol']:raise LedgerConflict('event symbol mismatch')
                return (event['trade_id'],p.get('execution_leg_id'),p.get('entry_broker_order_id'),
                        whole_quantity(p['exit_qty'],'event qty'),Decimal(str(p['pnl'])),Decimal(str(p['exit_price'])))
            if Counter(map(row_key,rows))!=Counter(map(event_key,matches)):
                raise LedgerConflict('active economic events differ from closed legs')
            fill=canonical.get(oid);target=delta.prior_qty
            if any(r.get('order_id')==oid and key!=oid for key,r in canonical.items()):
                raise LedgerConflict('ambiguous order aggregate fill identity')
            if fill is None:
                consumed=0;category='missing_observation'
            else:
                if (fill.get('order_id')!=oid or fill.get('symbol')!=order['symbol']
                        or fill.get('side')!='sell' or fill.get('quarantine_reason')):
                    raise LedgerConflict('conflicting/quarantined canonical fill')
                qty=whole_quantity(fill['qty'],'observed qty')
                consumed=whole_quantity(fill.get('consumed_qty',qty if fill.get('consumed') else 0),'consumed qty',positive=False)
                if qty>target or consumed>qty or consumed>target:
                    raise LedgerConflict('watermark or observation ahead of closed evidence')
                old=snap[oid]
                if (old.get('qty')!=fill.get('qty') or old.get('consumed_qty')!=fill.get('consumed_qty')
                        or old.get('consumption_events',[])!=fill.get('consumption_events',[])):
                    raise LedgerConflict('consumed snapshot differs from canonical fill')
                category='equal' if consumed==target else 'partial_watermark' if consumed else 'zero_watermark'
            counts[category]+=1
            if consumed<target:
                entries.append(dict(order=order,prior_consumed=consumed,target_qty=target,category=category,
                                    rows_sha256=json_revision(rows),events_sha256=json_revision(matches),
                                    original_row_hashes=[json_revision(r) for r in rows],
                                    original_event_hashes=[json_revision(e) for e in matches],
                                    original_consumption_events=deepcopy(fill.get('consumption_events',[])) if fill else []))
        intent=dict(schema_version=1,before_sha256={n:digest(b) for n,b in sorted(inputs.items())},
                    ledger_revision=revision,evidence_sha256=evidence_sha256,recorded_at=recorded_at,
                    orders=normalized,entries=entries)
        return dict(bridge_id=json_revision(intent),intent=intent,
                    summary=dict(orders_reviewed=len(orders),categories=dict(counts),bridged_orders=len(entries),
                                 bridged_qty=sum(e['target_qty']-e['prior_consumed'] for e in entries),
                                 economic_change=0,source_truth_independently_certified_here=False,
                                 production_applied=False,measurement_gate_passed=False))
    except (KeyError,TypeError,AttributeError,UnicodeError,ValueError) as exc:
        raise LedgerConflict('invalid bridge review evidence') from exc


def apply_bridge(project_root, plan):
    """Explicit application; no automatic discovery, broker call, or PnL rewrite.

    Reuse the existing cooperating four-file lock and recoverable journal. The
    original fill log remains a byte prefix; the consumed snapshot is derived.
    A plan hash binds reviewed evidence, not owner approval or truth attestation.
    """
    root=Path(project_root)
    try:
        intent=plan['intent'];bid=plan['bridge_id']
        if json_revision(intent)!=bid:raise LedgerConflict('bridge intent hash mismatch')
        with ledger_transaction(root) as tx:
            folder=root/'data/tracking';inputs={n:tx.read(folder/n) for n in FILES}
            if any(b is None for b in inputs.values()):raise LedgerConflict('missing bridge dependency')
            state=json.loads(inputs['pnl_state.json']);events=parse_events(inputs['trade_events.jsonl'])
            validate_history_pair(state,events)
            _check_snapshot(inputs['fill_consumed_ledger.json'],_canonical(inputs['fill_ledger.jsonl']))
            if state.get('measurement_lineage',{}).get('ledger_revision')!=intent['ledger_revision']:
                raise LedgerConflict('bridge ledger revision conflict')
            ledger=FillLedger(root);records={r['fill_id']:r for r in ledger.all_fills()}
            found=[]
            for entry in intent['entries']:
                fill=records.get(entry['order']['id'],{})
                markers=[e for e in fill.get('consumption_events',[]) if e.get('bridge_id')==bid]
                if markers and markers!=[_event(entry,intent,bid)]:raise LedgerConflict('bridge marker conflict')
                if markers:
                    prior=entry['original_consumption_events']
                    if fill['consumption_events'][:len(prior)]!=prior or fill['consumption_events'][len(prior)]!=markers[0]:
                        raise LedgerConflict('bridge changed prior consumption history')
                    current={json_revision(r) for r in state['trades']}
                    current_events={json_revision(e) for e in active_events(events)}
                    if (not set(entry['original_row_hashes'])<=current
                            or not set(entry['original_event_hashes'])<=current_events
                            or fill['consumed_qty']<entry['target_qty']):
                        raise LedgerConflict('bridge lost economic dependency')
                found.append(bool(markers))
            if found and all(found):return dict(status='already_applied',bridged_orders=len(found))
            if any(found):raise LedgerConflict('partial bridge markers require investigation')
            # Even an empty reviewed plan binds all four inputs; it performs no writes.
            if {n:digest(b) for n,b in inputs.items()}!=intent['before_sha256']:
                raise LedgerConflict('stale bridge inputs')
            regenerated=prepare_bridge(inputs,intent['orders'],evidence_sha256=intent['evidence_sha256'],recorded_at=intent['recorded_at'])
            if regenerated!=plan:raise LedgerConflict('bridge plan differs from regenerated review')
            for entry in intent['entries']:
                order=entry['order'];key=ledger.ingest(dict(order,qty=order['filled_qty']),quarantine_on_missing=True)
                record=ledger.get(key)
                if record.get('quarantine_reason') or record['consumed_qty']!=entry['prior_consumed']:
                    raise LedgerConflict('bridge observation changed')
                record['consumed_qty']=entry['target_qty'];record['consumed']=True
                event=_event(entry,intent,bid)
                record['consumed_by']=event['trade_id'];record['consumed_at']=intent['recorded_at']
                record['consumption_events']=list(record.get('consumption_events') or [])+[event]
                ledger._append(record)
            return dict(status='applied' if intent['entries'] else 'already_applied',bridged_orders=len(intent['entries']))
    except (KeyError,TypeError,ValueError,AttributeError) as exc:
        raise LedgerConflict('invalid bridge plan or current evidence') from exc
